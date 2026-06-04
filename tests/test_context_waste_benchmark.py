from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from headroom.benchmarks.context_waste.runner import (
    BENCHMARK_VERSION,
    load_manifest,
    run_context_waste_benchmark,
)
from headroom.benchmarks.context_waste.taxonomy import REQUIRED_SOURCE_TYPES
from headroom.cache.compression_store import reset_compression_store
from headroom.telemetry.ledger import estimate_tokens, reset_ledger_emitter

FIXTURES = Path("benchmarks/context_waste/fixtures")


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_compression_store()
    reset_ledger_emitter()


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return run_context_waste_benchmark(FIXTURES)


def _rows_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["fixture_id"]: row for row in report["rows"]}


def test_manifest_loads_and_validates_all_fixture_paths() -> None:
    fixtures = load_manifest(FIXTURES)

    assert fixtures
    assert len({fixture.id for fixture in fixtures}) == len(fixtures)
    for fixture in fixtures:
        assert (FIXTURES / fixture.path).is_file()
        assert fixture.description
        assert fixture.expected_behavior


def test_every_required_source_type_has_a_fixture() -> None:
    source_types = {fixture.source_type for fixture in load_manifest(FIXTURES)}

    assert set(REQUIRED_SOURCE_TYPES) <= source_types


def test_runner_produces_report_with_required_top_level_fields(
    report: dict[str, Any],
) -> None:
    assert report["benchmark_version"] == BENCHMARK_VERSION
    assert report["source_taxonomy_version"] == "source-taxonomy-v0"
    assert report["generated_at"]
    assert report["fixture_count"] == len(report["rows"])
    assert isinstance(report["totals"], dict)
    assert isinstance(report["by_source_type"], dict)
    assert isinstance(report["rows"], list)
    assert report["ledger_event_count"] >= report["fixture_count"]
    assert "bridge.compression.completed" in report["ledger_event_types"]


def test_every_row_has_source_type_and_token_estimates(report: dict[str, Any]) -> None:
    for row in report["rows"]:
        assert row["fixture_id"]
        assert row["source_type"]
        assert row["input_path"]
        assert row["original_tokens_estimated"] > 0
        assert row["compressed_tokens_estimated"] > 0
        assert row["saved_tokens_estimated"] >= 0
        assert 0 < row["compression_ratio"]
        assert row["compression_method"]
        assert "ccr_marker_present" in row
        assert "accuracy_guard" in row
        assert isinstance(row["warnings"], list)


def test_totals_equal_sum_of_rows(report: dict[str, Any]) -> None:
    rows = report["rows"]

    assert report["totals"]["original_tokens_estimated"] == sum(
        row["original_tokens_estimated"] for row in rows
    )
    assert report["totals"]["compressed_tokens_estimated"] == sum(
        row["compressed_tokens_estimated"] for row in rows
    )
    assert report["totals"]["saved_tokens_estimated"] == sum(
        row["saved_tokens_estimated"] for row in rows
    )
    for source_type, aggregate in report["by_source_type"].items():
        matching_rows = [row for row in rows if row["source_type"] == source_type]
        assert aggregate["count"] == len(matching_rows)
        assert aggregate["original_tokens_estimated"] == sum(
            row["original_tokens_estimated"] for row in matching_rows
        )


def test_log_fixtures_route_through_h004_log_behavior(report: dict[str, Any]) -> None:
    rows = _rows_by_id(report)

    for fixture_id in ("build-log-typescript", "test-log-pytest"):
        row = rows[fixture_id]
        assert row["compression_method"] == "log_compressor"
        assert row["accuracy_guard"] == "coding_agent_failure_evidence"
        assert row["saved_tokens_estimated"] > 0
        assert row["warnings"] == []


def test_git_diff_and_file_tree_route_through_h005_behavior(report: dict[str, Any]) -> None:
    rows = _rows_by_id(report)

    assert rows["git-diff-auth-patch"]["compression_method"] == "diff_compressor"
    assert rows["git-diff-auth-patch"]["accuracy_guard"] == "edit_target_diff_evidence"
    assert rows["file-tree-repository"]["compression_method"] == "file_tree_compressor"
    assert rows["file-tree-repository"]["accuracy_guard"] == "edit_target_tree_evidence"
    assert rows["git-diff-auth-patch"]["warnings"] == []
    assert rows["file-tree-repository"]["warnings"] == []


