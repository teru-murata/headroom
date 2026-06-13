"""RED test for F10-proxy-core.

Claim: `_context_tool_summary_payload` trusts the external rtk/lean-ctx
subprocess's self-reported numbers and, when no `tokens_saved`-style key is
present, SYNTHESIZES `tokens_saved = input - output` (helpers.py 1049-1050) and
`savings_pct = saved/input*100` (1067-1068). The defect: an external summary
that reports input/output counters but no saved counter (a plausible JSON-shape
where input/output are *raw token totals*, not before/after-compression sizes)
produces a fabricated, non-zero `tokens_saved` that then surfaces on the
dashboard as a real savings number.

This test feeds a summary lacking every `saved` alias, with input > output, and
asserts that the bridge does NOT silently fabricate a savings figure it never
received from the tool.
"""

from headroom.proxy.helpers import _context_tool_summary_payload


def test_missing_saved_keys_not_fabricated_from_input_minus_output():
    # Summary as a tool might emit it: cumulative input/output token counters,
    # but NO explicit saved/savings field reported by the tool.
    summary = {
        "total_input": 10_000,
        "total_output": 4_000,
        # deliberately: no total_saved / tokens_saved / totalSaved / etc.
        # deliberately: no avg_savings_pct / savings_pct / etc.
    }

    payload = _context_tool_summary_payload(
        tool="rtk",
        installed=True,
        summary=summary,
    )

    # The tool reported NO savings. The bridge must not invent one.
    assert payload["tokens_saved"] == 0, (
        "tokens_saved was fabricated from input-output; the external tool "
        f"never reported a saved figure but got {payload['tokens_saved']}"
    )
    assert payload["avg_savings_pct"] == 0, (
        "savings_pct was fabricated from saved/input; the external tool "
        f"never reported one but got {payload['avg_savings_pct']}"
    )
