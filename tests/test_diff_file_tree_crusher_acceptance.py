from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest

from headroom.cache.compression_store import get_compression_store, reset_compression_store
from headroom.ccr.markers import normalize_ccr_hash, parse_ccr_markers
from headroom.ccr.tool_injection import CCRToolInjector
from headroom.transforms import (
    ContentRouter,
    ContentRouterConfig,
    ContentType,
    DiffCompressor,
    DiffCompressorConfig,
    FileTreeCompressor,
    FileTreeCompressorConfig,
)
from headroom.transforms.content_detector import _try_detect_file_tree, detect_content_type
from headroom.transforms.content_router import CompressionStrategy

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "diff_file_tree_crusher"


@dataclass(frozen=True)
class DiffFixtureCase:
    name: str
    must_keep: tuple[str, ...]
    noise_fragment: str | None = None
    context: str = ""


@dataclass(frozen=True)
class FileTreeFixtureCase:
    name: str
    context: str
    must_keep: tuple[str, ...]
    generated_noise: tuple[str, ...]


DIFF_FIXTURES = (
    DiffFixtureCase(
        name="python_package.diff",
        context="billing discount rounding failure packages/billing/tests/test_discounts.py",
        must_keep=(
            "diff --git a/packages/billing/billing/discounts.py b/packages/billing/billing/discounts.py",
            "--- a/packages/billing/billing/discounts.py",
            "+++ b/packages/billing/billing/discounts.py",
            "@@ -1,18 +1,21 @@",
            "+from billing.audit import record_discount_decision",
            "+def apply_discount",
            "diff --git a/packages/billing/tests/test_discounts.py b/packages/billing/tests/test_discounts.py",
            "test_apply_discount_rounds_half_up",
            "test_apply_discount_records_audit_event",
        ),
        noise_fragment="unchanged_py_context_",
    ),
    DiffFixtureCase(
        name="typescript_react.diff",
        context="CheckoutSummary shipping estimate test storybook config",
        must_keep=(
            "diff --git a/apps/web/src/components/CheckoutSummary.tsx b/apps/web/src/components/CheckoutSummary.tsx",
            "@@ -1,16 +1,18 @@",
            '+import { useShippingEstimate } from "../hooks/useShippingEstimate";',
            "+export function CheckoutSummary",
            "diff --git a/apps/web/src/components/CheckoutSummary.test.tsx b/apps/web/src/components/CheckoutSummary.test.tsx",
            "renders subtotal and shipping estimate",
            "diff --git a/apps/web/.storybook/main.ts b/apps/web/.storybook/main.ts",
            '+  staticDirs: ["../public"],',
        ),
        noise_fragment="boilerplate_ts_",
    ),
    DiffFixtureCase(
        name="rust_crate.diff",
        context="checkout crate request_id uuid Cargo.toml session test",
        must_keep=(
            "diff --git a/crates/checkout/Cargo.toml b/crates/checkout/Cargo.toml",
            '+uuid = { version = "1", features = ["v7"] }',
            "diff --git a/crates/checkout/src/lib.rs b/crates/checkout/src/lib.rs",
            "pub struct CheckoutSession",
            "+pub fn create_checkout_session",
            "diff --git a/crates/checkout/tests/session.rs b/crates/checkout/tests/session.rs",
            "creates_checkout_session_request_id",
            "diff --git a/Cargo.lock b/Cargo.lock",
            'name = "uuid"',
        ),
        noise_fragment="unchanged_rust_context_",
    ),
    DiffFixtureCase(
        name="large_noisy.diff",
        context="auth required auditAuthFailure src/server/auth.ts",
        must_keep=(
            "diff --git a/src/server/auth.ts b/src/server/auth.ts",
            "--- a/src/server/auth.ts",
            "+++ b/src/server/auth.ts",
            "@@ -1,16 +1,19 @@",
            '+import { auditAuthFailure } from "./audit";',
            "export async function requireUser",
            "+    auditAuthFailure(userId);",
            "diff --git a/package-lock.json b/package-lock.json",
            "diff --git a/dist/client.min.js b/dist/client.min.js",
        ),
    ),
    DiffFixtureCase(
        name="rename_delete_add.diff",
        context="billing policy rename delete add gateway",
        must_keep=(
            "diff --git a/services/billing/old_policy.py b/services/billing/discount_policy.py",
            "similarity index 87%",
            "rename from services/billing/old_policy.py",
            "rename to services/billing/discount_policy.py",
            "@@ -1,5 +1,7 @@",
            "+def discount_policy_for_account",
            "diff --git a/services/billing/legacy.py b/services/billing/legacy.py",
            "deleted file mode 100644",
            "+++ /dev/null",
            "diff --git a/services/billing/new_gateway.py b/services/billing/new_gateway.py",
            "new file mode 100644",
            "--- /dev/null",
            "+class BillingGateway",
        ),
    ),
)


