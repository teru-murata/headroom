"""RED test for finding F28-telemetry (NN1: self-reported numbers are not evidence).

Claim under test (headroom/telemetry/reporter.py, _report_usage, ~l.256-320):
    The /v1/license/usage payload's requests/tokens_before/tokens_after/tokens_saved
    are built purely from proxy-local counters (cost_tracker._tokens_saved_by_model
    etc.) and POSTed to the billing/quota cloud verbatim, with no independent recount
    and no signed/verifiable evidence. A malicious/buggy client can mint arbitrary
    usage numbers that the cloud consumes for plan/quota decisions.

This RED test stubs a proxy whose cost_tracker reports an absurd 1e9 tokens_saved,
captures the outbound POST body, and asserts that the client does NOT forward the
self-reported number verbatim without any server-recountable proof.

It FAILS TODAY (the payload carries the raw client-minted number, no signature/proof).
It would PASS once the payload either omits the raw verbatim figure or carries a
verifiable signature / proof field the server can independently validate.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from headroom.telemetry.reporter import UsageReporter


class _FakeCostTracker:
    """Minimal stand-in for proxy.cost_tracker with attacker-controlled counters."""

    def __init__(self, saved_by_model, sent_by_model, requests_by_model):
        self._tokens_saved_by_model = dict(saved_by_model)
        self._tokens_sent_by_model = dict(sent_by_model)
        self._requests_by_model = dict(requests_by_model)


class _CapturingClient:
    """Async httpx-client stub that records the POST payload and returns 200."""

    def __init__(self):
        self.captured = []

    async def post(self, url, json=None, timeout=None):  # noqa: A002 - mirror httpx API
        self.captured.append({"url": url, "json": json})

        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                return {"status": "active"}

        return _Resp()


# Heuristic set of field names that would carry server-recountable proof / signature.
_EVIDENCE_FIELD_NAMES = {
    "signature",
    "sig",
    "proof",
    "attestation",
    "evidence",
    "hmac",
    "mac",
    "nonce",
    "receipt",
    "signed",
    "token_receipt",
}


def test_usage_payload_is_not_verbatim_client_minted():
    inflated_saved = 10**9  # one billion "saved" tokens, fabricated client-side

    cost_tracker = _FakeCostTracker(
        saved_by_model={"gpt": inflated_saved},
        sent_by_model={"gpt": 5},
        requests_by_model={"gpt": 1},
    )
    proxy = SimpleNamespace(cost_tracker=cost_tracker)

    reporter = UsageReporter(license_key="hlk_test", report_interval=300)
    reporter._proxy = proxy

    capturing = _CapturingClient()

    async def _fake_get_client():
        return capturing

    reporter._get_client = _fake_get_client  # type: ignore[assignment]

    asyncio.run(reporter._report_usage())

    assert capturing.captured, "expected a usage POST to be emitted"
    payload = capturing.captured[0]["json"]

    has_evidence = any(k in _EVIDENCE_FIELD_NAMES for k in payload.keys())
    forwarded_verbatim = payload.get("tokens_saved") == inflated_saved

    # NN1: the cloud must not consume a raw, client-minted number with no proof.
    assert not (forwarded_verbatim and not has_evidence), (
        "tokens_saved was forwarded verbatim from proxy-local counters "
        f"(={payload.get('tokens_saved')}) with no signed/recountable evidence "
        f"field present in payload keys={sorted(payload.keys())}. "
        "Self-reported numbers are not evidence (NN1)."
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
