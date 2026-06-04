from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from headroom.cache.compression_store import get_compression_store, reset_compression_store
from headroom.ccr.markers import normalize_ccr_hash, parse_ccr_markers
from headroom.ccr.tool_injection import CCRToolInjector
from headroom.presets import CodingAgentPreset, CodingAgentPresetConfig

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "coding_agent_presets"
LOG_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "log_crusher"
DIFF_TREE_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "diff_file_tree_crusher"


@pytest.fixture(autouse=True)
def _clean_ccr_store() -> Generator[None, None, None]:
    reset_compression_store()
    try:
        yield
    finally:
        reset_compression_store()


@pytest.fixture()
def preset() -> CodingAgentPreset:
    return CodingAgentPreset(
        CodingAgentPresetConfig(
            min_lines_for_ccr=8,
            min_chars_for_ccr=240,
            max_log_lines=24,
            max_search_matches_per_file=2,
            max_search_matches=8,
            max_file_tree_lines=70,
            max_generic_lines=28,
            generic_leading_lines=4,
            max_mcp_results=2,
            max_dependency_names=5,
        )
    )


def _load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _missing(content: str, fragments: tuple[str, ...]) -> list[str]:
    return [fragment for fragment in fragments if fragment not in content]


def test_test_log_routes_to_evidence_preserving_log_compressor(
    preset: CodingAgentPreset,
) -> None:
    original = _load(LOG_FIXTURE_DIR / "pytest_failure.txt")

    result = preset.route_and_compress("test_log", original)

    assert result.source_type == "test_log"
    assert result.compression_method == "log_compressor"
    assert result.metadata["compression_method"] == "log_compressor"
    assert result.metadata["accuracy_guard"] == "coding_agent_failure_evidence"
    assert not _missing(
        result.compressed,
        (
            "$ python -m pytest tests/test_checkout.py::test_discount_rounding -q",
            "FAILED tests/test_checkout.py::test_discount_rounding",
            "tests/test_checkout.py:42",
            'AssertionError: assert Decimal("9.99") == Decimal("10.00")',
            "exit code: 1",
        ),
    )
    assert result.compressed_length < result.original_length


def test_build_log_routes_to_log_compressor_and_preserves_root_cause(
    preset: CodingAgentPreset,
) -> None:
    original = _load(LOG_FIXTURE_DIR / "noisy_install_build.txt")

    result = preset.route_and_compress("build_log", original)

    assert result.source_type == "build_log"
    assert result.compression_method == "log_compressor"
    assert not _missing(
        result.compressed,
        (
            "$ npm ci && npm run build",
            "src/server/auth.ts:214:19 - error TS2345",
            "214     requireUser(session.user.id)",
            "ERROR: build failed while compiling src/server/auth.ts",
            "exit code: 2",
        ),
    )
    assert result.compressed.count("npm http fetch GET 200") < original.count(
        "npm http fetch GET 200"
    )


def test_search_results_group_preserves_query_paths_lines_and_matches(
    preset: CodingAgentPreset,
) -> None:
    original = _load(FIXTURE_DIR / "rg_results.txt")

    result = preset.route_and_compress(
        "search_results",
        original,
        {"context": "requireUser auth checkout"},
    )

    assert result.source_type == "search_results"
    assert result.compression_method == "search_compressor"
    assert '$ rg "requireUser|CheckoutSummary" -n src tests packages' in result.compressed
    assert "src/server/auth.ts:" in result.compressed
    assert "tests/server/auth.test.ts:" in result.compressed
    assert "requireUser" in result.compressed
    assert result.metadata["matches_omitted"] > 0
    assert "more matches" in result.compressed or result.ccr_hash is not None
    assert result.compressed_length < result.original_length


def test_file_tree_routes_to_file_tree_compressor_and_preserves_repo_shape(
    preset: CodingAgentPreset,
) -> None:
    original = _load(DIFF_TREE_FIXTURE_DIR / "repository_tree.txt")

    result = preset.route_and_compress(
        "file_tree",
        original,
        {
            "context": (
                "src/server/auth.ts src/checkout/session.ts "
                "tests/checkout/session.test.ts crates/headroom-core/src/auth.rs"
            )
        },
    )

    assert result.source_type == "file_tree"
    assert result.compression_method == "file_tree_compressor"
    assert not _missing(
        result.compressed,
        (
            "package.json",
            "pyproject.toml",
            "Cargo.toml",
            "|-- src/",
            "|   |-- server/",
            "|   |   |-- auth.ts",
            "|-- tests/",
            "|   |-- checkout/",
            "|   |   `-- session.test.ts",
        ),
    )
    assert "package_010" not in result.compressed
    assert result.metadata["omitted_line_count"] > 0


def test_git_diff_routes_to_diff_compressor_and_preserves_edit_targets(
    preset: CodingAgentPreset,
) -> None:
    original = _load(DIFF_TREE_FIXTURE_DIR / "python_package.diff")

    result = preset.route_and_compress(
        "git_diff",
        original,
        {"context": "billing discount tests audit"},
    )

    assert result.source_type == "git_diff"
    assert result.compression_method == "diff_compressor"
    assert not _missing(
        result.compressed,
        (
            "diff --git a/packages/billing/billing/discounts.py b/packages/billing/billing/discounts.py",
            "@@ -1,18 +1,21 @@",
            "+from billing.audit import record_discount_decision",
            "+def apply_discount",
            "diff --git a/packages/billing/tests/test_discounts.py b/packages/billing/tests/test_discounts.py",
            "test_apply_discount_records_audit_event",
        ),
    )
    assert result.metadata["files_affected"] >= 2