FILE_TREE_FIXTURE = FileTreeFixtureCase(
    name="repository_tree.txt",
    context=(
        "Recently changed paths: src/server/auth.ts src/checkout/session.ts "
        "tests/checkout/session.test.ts crates/headroom-core/src/auth.rs"
    ),
    must_keep=(
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "go.mod",
        "|-- src/",
        "|   |-- server/",
        "|   |   |-- auth.ts",
        "|   |-- checkout/",
        "|   |   |-- session.ts",
        "|-- tests/",
        "|   |-- checkout/",
        "|   |   `-- session.test.ts",
        "|-- .github/",
        "|   |   |-- ci.yml",
        "|-- crates/",
        "|   |   |   |-- auth.rs",
    ),
    generated_noise=(
        "package_010",
        "bundle_004",
        "chunk_006.js",
        "generated_004.o",
        "report_003.html",
        "entry_003",
    ),
)


@pytest.fixture(autouse=True)
def _clean_ccr_store() -> Generator[None, None, None]:
    reset_compression_store()
    try:
        yield
    finally:
        reset_compression_store()


def _load_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _missing_required_fragments(content: str, fragments: tuple[str, ...]) -> list[str]:
    return [fragment for fragment in fragments if fragment not in content]


def _diff_compressor() -> DiffCompressor:
    return DiffCompressor(
        DiffCompressorConfig(
            max_context_lines=2,
            max_hunks_per_file=8,
            max_files=12,
            enable_ccr=True,
            min_lines_for_ccr=10,
        )
    )


@pytest.mark.parametrize("case", DIFF_FIXTURES, ids=lambda case: case.name)
def test_diff_crusher_preserves_edit_target_evidence(case: DiffFixtureCase) -> None:
    original = _load_fixture(case.name)
    missing = _missing_required_fragments(original, case.must_keep)
    assert not missing, f"{case.name} fixture is missing required evidence: {missing!r}"

    result = _diff_compressor().compress(original, context=case.context)

    # TODO(#19): once transform-level ledger emission exists, replace this
    # must-keep assertion set with accuracy-ledger assertions for diff evidence.
    missing = _missing_required_fragments(result.compressed, case.must_keep)
    assert not missing, f"{case.name} compressed diff dropped required evidence: {missing!r}"
    assert result.compressed_line_count <= result.original_line_count
    assert "diff --git " in result.compressed
    assert "@@ " in result.compressed


@pytest.mark.parametrize(
    "case",
    [case for case in DIFF_FIXTURES if case.noise_fragment is not None],
    ids=lambda case: case.name,
)
def test_diff_crusher_collapses_excessive_context_without_losing_targets(
    case: DiffFixtureCase,
) -> None:
    original = _load_fixture(case.name)
    assert case.noise_fragment is not None
    assert original.count(case.noise_fragment) >= 4

    result = _diff_compressor().compress(original, context=case.context)

    assert result.compressed_line_count < result.original_line_count
    assert result.compressed.count(case.noise_fragment) < original.count(case.noise_fragment)
    missing = _missing_required_fragments(result.compressed, case.must_keep)
    assert not missing


def test_diff_ccr_marker_is_parseable_injectable_and_retrievable() -> None:
    original = _load_fixture("python_package.diff")

    result = _diff_compressor().compress(original, context="billing discount")

    assert result.cache_key is not None
    markers = parse_ccr_markers(result.compressed)
    assert markers
    marker = markers[-1]
    assert marker.family == "bracket_retrieve"
    assert marker.hash == result.cache_key
    assert normalize_ccr_hash(marker.raw) == result.cache_key

    injector = CCRToolInjector()
    assert injector.scan_for_markers([{"role": "tool", "content": result.compressed}]) == [
        result.cache_key
    ]

    entry = get_compression_store().retrieve(marker.raw)
    assert entry is not None
    assert entry.original_content == original
    assert entry.compressed_content == result.compressed