def test_h006_preset_routes_search_package_mcp_and_tool_outputs(
    report: dict[str, Any],
) -> None:
    rows = _rows_by_id(report)

    assert rows["search-results-rg"]["compression_method"] == "search_compressor"
    assert (
        rows["package-metadata-package-json"]["compression_method"] == "package_metadata_compactor"
    )
    assert rows["mcp-tool-response-search"]["compression_method"] == ("mcp_tool_response_compactor")
    assert rows["tool-outputs-noisy-command"]["compression_method"] == (
        "generic_tool_output_compactor"
    )
    assert rows["tool-definitions-openai-anthropic"]["compression_method"] == (
        "tool_definition_schema_compactor"
    )


def test_source_code_file_read_is_not_blindly_compressed(report: dict[str, Any]) -> None:
    row = _rows_by_id(report)["file-read-source-code"]

    assert row["source_type"] == "file_reads"
    assert row["compression_method"] == "source_code_passthrough"
    assert row["accuracy_guard"] == "source_code_not_blindly_compressed"
    assert row["saved_tokens_estimated"] == 0
    assert row["ccr_marker_present"] is False


def test_ccr_marker_retrievability_is_checked_for_rows_with_markers(
    report: dict[str, Any],
) -> None:
    rows_with_markers = [row for row in report["rows"] if row["ccr_marker_present"]]

    assert rows_with_markers
    assert all(row["ccr_marker_id"] for row in rows_with_markers)
    assert all(row["ccr_retrievable"] is True for row in rows_with_markers)
    assert report["totals"]["ccr_marker_rows"] == len(rows_with_markers)
    assert report["totals"]["ccr_retrievable_rows"] == len(rows_with_markers)


def test_ledger_event_source_type_matches_benchmark_source_type(
    report: dict[str, Any],
) -> None:
    consistency = report["source_type_consistency"]

    assert consistency["checked_event_types"] == [
        "bridge.compression.completed",
        "bridge.compression.bypassed",
    ]
    assert consistency["checked_event_count"] == report["fixture_count"]
    assert consistency["matched_event_count"] == report["fixture_count"]
    assert consistency["mismatched_fixture_ids"] == []
    for row in report["rows"]:
        assert row["source_type_consistent"] is True
        assert row["ledger_source_types"] == [row["source_type"]]


def test_report_serialization_to_json_and_jsonl_works(tmp_path: Path) -> None:
    report_path = tmp_path / "context-waste-report.json"
    jsonl_path = tmp_path / "context-waste-rows.jsonl"

    generated = run_context_waste_benchmark(FIXTURES, out=report_path, jsonl_out=jsonl_path)

    loaded = json.loads(report_path.read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert loaded["benchmark_version"] == BENCHMARK_VERSION
    assert loaded["fixture_count"] == generated["fixture_count"]
    assert len(rows) == generated["fixture_count"]


def test_token_estimates_are_deterministic(report: dict[str, Any]) -> None:
    repeated = run_context_waste_benchmark(FIXTURES)

    first = {
        row["fixture_id"]: (
            row["original_tokens_estimated"],
            row["compressed_tokens_estimated"],
            row["saved_tokens_estimated"],
        )
        for row in report["rows"]
    }
    second = {
        row["fixture_id"]: (
            row["original_tokens_estimated"],
            row["compressed_tokens_estimated"],
            row["saved_tokens_estimated"],
        )
        for row in repeated["rows"]
    }
    assert first == second
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_runner_makes_no_remote_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("context waste benchmark attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail_connect)
    monkeypatch.setattr(socket.socket, "connect", fail_connect)

    generated = run_context_waste_benchmark(FIXTURES)

    assert generated["fixture_count"] >= len(REQUIRED_SOURCE_TYPES)
