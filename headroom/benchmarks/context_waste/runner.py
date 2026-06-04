"""Local coding-agent context waste benchmark runner."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from headroom.cache.compression_store import get_compression_store, reset_compression_store
from headroom.ccr.markers import parse_ccr_markers
from headroom.presets import CodingAgentPreset, CodingAgentPresetConfig
from headroom.telemetry.ledger import (
    InMemoryLedgerEmitter,
    estimate_tokens,
    reset_ledger_emitter,
    set_ledger_emitter,
)

from .taxonomy import (
    SOURCE_TAXONOMY_VERSION,
    normalize_source_type,
    validate_required_source_types,
)

BENCHMARK_VERSION = "context-waste-benchmark-v0"
DEFAULT_FIXTURES = Path("benchmarks/context_waste/fixtures")


@dataclass(frozen=True)
class BenchmarkFixture:
    """One manifest entry for the context waste benchmark."""

    id: str
    source_type: str
    path: str
    description: str
    expected_behavior: str
    must_preserve: tuple[str, ...] = ()
    may_collapse: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkFixture:
        required = ("id", "source_type", "path", "description", "expected_behavior")
        missing = [key for key in required if not data.get(key)]
        if missing:
            msg = f"fixture manifest entry missing required keys: {', '.join(missing)}"
            raise ValueError(msg)
        return cls(
            id=str(data["id"]),
            source_type=normalize_source_type(str(data["source_type"])),
            path=str(data["path"]),
            description=str(data["description"]),
            expected_behavior=str(data["expected_behavior"]),
            must_preserve=tuple(str(item) for item in data.get("must_preserve", ())),
            may_collapse=tuple(str(item) for item in data.get("may_collapse", ())),
            metadata=dict(data.get("metadata") or {}),
        )


def _manifest_path(fixtures: str | Path | None = None) -> Path:
    path = Path(fixtures) if fixtures is not None else DEFAULT_FIXTURES
    if path.is_dir():
        return path / "manifest.json"
    return path


def load_manifest(fixtures: str | Path | None = None) -> list[BenchmarkFixture]:
    """Load and validate a context-waste fixture manifest."""
    manifest_path = _manifest_path(fixtures)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_items = raw.get("fixtures") if isinstance(raw, dict) else raw
    if not isinstance(raw_items, list):
        raise ValueError("manifest must contain a fixtures list")

    fixtures_list = [BenchmarkFixture.from_dict(item) for item in raw_items]
    ids = [item.id for item in fixtures_list]
    duplicates = sorted({fixture_id for fixture_id in ids if ids.count(fixture_id) > 1})
    if duplicates:
        msg = "manifest contains duplicate fixture ids: " + ", ".join(duplicates)
        raise ValueError(msg)
    validate_required_source_types({item.source_type for item in fixtures_list})

    root = manifest_path.parent
    missing_paths = [item.path for item in fixtures_list if not (root / item.path).is_file()]
    if missing_paths:
        msg = "manifest references missing fixture paths: " + ", ".join(missing_paths)
        raise FileNotFoundError(msg)
    return fixtures_list


def run_context_waste_benchmark(
    fixtures: str | Path | None = None,
    *,
    out: str | Path | None = None,
    jsonl_out: str | Path | None = None,
) -> dict[str, Any]:
    """Run the local context-waste benchmark and optionally write reports."""
    manifest_path = _manifest_path(fixtures)
    fixtures_root = manifest_path.parent
    fixture_items = load_manifest(manifest_path)

    reset_compression_store()
    reset_ledger_emitter()
    emitter = InMemoryLedgerEmitter()
    set_ledger_emitter(emitter)
    preset = CodingAgentPreset(_benchmark_preset_config(), ledger_emitter=emitter)

    try:
        rows = [_run_fixture(fixtures_root, fixture, preset, emitter) for fixture in fixture_items]
    finally:
        reset_ledger_emitter()

    report = _build_report(rows, emitter)
    if out is not None:
        _write_json(Path(out), report)
    if jsonl_out is not None:
        _write_jsonl(Path(jsonl_out), rows)
    return report


def _benchmark_preset_config() -> CodingAgentPresetConfig:
    return CodingAgentPresetConfig(
        enable_ccr=True,
        min_lines_for_ccr=6,
        min_chars_for_ccr=200,
        max_log_lines=28,
        max_search_matches_per_file=2,
        max_search_matches=10,
        max_file_tree_lines=60,
        max_generic_lines=32,
        generic_leading_lines=5,
        max_mcp_results=3,
        max_dependency_names=8,
    )


def _run_fixture(
    fixtures_root: Path,
    fixture: BenchmarkFixture,
    preset: CodingAgentPreset,
    emitter: InMemoryLedgerEmitter,
) -> dict[str, Any]:
    input_path = fixtures_root / fixture.path
    original = input_path.read_text(encoding="utf-8")
    before_event_count = len(emitter.events)
    metadata = {
        "source_id": fixture.id,
        "source_path": fixture.path,
        "source_type": fixture.source_type,
        **fixture.metadata,
    }

    result = preset.route_and_compress(fixture.source_type, original, metadata)
    markers = parse_ccr_markers(result.compressed)
    ccr_marker_id = markers[-1].hash if markers else None
    ccr_retrievable = _check_ccr_retrievable(markers[-1].raw, original) if markers else None
    row_events = [event.to_dict() for event in emitter.events[before_event_count:]]
    compression_events = [
        event
        for event in row_events
        if event["event_type"] in {"bridge.compression.completed", "bridge.compression.bypassed"}
    ]

    original_tokens = estimate_tokens(original)
    compressed_tokens = estimate_tokens(result.compressed)
    saved_tokens = max(0, original_tokens - compressed_tokens)
    warnings = _row_warnings(fixture, result.compressed, ccr_marker_id, ccr_retrievable)
    ledger_source_types = sorted(
        {
            str(event.get("source_type"))
            for event in compression_events
            if event.get("source_type") is not None
        }
    )
    source_type_consistent = all(
        event.get("source_type") == fixture.source_type for event in compression_events
    )

    return {
        "fixture_id": fixture.id,
        "source_type": fixture.source_type,
        "input_path": fixture.path,
        "description": fixture.description,
        "expected_behavior": fixture.expected_behavior,
        "original_tokens_estimated": original_tokens,
        "compressed_tokens_estimated": compressed_tokens,
        "saved_tokens_estimated": saved_tokens,
        "compression_ratio": _ratio(compressed_tokens, original_tokens),
        "compression_method": result.compression_method,
        "ccr_marker_present": ccr_marker_id is not None,
        "ccr_marker_id": ccr_marker_id,
        "ccr_retrievable": ccr_retrievable,
        "accuracy_guard": result.accuracy_guard,
        "event_count": len(row_events),
        "event_types": sorted({str(event["event_type"]) for event in row_events}),
        "ledger_source_types": ledger_source_types,
        "source_type_consistent": source_type_consistent,
        "warnings": warnings,
    }


def _check_ccr_retrievable(marker: str, original: str) -> bool:
    entry = get_compression_store().retrieve(marker, query="context_waste_benchmark")
    return entry is not None and entry.original_content == original


def _row_warnings(
    fixture: BenchmarkFixture,
    compressed: str,
    ccr_marker_id: str | None,
    ccr_retrievable: bool | None,
) -> list[str]:
    warnings: list[str] = []
    missing = [fragment for fragment in fixture.must_preserve if fragment not in compressed]
    if missing:
        warnings.append("missing must_preserve fragments: " + ", ".join(missing[:4]))
    if ccr_marker_id and ccr_retrievable is not True:
        warnings.append("CCR marker was present but not locally retrievable")
    return warnings


def _build_report(rows: list[dict[str, Any]], emitter: InMemoryLedgerEmitter) -> dict[str, Any]:
    totals = _aggregate(rows)
    by_source_type: dict[str, dict[str, Any]] = {}
    for row in rows:
        aggregate = by_source_type.setdefault(row["source_type"], _empty_aggregate())
        _add_row(aggregate, row)
    for aggregate in by_source_type.values():
        _finish_aggregate(aggregate)

    compression_events = [
        event.to_dict()
        for event in emitter.events
        if event.event_type in {"bridge.compression.completed", "bridge.compression.bypassed"}
    ]
    mismatched_rows = [
        row["fixture_id"]
        for row in rows
        if row["event_count"] > 0 and not row["source_type_consistent"]
    ]

    return {
        "benchmark_version": BENCHMARK_VERSION,
        "source_taxonomy_version": SOURCE_TAXONOMY_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "fixture_count": len(rows),
        "totals": totals,
        "by_source_type": by_source_type,
        "ledger_event_count": len(emitter.events),
        "ledger_event_types": sorted({event.event_type for event in emitter.events}),
        "source_type_consistency": {
            "checked_event_types": [
                "bridge.compression.completed",
                "bridge.compression.bypassed",
            ],
            "checked_event_count": len(compression_events),
            "matched_event_count": len(compression_events) - len(mismatched_rows),
            "mismatched_fixture_ids": mismatched_rows,
        },
        "rows": rows,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate = _empty_aggregate()
    for row in rows:
        _add_row(aggregate, row)
    _finish_aggregate(aggregate)
    return aggregate


def _empty_aggregate() -> dict[str, Any]:
    return {
        "count": 0,
        "original_tokens_estimated": 0,
        "compressed_tokens_estimated": 0,
        "saved_tokens_estimated": 0,
        "compression_ratio": 1.0,
        "ccr_marker_rows": 0,
        "ccr_retrievable_rows": 0,
    }


def _add_row(aggregate: dict[str, Any], row: dict[str, Any]) -> None:
    aggregate["count"] += 1
    aggregate["original_tokens_estimated"] += int(row["original_tokens_estimated"])
    aggregate["compressed_tokens_estimated"] += int(row["compressed_tokens_estimated"])
    aggregate["saved_tokens_estimated"] += int(row["saved_tokens_estimated"])
    if row["ccr_marker_present"]:
        aggregate["ccr_marker_rows"] += 1
    if row["ccr_retrievable"] is True:
        aggregate["ccr_retrievable_rows"] += 1


def _finish_aggregate(aggregate: dict[str, Any]) -> None:
    aggregate["compression_ratio"] = _ratio(
        int(aggregate["compressed_tokens_estimated"]),
        int(aggregate["original_tokens_estimated"]),
    )


def _ratio(compressed_tokens: int, original_tokens: int) -> float:
    if original_tokens <= 0:
        return 1.0
    return round(compressed_tokens / original_tokens, 4)


def _write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        default=str(DEFAULT_FIXTURES),
        help="Fixture directory or manifest path.",
    )
    parser.add_argument("--out", "--output", dest="out", help="Write JSON report to this path.")
    parser.add_argument("--jsonl-out", help="Write per-row JSONL report to this path.")
    args = parser.parse_args(argv)

    report = run_context_waste_benchmark(args.fixtures, out=args.out, jsonl_out=args.jsonl_out)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
