"""RED test for finding F19-transforms (partition: transforms, NN4).

Claim under test
----------------
The broad ``except Exception`` in ``ContentRouter._apply_strategy_to_content``
(content_router.py:1340-1343) catches any compressor failure, logs at
WARNING, sets ``compressed`` to None, and falls through to the passthrough
tail (1427-1449) which returns ``(content, original_tokens, strategy_chain)``
unchanged.

The resulting ``RoutingDecision`` therefore has ``original_tokens ==
compressed_tokens`` (zero savings) — bit-for-bit identical to a legitimately
non-compressible input that genuinely passed through. The ``CompressionObserver``
(the operator-visible metrics surface) only receives
``record_compression(strategy, original_tokens, compressed_tokens)``; there is
no failure channel. So a crashing compressor and a no-op input look identical
to per-strategy savings metrics: operators get NO distinct failure signal.

This module isolates TOIN to a tempdir so the global on-disk learning store is
never touched, and resets the TOIN singleton before/after.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from headroom.transforms.content_router import (
    CompressionStrategy,
    ContentRouter,
    ContentRouterConfig,
)
from headroom.telemetry.toin import TOIN_PATH_ENV_VAR, reset_toin


@dataclass
class SpyObserver:
    """Captures every ``record_compression`` call the router emits."""

    calls: list[tuple[str, int, int]] = field(default_factory=list)

    def record_compression(
        self, strategy: str, original_tokens: int, compressed_tokens: int
    ) -> None:
        self.calls.append((strategy, original_tokens, compressed_tokens))


class _RaisingCompressor:
    """Stub compressor whose compress() always crashes."""

    def compress(self, *_a, **_kw):  # noqa: ANN002, ANN003
        raise RuntimeError("compressor exploded")


class _NoOpCompressor:
    """Stub compressor that succeeds but cannot shrink the input
    (returns it unchanged) — a *legitimate* non-compressible result."""

    def __init__(self, content: str) -> None:
        self._content = content

    def compress(self, *_a, **_kw):  # noqa: ANN002, ANN003
        @dataclass
        class _R:
            compressed: str

        return _R(compressed=self._content)


@pytest.fixture(autouse=True)
def _isolated_toin(tmp_path, monkeypatch):
    """Keep the global TOIN store off real disk for this module."""
    monkeypatch.setenv(TOIN_PATH_ENV_VAR, str(tmp_path / "toin.jsonl"))
    reset_toin()
    yield
    reset_toin()


def _run_log_strategy(compressor) -> tuple[str, int, list[str]]:
    """Route a fixed input through the LOG strategy with the given
    (stub) log compressor injected, returning the raw 3-tuple from the
    cited method ``_apply_strategy_to_content``."""
    router = ContentRouter(ContentRouterConfig(enable_log_compressor=True))
    # Pre-seed the lazy slot so _get_log_compressor() returns our stub.
    router._log_compressor = compressor
    content = "INFO line one\nINFO line two\nINFO line three"
    return router._apply_strategy_to_content(
        content, CompressionStrategy.LOG, context=""
    )


def test_crashing_compressor_is_distinguishable_from_legit_passthrough():
    """A compressor that *crashes* must surface a signal that an operator
    can tell apart from a legitimate no-op passthrough.

    We compare the full observable surface of both events:
      * the 3-tuple returned by the cited method, and
      * the observer notification the router would emit.

    If the two are byte-for-byte identical, there is no operator-visible
    failure signal — which is exactly the F19 defect. This assertion FAILS
    today (RED) and would pass only once failures surface a distinct marker.
    """
    content = "INFO line one\nINFO line two\nINFO line three"

    # (a) Crashing compressor → exception path → passthrough tail.
    crash_out = _run_log_strategy(_RaisingCompressor())

    # (b) Legitimate non-compressible input → compressor returns content
    #     unchanged, no exception.
    noop_out = _run_log_strategy(_NoOpCompressor(content))

    crash_compressed, crash_tokens, crash_chain = crash_out
    noop_compressed, noop_tokens, noop_chain = noop_out

    # Both produce zero savings and the same output text...
    assert crash_compressed == content
    assert noop_compressed == content
    assert crash_tokens == noop_tokens

    # ...and the defect: the strategy_chain (the only structured per-decision
    # breadcrumb a log/metrics reader gets) is ALSO identical, so a crash is
    # indistinguishable from a benign no-op. This assertion is the RED.
    assert crash_chain != noop_chain, (
        "F19: a crashing compressor produces the same strategy_chain "
        f"({crash_chain!r}) as a legitimate non-compressible passthrough "
        f"({noop_chain!r}); operators get no distinct failure signal."
    )


def test_observer_receives_distinct_failure_signal_on_compressor_crash():
    """End-to-end through the observer surface: when a compressor crashes,
    the metrics-facing observer must be able to tell it apart from a
    legitimate passthrough.

    Today the observer only ever sees ``(strategy, N, N)`` for both, so this
    FAILS (RED). Green requires a distinct failure-visible signal (e.g. an
    'error' strategy tag, a failure counter, or compressed_tokens sentinel).
    """
    content = "INFO line one\nINFO line two\nINFO line three"

    # Crash case
    crash_spy = SpyObserver()
    crash_router = ContentRouter(
        ContentRouterConfig(enable_log_compressor=True), observer=crash_spy
    )
    crash_router._log_compressor = _RaisingCompressor()
    crash_router._observe(
        crash_router._compress_pure(content, CompressionStrategy.LOG, context="")
    )

    # Legitimate passthrough case
    noop_spy = SpyObserver()
    noop_router = ContentRouter(
        ContentRouterConfig(enable_log_compressor=True), observer=noop_spy
    )
    noop_router._log_compressor = _NoOpCompressor(content)
    noop_router._observe(
        noop_router._compress_pure(content, CompressionStrategy.LOG, context="")
    )

    assert crash_spy.calls, "observer should have been notified for the crash case"
    assert noop_spy.calls, "observer should have been notified for the no-op case"

    # The defect: the observer gets identical notifications for a crash and a
    # benign no-op. There is no failure channel in the metrics surface.
    assert crash_spy.calls != noop_spy.calls, (
        "F19: CompressionObserver receives identical record_compression() "
        f"calls for a crashing compressor ({crash_spy.calls!r}) and a "
        f"legitimate passthrough ({noop_spy.calls!r}); a crashing compressor "
        "and a no-op input are indistinguishable in operator metrics."
    )
