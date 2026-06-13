"""RED test for F31-telemetry (NN4, fork-local).

Claim: ``CodingAgentPreset._emit_ledger_event`` wraps the entire bridge.*
ledger emission in ``except Exception`` -> logger.warning. When the
ledger emitter's ``emit()`` raises, ``route_and_compress`` still returns a
successful ``CodingAgentPresetResult``. So a compression that "completed"
can have NO corresponding bridge.compression.completed/bypassed ledger
event AND no error signal -> a provenance gap invisible to operators.

This test injects an emitter whose ``emit()`` raises and asserts that the
emission failure is SURFACED (counter, flag, or raise) instead of silently
swallowed while reporting success. It FAILS today; it would pass once
emission failures are made observable.
"""

from headroom.presets.coding_agent import CodingAgentPreset


class _ExplodingEmitter:
    """Stand-in ledger emitter whose emit() always raises."""

    def __init__(self) -> None:
        self.calls = 0

    def emit(self, event):  # noqa: ANN001
        self.calls += 1
        raise RuntimeError("ledger backend unavailable")


def test_emission_failure_is_surfaced_not_swallowed():
    emitter = _ExplodingEmitter()
    preset = CodingAgentPreset(ledger_emitter=emitter)

    # A normal compression call. The emitter will raise inside
    # _emit_ledger_event for the bridge.compression.* event.
    result = preset.route_and_compress(
        "test_log",
        "ERROR: build failed\n" * 50,
        metadata={"source_id": "F31-red"},
    )

    # The emitter was actually invoked (so the failure path was exercised).
    assert emitter.calls == 1, "emitter.emit() should have been called once"

    # The compression "succeeded" from the caller's perspective.
    assert result is not None
    assert result.compressed is not None

    # CORE ASSERTION: an operator must be able to detect that the ledger
    # event for this successful compression never landed. Today the failure
    # is swallowed by `except Exception -> logger.warning`, leaving no
    # programmatic signal. We look for ANY observable signal of the failure.
    observable = _emission_failure_observable(preset, result)
    assert observable, (
        "Ledger emission failed but route_and_compress reported success "
        "with no observable error signal (no counter, no flag, no raise). "
        "Provenance gap is invisible to operators (NN4)."
    )


def _emission_failure_observable(preset, result) -> bool:
    """Return True if there is ANY programmatic signal of emission failure.

    Checks several plausible surfacing mechanisms so the test is fair: a
    failure counter on the preset, a flag/error captured on the result or
    its metadata. If none exist, the failure was silently swallowed.
    """
    # 1) A failure counter / attribute on the preset instance.
    for attr in (
        "ledger_emit_failures",
        "_ledger_emit_failures",
        "ledger_emission_errors",
        "_ledger_emission_errors",
    ):
        val = getattr(preset, attr, None)
        if isinstance(val, int) and val > 0:
            return True
        if isinstance(val, (list, tuple)) and len(val) > 0:
            return True

    # 2) A flag / error recorded on the result object.
    for attr in ("ledger_emit_failed", "ledger_error", "telemetry_error"):
        if getattr(result, attr, None):
            return True

    # 3) A flag / error recorded in result metadata.
    md = getattr(result, "metadata", None) or {}
    for key in (
        "ledger_emit_failed",
        "ledger_error",
        "telemetry_error",
        "ledger_emission_failed",
    ):
        if md.get(key):
            return True

    return False