def test_package_metadata_preserves_scripts_dependencies_and_toolchain(
    preset: CodingAgentPreset,
) -> None:
    original = _load(FIXTURE_DIR / "package_metadata.json")

    result = preset.route_and_compress(
        "package_metadata",
        original,
        {"filename": "package.json"},
    )

    assert result.source_type == "package_metadata"
    assert result.compression_method == "package_metadata_compactor"
    assert not _missing(
        result.compressed,
        (
            "name: @acme/checkout-web",
            "version: 2.4.1",
            "packageManager: pnpm@9.4.0",
            "- build: tsc -b && vite build",
            "- test: vitest run",
            "dependencies (8):",
            "react",
            "zod",
            "devDependencies (8):",
            "typescript",
            "vitest",
        ),
    )
    assert "generatedMetadata" not in result.compressed
    assert result.compressed_length < result.original_length


def test_mcp_tool_response_preserves_tool_status_error_counts_and_first_result(
    preset: CodingAgentPreset,
) -> None:
    original = _load(FIXTURE_DIR / "mcp_response.json")

    result = preset.route_and_compress("mcp_tool_response", original)

    assert result.source_type == "mcp_tool_response"
    assert result.compression_method == "mcp_tool_response_compactor"
    assert not _missing(
        result.compressed,
        (
            "tool: repo.search",
            "status: error",
            "Permission denied reading src/server/secret.ts",
            "result_count: 9",
            "path=src/server/auth.ts",
            "resource_id=file:src/server/auth.ts",
            "MCP result objects omitted",
        ),
    )
    assert result.ccr_hash is not None


def test_generic_tool_output_preserves_errors_paths_status_and_collapses_noise(
    preset: CodingAgentPreset,
) -> None:
    original = _load(FIXTURE_DIR / "generic_noisy_output.txt")

    result = preset.route_and_compress("generic_tool_output", original)

    assert result.source_type == "generic_tool_output"
    assert result.compression_method == "generic_tool_output_compactor"
    assert not _missing(
        result.compressed,
        (
            "$ npm run generate && npm run check",
            "WARN workspace package apps/web has deprecated peer dependency",
            "src/server/auth.ts:214:19 ERROR expected SessionUser but got null",
            "tests/server/auth.test.ts:20:11 AssertionError: expected missing user error",
            "exit code: 2",
        ),
    )
    assert result.compressed.count("download package") < original.count("download package")
    assert result.compressed_length < result.original_length


def test_source_code_is_preserved_verbatim_not_blindly_compressed(
    preset: CodingAgentPreset,
) -> None:
    original = _load(FIXTURE_DIR / "source_code.py")

    result = preset.route_and_compress("generic_tool_output", original)

    assert result.source_type == "source_code"
    assert result.compression_method == "source_code_passthrough"
    assert result.accuracy_guard == "source_code_not_blindly_compressed"
    assert result.compressed == original
    assert result.saved_length == 0


def test_ccr_retrievability_for_omitted_preset_output(preset: CodingAgentPreset) -> None:
    original = _load(FIXTURE_DIR / "mcp_response.json")

    result = preset.route_and_compress("mcp_tool_response", original)

    markers = parse_ccr_markers(result.compressed)
    assert markers
    marker = markers[-1]
    assert result.ccr_hash == marker.hash
    assert result.ccr_marker == marker.raw
    assert normalize_ccr_hash(marker.raw) == result.ccr_hash

    injector = CCRToolInjector()
    assert injector.scan_for_markers([{"role": "tool", "content": result.compressed}]) == [
        result.ccr_hash
    ]

    entry = get_compression_store().retrieve(marker.raw)
    assert entry is not None
    assert entry.original_content == original
    assert entry.compressed_content == result.compressed


def test_auto_classification_and_metadata_are_stable(preset: CodingAgentPreset) -> None:
    original = _load(FIXTURE_DIR / "rg_results.txt")

    result = preset.route_and_compress(None, original, {"query": "requireUser"})

    assert result.source_type == "search_results"
    assert result.metadata["source_type"] == "search_results"
    assert result.metadata["compression_method"] == result.compression_method
    assert result.metadata["accuracy_guard"] == result.accuracy_guard
    assert result.metadata["original_length"] == len(original)
    assert result.metadata["compressed_length"] == len(result.compressed)
    assert result.metadata["saved_length"] == result.saved_length
    assert "ccr_hash" in result.metadata


def test_unknown_source_type_falls_back_safely_without_losing_evidence(
    preset: CodingAgentPreset,
) -> None:
    original = _load(FIXTURE_DIR / "generic_noisy_output.txt")

    result = preset.route_and_compress("unknown_shell_dump", original)

    assert result.source_type == "generic_tool_output"
    assert result.compression_method == "generic_tool_output_compactor"
    assert "src/server/auth.ts:214:19 ERROR expected SessionUser but got null" in result.compressed
    assert "exit code: 2" in result.compressed
