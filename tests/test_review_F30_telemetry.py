"""RED test for finding F30-telemetry.

Claim: JsonlLedgerEmitter._emit catches all exceptions and only re-raises when
strict=True (the env-built default is strict=False). A write failure (full
disk, permission error, serialization fault) silently drops the provenance
event behind a single logger.warning, with NO counter, health signal, or
metric. Operators lose attribution events invisibly (NN4 silent degradation).

This test forces a write failure with strict=False and asserts that some
surfaced, queryable failure signal (a drop counter / health attribute) is
incremented. If the bug is real, no such signal exists and this FAILS today.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from headroom.telemetry.ledger import (
    JsonlLedgerEmitter,
    LedgerEvent,
    reset_ledger_emitter,
)


@pytest.fixture(autouse=True)
def _clean_state() -> Generator[None, None, None]:
    reset_ledger_emitter()
    try:
        yield
    finally:
        reset_ledger_emitter()


def _find_failure_counter(emitter: JsonlLedgerEmitter) -> int:
    """Locate a surfaced write-failure / drop counter on the emitter.

    Accepts any reasonably named integer counter or a callable health-signal
    accessor. Returns the current count. Raises AssertionError if no such
    surfaced failure signal exists at all (which is the F30 defect).
    """
    candidate_names = (
        "dropped_events",
        "drop_count",
        "dropped_count",
        "failed_writes",
        "write_failures",
        "failure_count",
        "emit_failures",
        "errors",
        "error_count",
    )
    for name in candidate_names:
        if hasattr(emitter, name):
            value = getattr(emitter, name)
            if callable(value):
                value = value()
            return int(value)

    # Allow a structured health-signal accessor instead of a bare attribute.
    for accessor in ("health", "stats", "metrics", "get_health", "get_stats"):
        if hasattr(emitter, accessor):
            obj = getattr(emitter, accessor)
            if callable(obj):
                obj = obj()
            for key in candidate_names:
                if isinstance(obj, dict) and key in obj:
                    return int(obj[key])
                if hasattr(obj, key):
                    return int(getattr(obj, key))

    raise AssertionError(
        "JsonlLedgerEmitter exposes no write-failure / drop counter or health "
        "signal; dropped provenance events are invisible to operators (F30)."
    )


def test_silent_drop_increments_surfaced_failure_counter(tmp_path: Path) -> None:
    # Make the ledger parent path un-creatable: a regular file sits where a
    # directory must be, so mkdir(parents=True) raises inside _emit.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    ledger_path = blocker / "subdir" / "ledger.jsonl"

    # strict=False mirrors the env-built default (_build_env_emitter, l.287).
    emitter = JsonlLedgerEmitter(ledger_path, strict=False)

    before = _find_failure_counter(emitter)

    event = LedgerEvent.create(event_type="compression")
    # Must NOT raise (strict=False) -- the event is dropped instead.
    emitter.emit(event)

    # Nothing was actually written.
    assert not ledger_path.exists()

    after = _find_failure_counter(emitter)
    assert after == before + 1, (
        "A silently dropped ledger write must increment a surfaced failure "
        f"counter; counter went {before} -> {after}."
    )
