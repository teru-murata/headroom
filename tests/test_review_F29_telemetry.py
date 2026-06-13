"""RED test for finding F29-telemetry.

Claim (NN2): UsageReporter._load_cache_or_default trusts an unsigned,
licensee-writable local JSON cache verbatim. validate_license swallows all
errors and falls back to that cache, so an OFFLINE/unlicensed user who writes
{"status": "active", "validated_at": <now>} into LICENSE_CACHE_PATH obtains
is_active == True and should_compress == True for the full 7-day grace window,
for a license key the cloud never validated.

This test simulates that exploit. The SECURE expectation is that a cache the
cloud never produced/signed must NOT grant entitlement. If the cache is trusted
verbatim (no signature/HMAC), this test FAILS today (values are True).
"""

import json
from datetime import datetime, timezone

import pytest

from headroom.telemetry.reporter import UsageReporter


@pytest.mark.asyncio
async def test_offline_attacker_written_cache_does_not_grant_entitlement(tmp_path):
    cache_path = tmp_path / "license_cache.json"

    # Attacker (the interested party) forges entitlement evidence locally.
    # No real cloud validation ever happened for this key.
    forged = {
        "status": "active",
        "org_id": "attacker",
        "org_name": "Attacker Inc",
        "plan": "enterprise",
        "quota_tokens": None,
        "trial_expires_at": None,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    cache_path.write_text(json.dumps(forged), encoding="utf-8")

    reporter = UsageReporter(
        license_key="hlk_never_validated_by_cloud",
        cloud_url="https://app.headroomlabs.ai",
        cache_path=cache_path,
    )

    # Force the reporter offline: any attempt to reach the cloud raises,
    # mirroring an unlicensed user with no network path to validation.
    async def _offline_client():
        raise ConnectionError("offline: cloud unreachable")

    reporter._get_client = _offline_client  # type: ignore[method-assign]

    info = await reporter.validate_license()

    # Secure expectation: an unsigned, locally-forged cache the cloud never
    # produced must not be trusted as proof of an active license.
    assert info.status not in ("active", "trial"), (
        "Forged local cache was trusted verbatim as 'active' (NN2): "
        f"got status={info.status!r}"
    )
    assert reporter.is_active is False, (
        "is_active granted entitlement from a forged, unsigned local cache"
    )
    assert reporter.should_compress is False, (
        "should_compress granted from a forged, unsigned local cache"
    )
