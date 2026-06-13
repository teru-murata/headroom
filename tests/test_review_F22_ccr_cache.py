"""RED test for finding F22-ccr-cache.

Claim (NN1, fork-local, major):
  ``CompressionStore._emit_ledger_retrieved_event`` (compression_store.py L424-455)
  emits ``bridge.ccr.retrieved`` with ``saved_tokens = original_tokens - compressed_tokens``
  taken VERBATIM from ``CompressionEntry`` fields that the producer supplied at
  ``store()`` time (kwargs default 0, never recounted). A producer can assert any
  savings it likes; the bridge presents it as measured CCR savings without
  recounting the actual original/compressed content.

This test stores an entry whose SELF-REPORTED tokens (1000 -> 100, "saved 900")
wildly disagree with the REAL content (original is tiny, compressed is large).
A trustworthy bridge would recount the real content and emit savings consistent
with what is actually stored. If the bridge instead trusts the self-reported
numbers, ``saved_tokens`` will be the unmeasured 900.

RED expectation: with the defect present, the emitted ``saved_tokens`` == 900
(the fabricated figure), which is impossible given the real content (the
"compressed" payload is actually LARGER than the "original"). The assertion that
the ledger reflect reality therefore FAILS today.
"""

from __future__ import annotations

import pytest

from headroom.cache.compression_store import CompressionStore
from headroom.telemetry import ledger as ledger_mod
from headroom.telemetry.ledger import (
    InMemoryLedgerEmitter,
    reset_ledger_emitter,
    set_ledger_emitter,
)


def _count_tokens(text: str) -> int:
    """A simple, honest token estimate (whitespace words).

    Any reasonable measurement of the real content would agree this is a fine
    lower bound; the point is only that the real counts are nowhere near the
    self-reported 1000 -> 100.
    """
    return len(text.split())


@pytest.fixture
def capture_ledger():
    reset_ledger_emitter()
    emitter = InMemoryLedgerEmitter()
    set_ledger_emitter(emitter)
    try:
        yield emitter
    finally:
        reset_ledger_emitter()


def test_ledger_retrieved_recounts_savings(capture_ledger: InMemoryLedgerEmitter) -> None:
    emitter = capture_ledger
    store = CompressionStore(enable_feedback=False)

    # REAL content: the "original" is tiny and the "compressed" payload is
    # actually LARGER. Honestly measured, this entry SAVED NOTHING (in fact it
    # grew). Real saved tokens <= 0.
    original = "alpha beta"  # 2 words
    compressed = " ".join(f"row{i}" for i in range(50))  # 50 words, bigger

    real_original_tokens = _count_tokens(original)
    real_compressed_tokens = _count_tokens(compressed)
    real_saved = max(real_original_tokens - real_compressed_tokens, 0)
    assert real_saved == 0  # sanity: the real content saved nothing

    # SELF-REPORTED (fabricated) savings the producer asserts.
    hash_key = store.store(
        original,
        compressed,
        original_tokens=1000,
        compressed_tokens=100,
        compression_strategy="fabricated",
    )

    result = store.retrieve(hash_key)
    assert result is not None

    retrieved_events = [
        e for e in emitter.events if e.event_type == "bridge.ccr.retrieved"
    ]
    assert len(retrieved_events) == 1, "expected exactly one ledger retrieve event"
    event = retrieved_events[0]

    # A truthful bridge would emit savings consistent with the real content.
    # With the defect, saved_tokens is the unmeasured fabricated 900.
    assert event.saved_tokens == real_saved, (
        "Ledger reported unmeasured CCR savings: emitted saved_tokens="
        f"{event.saved_tokens} but the real content's measured savings is "
        f"{real_saved} (original {real_original_tokens} tok, compressed "
        f"{real_compressed_tokens} tok). The bridge took producer-supplied "
        "token counts verbatim with no recount."
    )
