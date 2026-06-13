"""RED test for F39-memory.

Claim: `_db_fingerprint` (headroom/memory/sync.py L140-148) hashes only
`count + first 5 memory ids`, ignoring memory content/updated_at. A DB-side
content edit (same id, same count) therefore leaves the fingerprint
unchanged, so the no-op gate in `sync()` skips export and the agent keeps
stale text while logging "no-op — nothing changed".

This focused test reproduces the root cause: mutating one memory's content
(id and count unchanged) must change the fingerprint. If the bug is real,
the two fingerprints are EQUAL and this test FAILS today.
"""

from dataclasses import dataclass

from headroom.memory.sync import _db_fingerprint


@dataclass
class _FakeMemory:
    id: str
    content: str
    updated_at: str = "2026-06-13T00:00:00Z"


def _build_memories() -> list[_FakeMemory]:
    return [
        _FakeMemory(id=f"id-{i:08d}", content=f"original content {i}")
        for i in range(6)
    ]


def test_db_fingerprint_detects_content_edit() -> None:
    memories = _build_memories()
    fp_before = _db_fingerprint(memories)

    # Simulate HierarchicalMemory.update: same id, same count, new content.
    memories[0].content = "EDITED content — this changed materially"
    memories[0].updated_at = "2026-06-13T12:00:00Z"

    fp_after = _db_fingerprint(memories)

    assert fp_before != fp_after, (
        "Fingerprint unchanged after a content edit (same id/count): "
        "the no-op gate would skip export and silently withhold the "
        "updated content while logging 'nothing changed'."
    )
