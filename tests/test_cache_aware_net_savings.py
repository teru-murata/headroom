from __future__ import annotations

from pathlib import Path

from headroom.benchmarks.net_savings import (
    NetSavingsInput,
    PricingConfig,
    classify_cache_zone,
    compute_net_savings_decision,
    emit_decision_ledger_event,
    run_net_savings_benchmark,
)
from headroom.telemetry.ledger import InMemoryLedgerEmitter


def test_protected_prefix_is_never_compressed() -> None:
    decision = compute_net_savings_decision(
        NetSavingsInput(
            original_tokens_estimated=1000,
            compressed_tokens_estimated=100,
            cache_zone="protected_prefix",
            task_accuracy_guard_passed=True,
        )
    )

    assert decision.decision == "bypass_protected_prefix"
    assert "protected prefix" in decision.reason
    assert decision.ledger_event_fields["event_type"] == "bridge.compression.bypassed"


def test_stable_prefix_skips_when_cache_miss_penalty_exceeds_gross_savings() -> None:
    decision = compute_net_savings_decision(
        NetSavingsInput(
            original_tokens_estimated=1000,
            compressed_tokens_estimated=500,
            cache_zone="stable_prefix",
            provider_cached_tokens=800,
            task_accuracy_guard_passed=True,
        )
    )

    assert decision.decision == "skip_preserve_cache"
    assert decision.gross_saved_tokens_estimated == 500
    assert decision.cache_miss_penalty_tokens_estimated == 800
    assert decision.net_saved_tokens_estimated == -300


def test_live_tool_output_compresses_when_net_savings_positive_and_guard_passes() -> None:
    decision = compute_net_savings_decision(
        NetSavingsInput(
            original_tokens_estimated=2000,
            compressed_tokens_estimated=500,
            cache_zone="live_tool_output",
            task_accuracy_guard_passed=True,
            source_type="test_log",
            compression_method="log_compressor",
            accuracy_guard="coding_agent_failure_evidence",
        )
    )

    assert decision.decision == "compress"
    assert decision.net_saved_tokens_estimated == 1500
    assert decision.ledger_event_fields["event_type"] == "bridge.compression.completed"
    assert decision.ledger_event_fields["compression_method"] == "log_compressor"


def test_evidence_guard_failure_bypasses_compression() -> None:
    decision = compute_net_savings_decision(
        NetSavingsInput(
            original_tokens_estimated=2000,
            compressed_tokens_estimated=300,
            cache_zone="live_tool_output",
            task_accuracy_guard_passed=False,
        )
    )

    assert decision.decision == "bypass_accuracy_guard"
    assert "accuracy guard" in decision.reason


def test_ccr_retrieve_cost_reduces_net_saved_tokens() -> None:
    decision = compute_net_savings_decision(
        NetSavingsInput(
            original_tokens_estimated=1000,
            compressed_tokens_estimated=200,
            cache_zone="live_tool_output",
            ccr_marker_present=True,
            ccr_retrieve_rate_estimate=0.5,
            task_accuracy_guard_passed=True,
        )
    )

    assert decision.gross_saved_tokens_estimated == 800
    assert decision.ccr_retrieve_cost_tokens_estimated == 500
    assert decision.net_saved_tokens_estimated == 300


def test_no_pricing_config_still_returns_token_based_decision() -> None:
    decision = compute_net_savings_decision(
        NetSavingsInput(
            original_tokens_estimated=800,
            compressed_tokens_estimated=300,
            cache_zone="volatile_tail",
            task_accuracy_guard_passed=True,
        )
    )

    assert decision.decision == "compress"
    assert decision.estimated_cost_before is None
    assert decision.estimated_cost_after is None
    assert decision.estimated_net_savings is None
    assert any("pricing was not supplied" in warning for warning in decision.warnings)


