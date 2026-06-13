"""RED test for finding F32-telemetry.

Claim (NN1): import_stats() folds self-reported summary counters
(total_compressions/total_retrievals/total_tokens_saved) from arbitrary
imported data straight into the collector's global counters, and get_stats()
then reports those blended, unverified numbers as authoritative totals with no
provenance separation.

This test imports an absurd, unverified external aggregate and asserts that the
collector does NOT absorb it verbatim into its authoritative totals.
If the bug is real, get_stats()['total_tokens_saved'] will equal the injected
value and the test FAILS.
"""

from headroom.telemetry.collector import TelemetryCollector, TelemetryConfig


def test_import_stats_does_not_absorb_unverified_external_totals():
    collector = TelemetryCollector(TelemetryConfig(enabled=True, storage_path=None))

    # Baseline: nothing recorded locally.
    assert collector.get_stats()["total_tokens_saved"] == 0

    bogus = 10**12
    collector.import_stats({"summary": {"total_tokens_saved": bogus}})

    reported = collector.get_stats()["total_tokens_saved"]

    # The authoritative total should not be the verbatim, unverified external
    # number. Either imported aggregates are validated/rejected (stays 0) or
    # segregated into a separate provenance bucket (not surfaced as the
    # authoritative total_tokens_saved).
    assert reported != bogus, (
        "get_stats() surfaced an unverified imported aggregate "
        f"({reported}) as the authoritative total_tokens_saved"
    )
