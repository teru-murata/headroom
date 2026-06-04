"""Local cache-aware net-savings benchmark runner."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from headroom.presets import CodingAgentPreset, CodingAgentPresetConfig
from headroom.telemetry.ledger import estimate_tokens

from .model import (
    NetSavingsInput,
    PricingConfig,
    classify_cache_zone,
    compute_net_savings_decision,
)

BENCHMARK_VERSION = "cache-aware-net-savings-v0"


def run_net_savings_benchmark(
    manifest_path: str | Path | None = None,
    *,
    output_path: str | Path | None = None,
    pricing: PricingConfig | dict[str, float | None] | None = None,
) -> dict[str, Any]:
    """Run the local net-savings benchmark and optionally write a JSON report."""

    manifest_file = Path(manifest_path) if manifest_path is not None else _default_manifest_path()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest_pricing = pricing or manifest.get("pricing_config")
    fixture_base = manifest_file.parent
    rows = []
    preset = CodingAgentPreset(
        CodingAgentPresetConfig(
            min_lines_for_ccr=8,
            min_chars_for_ccr=240,
            max_log_lines=24,
            max_file_tree_lines=70,
            max_generic_lines=30,
            generic_leading_lines=4,
        )
    )

    for fixture in manifest.get("fixtures", []):
        row = _run_fixture(
            fixture,
            fixture_base=fixture_base,
            preset=preset,
            manifest_pricing=manifest_pricing,
        )
        rows.append(row)

    report = _build_report(rows)
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _run_fixture(
    fixture: dict[str, Any],
    *,
    fixture_base: Path,
    preset: CodingAgentPreset,
    manifest_pricing: PricingConfig | dict[str, float | None] | None,
) -> dict[str, Any]:
    text = _load_fixture_text(fixture, fixture_base)
    source_type = fixture.get("source_type")
    metadata = dict(fixture.get("metadata") or {})
    cache_zone = fixture.get("cache_zone") or classify_cache_zone(
        text,
        source_type=source_type,
        metadata=metadata,
    )
    metadata["cache_zone"] = cache_zone
    result = preset.route_and_compress(source_type, text, metadata)
    original_tokens = int(fixture.get("original_tokens_estimated") or estimate_tokens(text))
    compressed_tokens = int(
        fixture.get("compressed_tokens_estimated") or estimate_tokens(result.compressed)
    )
    fixture_pricing = None if fixture.get("disable_pricing") else fixture.get("pricing_config")
    if fixture_pricing is None and not fixture.get("disable_pricing"):
        fixture_pricing = manifest_pricing
    decision = compute_net_savings_decision(
        NetSavingsInput(
            original_tokens_estimated=original_tokens,
            compressed_tokens_estimated=compressed_tokens,
            cache_zone=cache_zone,
            provider_cached_tokens=int(fixture.get("provider_cached_tokens") or 0),
            provider_cache_reads=int(fixture.get("provider_cache_reads") or 0),
            cache_miss_penalty_tokens_estimated=fixture.get("cache_miss_penalty_tokens_estimated"),
            stable_prefix_tokens_estimated=fixture.get("stable_prefix_tokens_estimated"),
            cache_miss_penalty_multiplier=float(
                fixture.get("cache_miss_penalty_multiplier") or 1.0
            ),
            pricing=fixture_pricing,
            ccr_marker_present=bool(fixture.get("ccr_marker_present", result.ccr_hash is not None)),
            ccr_retrieve_rate_estimate=float(fixture.get("ccr_retrieve_rate_estimate") or 0.1),
            ccr_retrieve_cost_tokens_estimated=fixture.get("ccr_retrieve_cost_tokens_estimated"),
            retrieved_count=fixture.get("retrieved_count"),
            task_accuracy_guard_passed=fixture.get("task_accuracy_guard_passed"),
            source_type=result.source_type,
            compression_method=result.compression_method,
            accuracy_guard=result.accuracy_guard,
        )
    )
    return {
        "fixture_id": fixture["id"],
        "source_type": result.source_type,
        "cache_zone": decision.cache_zone,
        "decision": decision.decision,
        "reason": decision.reason,
        "original_tokens_estimated": original_tokens,
        "compressed_tokens_estimated": compressed_tokens,
        "saved_tokens_estimated": decision.gross_saved_tokens_estimated,
        "cache_miss_penalty_tokens_estimated": decision.cache_miss_penalty_tokens_estimated,
        "ccr_retrieve_cost_tokens_estimated": decision.ccr_retrieve_cost_tokens_estimated,
        "net_saved_tokens_estimated": decision.net_saved_tokens_estimated,
        "estimated_cost_before": decision.estimated_cost_before,
        "estimated_cost_after": decision.estimated_cost_after,
        "estimated_net_savings": decision.estimated_net_savings,
        "compression_method": result.compression_method,
        "accuracy_guard": result.accuracy_guard,
        "warnings": decision.warnings,
    }


def _build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = Counter(row["decision"] for row in rows)
    by_source_type = _group_rows(rows, "source_type")
    by_cache_zone = _group_rows(rows, "cache_zone")
    totals = {
        "gross_saved_tokens_estimated": sum(row["saved_tokens_estimated"] for row in rows),
        "cache_miss_penalty_tokens_estimated": sum(
            row["cache_miss_penalty_tokens_estimated"] for row in rows
        ),
        "ccr_retrieve_cost_tokens_estimated": sum(
            row["ccr_retrieve_cost_tokens_estimated"] for row in rows
        ),
        "net_saved_tokens_estimated": sum(row["net_saved_tokens_estimated"] for row in rows),
        "compress_count": decisions.get("compress", 0),
        "bypass_or_skip_count": len(rows) - decisions.get("compress", 0),
    }
    cost_values = [
        row["estimated_net_savings"] for row in rows if row["estimated_net_savings"] is not None
    ]
    if cost_values:
        totals["estimated_net_savings"] = sum(cost_values)
    else:
        totals["estimated_net_savings"] = None
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "fixture_count": len(rows),
        "totals": totals,
        "by_source_type": by_source_type,
        "by_cache_zone": by_cache_zone,
        "decisions": dict(decisions),
        "rows": rows,
    }


def _group_rows(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "count": 0,
            "gross_saved_tokens_estimated": 0,
            "net_saved_tokens_estimated": 0,
        }
    )
    for row in rows:
        bucket = grouped[str(row[key])]
        bucket["count"] += 1
        bucket["gross_saved_tokens_estimated"] += int(row["saved_tokens_estimated"])
        bucket["net_saved_tokens_estimated"] += int(row["net_saved_tokens_estimated"])
    return dict(grouped)


def _load_fixture_text(fixture: dict[str, Any], fixture_base: Path) -> str:
    if "content" in fixture:
        return str(fixture["content"])
    path = fixture_base / str(fixture["path"])
    return path.read_text(encoding="utf-8")


def _default_manifest_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "benchmarks"
        / "net_savings"
        / "fixtures"
        / "manifest.json"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(_default_manifest_path()),
        help="Path to net-savings fixture manifest.",
    )
    parser.add_argument("--output", help="Optional JSON report output path.")
    parser.add_argument("--input-price", type=float, help="Input token price per million.")
    parser.add_argument("--cached-price", type=float, help="Cached token price per million.")
    args = parser.parse_args(argv)

    pricing = None
    if args.input_price is not None:
        pricing = PricingConfig(
            input_token_price_per_million=args.input_price,
            cached_token_price_per_million=args.cached_price,
        )
    report = run_net_savings_benchmark(args.manifest, output_path=args.output, pricing=pricing)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["BENCHMARK_VERSION", "main", "run_net_savings_benchmark"]