def test_pricing_config_returns_estimated_costs() -> None:
    decision = compute_net_savings_decision(
        NetSavingsInput(
            original_tokens_estimated=1000,
            compressed_tokens_estimated=400,
            cache_zone="stable_prefix",
            provider_cached_tokens=200,
            task_accuracy_guard_passed=True,
            pricing=PricingConfig(
                input_token_price_per_million=3.0,
                cached_token_price_per_million=0.3,
            ),
        )
    )

    assert decision.estimated_cost_before is not None
    assert decision.estimated_cost_after is not None
    assert decision.estimated_net_savings is not None
    assert decision.estimated_cost_before > 0


def test_unknown_weak_signal_is_conservative() -> None:
    decision = compute_net_savings_decision(
        NetSavingsInput(
            original_tokens_estimated=200,
            compressed_tokens_estimated=180,
            cache_zone="unknown",
            task_accuracy_guard_passed=True,
        )
    )

    assert decision.decision == "insufficient_signal"
    assert decision.confidence == "low"


def test_cache_zone_classifier_identifies_supported_cases() -> None:
    assert (
        classify_cache_zone("System: do not rewrite", metadata={"role": "system"})
        == "protected_prefix"
    )
    assert (
        classify_cache_zone("same prefix", metadata={"stable_prefix_hash": "abc123"})
        == "stable_prefix"
    )
    assert (
        classify_cache_zone("$ python -m pytest tests -q\nFAILED tests/test_a.py::test_b")
        == "live_tool_output"
    )
    assert classify_cache_zone("pytest output", source_type="test_logs") == "live_tool_output"
    assert classify_cache_zone("diff output", source_type="git_diffs") == "live_tool_output"
    assert classify_cache_zone("new turn", metadata={"position": "tail"}) == "volatile_tail"
    assert classify_cache_zone("plain prose without hints") == "unknown"


def test_decision_output_includes_reason_confidence_and_warnings() -> None:
    decision = compute_net_savings_decision(
        NetSavingsInput(
            original_tokens_estimated=100,
            compressed_tokens_estimated=90,
            cache_zone="unknown",
        )
    )

    assert decision.reason
    assert decision.confidence in {"low", "medium", "high"}
    assert decision.warnings
    assert "reason" in decision.ledger_event_fields["attributes"]


def test_benchmark_runner_produces_report_with_required_groups(tmp_path: Path) -> None:
    output_path = tmp_path / "net-savings-report.json"

    report = run_net_savings_benchmark(output_path=output_path)

    assert output_path.exists()
    assert report["benchmark_version"] == "cache-aware-net-savings-v0"
    assert report["fixture_count"] >= 10
    assert report["by_source_type"]
    assert report["by_cache_zone"]
    assert report["decisions"]["compress"] >= 1
    assert "stable_prefix" in report["by_cache_zone"]
    assert "live_tool_output" in report["by_cache_zone"]
    assert "test_logs" in report["by_source_type"]
    assert "git_diffs" in report["by_source_type"]
    assert "tool_outputs" in report["by_source_type"]
    assert all("net_saved_tokens_estimated" in row for row in report["rows"])


def test_skip_preserve_cache_can_emit_ledger_compatible_event() -> None:
    emitter = InMemoryLedgerEmitter()
    decision = compute_net_savings_decision(
        NetSavingsInput(
            original_tokens_estimated=1000,
            compressed_tokens_estimated=600,
            cache_zone="stable_prefix",
            provider_cached_tokens=900,
            task_accuracy_guard_passed=True,
            source_type="generic_tool_output",
            accuracy_guard="cache_preservation",
        )
    )

    event = emit_decision_ledger_event(decision, emitter=emitter, source_id="fixture:stable")
    data = event.to_dict()

    assert len(emitter.events) == 1
    assert data["event_type"] == "bridge.compression.bypassed"
    assert data["source_id"] == "fixture:stable"
    assert data["cache_zone"] == "stable_prefix"
    assert data["compression_method"] == "skip_preserve_cache"
    assert data["compressed_tokens"] == data["original_tokens"]
    assert data["saved_tokens"] == 0