def test_large_noisy_diff_keeps_meaningful_source_change_and_compresses() -> None:
    original = _load_fixture("large_noisy.diff")

    result = _diff_compressor().compress(original, context="auth audit")

    must_keep = next(case.must_keep for case in DIFF_FIXTURES if case.name == "large_noisy.diff")
    missing = _missing_required_fragments(result.compressed, must_keep)
    assert not missing
    assert result.compressed_line_count < result.original_line_count


def test_file_tree_detector_recognizes_repository_tree() -> None:
    original = _load_fixture(FILE_TREE_FIXTURE.name)

    detection = detect_content_type(original)
    assert detection.content_type == ContentType.FILE_TREE

    regex_detection = _try_detect_file_tree(original)
    assert regex_detection is not None
    assert regex_detection.metadata["tree_lines"] > 20
    assert regex_detection.metadata["config_files"] >= 4


def _file_tree_compressor() -> FileTreeCompressor:
    return FileTreeCompressor(
        FileTreeCompressorConfig(
            max_lines=70,
            max_depth=4,
            enable_ccr=True,
            min_lines_for_ccr=20,
        )
    )


def test_file_tree_crusher_preserves_repo_shape_and_collapses_generated_noise() -> None:
    original = _load_fixture(FILE_TREE_FIXTURE.name)
    missing = _missing_required_fragments(original, FILE_TREE_FIXTURE.must_keep)
    assert not missing, f"file-tree fixture is missing required evidence: {missing!r}"
    for fragment in FILE_TREE_FIXTURE.generated_noise:
        assert fragment in original

    result = _file_tree_compressor().compress(original, context=FILE_TREE_FIXTURE.context)

    # TODO(#19): once ledger emission exists, connect file-tree edit-target
    # preservation metadata here instead of only asserting fragments.
    missing = _missing_required_fragments(result.compressed, FILE_TREE_FIXTURE.must_keep)
    assert not missing, f"compressed file tree dropped required paths: {missing!r}"
    assert result.compressed_line_count < result.original_line_count
    assert result.collapsed_directories >= 5
    assert result.omitted_line_count > 0
    assert result.preserved_relevant_paths >= 4

    for fragment in FILE_TREE_FIXTURE.generated_noise:
        assert fragment not in result.compressed
    for collapsed_dir in ("node_modules", "vendor", "dist", "build", "coverage", ".cache"):
        assert f"[{collapsed_dir}/ omitted generated/cache subtree]" in result.compressed


def test_file_tree_ccr_marker_is_parseable_injectable_and_retrievable() -> None:
    original = _load_fixture(FILE_TREE_FIXTURE.name)

    result = _file_tree_compressor().compress(original, context=FILE_TREE_FIXTURE.context)

    assert result.cache_key is not None
    markers = parse_ccr_markers(result.compressed)
    assert markers
    marker = markers[-1]
    assert marker.family == "bracket_retrieve"
    assert marker.hash == result.cache_key
    assert normalize_ccr_hash(marker.raw) == result.cache_key

    injector = CCRToolInjector()
    assert injector.scan_for_markers([{"role": "tool", "content": result.compressed}]) == [
        result.cache_key
    ]

    entry = get_compression_store().retrieve(marker.raw)
    assert entry is not None
    assert entry.original_content == original
    assert entry.compressed_content == result.compressed


def test_content_router_uses_file_tree_compressor_for_repository_tree() -> None:
    original = _load_fixture(FILE_TREE_FIXTURE.name)
    router = ContentRouter(
        ContentRouterConfig(
            min_section_tokens=10,
            enable_kompress=False,
        )
    )

    result = router.compress(original, context=FILE_TREE_FIXTURE.context)

    assert result.strategy_used == CompressionStrategy.FILE_TREE
    assert result.routing_log[0].content_type == ContentType.FILE_TREE
    assert result.routing_log[0].strategy == CompressionStrategy.FILE_TREE
    assert result.compressed != original
    assert (
        "src/checkout/session.ts" in result.compressed
        or "|   |   |-- session.ts" in result.compressed
    )
    assert "package_010" not in result.compressed
