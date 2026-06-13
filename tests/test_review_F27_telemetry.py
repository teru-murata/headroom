"""RED test for fork-review finding F27-telemetry (NN2, critical).

Claim: ``LedgerEvent.create`` accepts caller-supplied ``occurred_at`` and
``tenant_id`` verbatim, ``JsonlLedgerEmitter`` appends them to a local JSONL
with no signature / monotonic-clock binding / server authority, and
``to_otel_attributes`` re-exports them as ``bridge.*``. The provenance /
attribution surface is therefore fully mintable by the interested producer:
``occurred_at`` and ``tenant`` are forgeable.

This test asserts the DEFENDED behavior the finding says is missing: a forged
future ``occurred_at`` and a forged ``tenant_id`` must NOT survive verbatim
into the emitted event / re-exported OTel attributes. If the defect is real
the forged values are accepted verbatim and these assertions FAIL today.

Self-contained: uses tmp_path for the JSONL sink, an InMemoryLedgerEmitter for
the in-process surface, and resets the global emitter singleton around the run.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from headroom.telemetry.ledger import (
    InMemoryLedgerEmitter,
    JsonlLedgerEmitter,
    LedgerEvent,
    event_to_otel_attributes,
    reset_ledger_emitter,
)

FORGED_OCCURRED_AT = "2099-01-01T00:00:00+00:00"
FORGED_TENANT = "victim"
FORGED_SAVED_TOKENS = 10**9


@pytest.fixture(autouse=True)
def _clean_state() -> Generator[None, None, None]:
    reset_ledger_emitter()
    try:
        yield
    finally:
        reset_ledger_emitter()


def test_forged_occurred_at_is_not_accepted_verbatim(tmp_path: Path) -> None:
    """A producer-supplied future timestamp must be rejected or server-restamped.

    Today ``create`` does ``occurred_at = str(fields.pop("occurred_at", _utc_now()))``
    (ledger.py:127), so the year-2099 value is taken verbatim. A trustworthy
    provenance surface would re-stamp to a real server/monotonic clock value
    near now, so the emitted ``occurred_at`` should be in the past, not 2099.
    """
    before = datetime.now(UTC)

    emitter = InMemoryLedgerEmitter()
    event = LedgerEvent.create(
        "bridge.compression.completed",
        occurred_at=FORGED_OCCURRED_AT,
        tenant_id=FORGED_TENANT,
        saved_tokens=FORGED_SAVED_TOKENS,
    )
    emitter.emit(event)

    after = datetime.now(UTC)

    emitted = emitter.events[0].to_dict()
    stamped = datetime.fromisoformat(emitted["occurred_at"])

    # The defended behavior: occurred_at is bound to a real clock at emit time,
    # so it cannot be a forged far-future value.
    assert before <= stamped <= after, (
        "forged occurred_at survived verbatim into the ledger event: "
        f"{emitted['occurred_at']!r} (expected a server/monotonic stamp "
        f"between {before.isoformat()} and {after.isoformat()})"
    )


def test_forged_tenant_is_authority_bound_not_taken_verbatim() -> None:
    """A producer must not be able to mint another tenant's attribution.

    Today ``create`` takes ``tenant_id`` verbatim (ledger.py:128-130), so the
    interested producer can stamp 'victim'. A trustworthy surface would bind
    tenant to local/authenticated authority, never to an arbitrary caller value.
    """
    event = LedgerEvent.create(
        "bridge.compression.completed",
        tenant_id=FORGED_TENANT,
        saved_tokens=FORGED_SAVED_TOKENS,
    )

    assert event.tenant_id != FORGED_TENANT, (
        "caller-supplied tenant_id was accepted verbatim "
        f"({event.tenant_id!r}); attribution is mintable by the producer"
    )


def test_otel_export_does_not_re_export_forged_provenance() -> None:
    """The forged values must not be re-exported as bridge.* attributes."""
    event = LedgerEvent.create(
        "bridge.compression.completed",
        occurred_at=FORGED_OCCURRED_AT,
        tenant_id=FORGED_TENANT,
        saved_tokens=FORGED_SAVED_TOKENS,
    )

    attrs = event_to_otel_attributes(event)

    assert attrs.get("bridge.tenant_id") != FORGED_TENANT, (
        "forged tenant_id re-exported verbatim as bridge.tenant_id"
    )


def test_jsonl_sink_carries_no_signature_or_authority_field(tmp_path: Path) -> None:
    """A forged event written to the local JSONL has no integrity binding.

    The finding's structural core: events land on disk with no signature /
    HMAC / server-authority field, so a forged occurred_at + tenant is
    indistinguishable from a genuine one. This asserts the presence of an
    integrity binding the finding says is absent.
    """
    path = tmp_path / "events.jsonl"
    emitter = JsonlLedgerEmitter(path)

    emitter.emit(
        LedgerEvent.create(
            "bridge.compression.completed",
            occurred_at=FORGED_OCCURRED_AT,
            tenant_id=FORGED_TENANT,
            saved_tokens=FORGED_SAVED_TOKENS,
        )
    )

    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])

    integrity_fields = {"signature", "hmac", "server_signature", "authority", "attestation"}
    present = integrity_fields.intersection(record.keys())
    assert present, (
        "ledger JSONL record has no integrity/authority binding "
        f"(none of {sorted(integrity_fields)} present); forged occurred_at="
        f"{record.get('occurred_at')!r} tenant={record.get('tenant_id')!r} "
        "is indistinguishable from a genuine event"
    )
