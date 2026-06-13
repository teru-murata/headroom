"""RED test for finding F38-memory.

Claim: MemoryBridge._check_duplicate (bridge.py L334-350) wraps the dedup
semantic search in a bare `except Exception: return False` with NO logging.
Any backend/embedder/search outage is therefore treated as "not a duplicate",
so _import_section proceeds to save the section anyway. A transient search
failure silently floods the store with duplicate memories, and the
degradation is invisible to operators (no warn/metric).

This test simulates a search outage while a known-duplicate already exists in
the store. If the bug is real, _import_section will (a) save the duplicate AND
(b) emit no log/warning at all.

We assert the fail-open is at minimum VISIBLE: either the import is suppressed
(fail-closed) OR a warning/error is logged when search fails. With the current
bare `except Exception: return False`, neither happens -> test FAILS (red).

Run:
  cd /Users/terum/dev/headroom-fork && PYTHONPATH=. \
    /Users/terum/dev/headroom-fork/.venv-review/bin/python \
    -m pytest tests/test_review_F38_memory.py -q
"""

from __future__ import annotations

import logging

import pytest

from headroom.memory.bridge import MemoryBridge
from headroom.memory.bridge_config import BridgeConfig
from headroom.memory.bridge_parsers import ParsedSection


class _SavedMemory:
    """Minimal stand-in for headroom.memory.models.Memory."""

    def __init__(self, mem_id: str) -> None:
        self.id = mem_id


class _OutageBackend:
    """Backend whose semantic search is down (embedder/search outage),
    but whose save path works fine. Mirrors a transient outage during sync().
    """

    def __init__(self) -> None:
        self.saved: list[str] = []

    async def search_memories(self, *args, **kwargs):
        # Simulate the embedder/search backend hiccup.
        raise RuntimeError("vector search backend unavailable")

    async def save_memory(self, *, content, user_id, importance, entities,
                          relationships, metadata, facts=None):
        self.saved.append(content)
        return _SavedMemory(mem_id=f"mem-{len(self.saved)}")


@pytest.fixture()
def bridge(tmp_path):
    # Isolated, in-tmp sync state; no shared on-disk state touched.
    config = BridgeConfig(
        md_paths=[],
        user_id="reviewer",
        sync_state_path=tmp_path / "bridge_state.json",
        extract_entities=False,
        chunk_by_section=True,
    )
    return MemoryBridge(config, _OutageBackend())


@pytest.mark.asyncio
async def test_check_duplicate_failure_is_visible_not_open(bridge, caplog):
    backend = bridge._backend

    section = ParsedSection(
        heading="Project Overview",
        heading_level=2,
        content="- Headroom: Context optimization layer for LLM applications",
        facts=["Headroom: Context optimization layer for LLM applications"],
    )

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="headroom.memory.bridge"):
        imported_id = await bridge._import_section(
            section, user_id="reviewer", file_path="MEMORY.md"
        )

    saved_count = len(backend.saved)
    logged_failure = any(
        "search" in r.getMessage().lower()
        or "dedup" in r.getMessage().lower()
        or "duplicate" in r.getMessage().lower()
        for r in caplog.records
        if r.levelno >= logging.WARNING
    )

    # The bug: with the search backend down, the dedup check silently returns
    # False, the section is saved, and nothing is logged. That is a SILENT
    # fail-open. We require the degradation to be visible: either no insert on
    # search failure (fail-closed) OR an explicit warn/error signal.
    assert (imported_id is None) or logged_failure, (
        "Silent fail-open: dedup search failed, section was imported anyway "
        f"(saved={saved_count}), and no warning/error was logged "
        "(no failure signal to operators)."
    )
