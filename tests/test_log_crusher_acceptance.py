from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest

from headroom.cache.compression_store import get_compression_store, reset_compression_store
from headroom.ccr.markers import normalize_ccr_hash, parse_ccr_markers
from headroom.ccr.tool_injection import CCRToolInjector
from headroom.transforms.log_compressor import LogCompressor, LogCompressorConfig

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "log_crusher"


@dataclass(frozen=True)
class LogFixtureCase:
    name: str
    must_keep: tuple[str, ...]
    noise_fragment: str


LOG_FIXTURES = (
    LogFixtureCase(
        name="pytest_failure.txt",
        must_keep=(
            "$ python -m pytest tests/test_checkout.py::test_discount_rounding -q",
            "FAILED tests/test_checkout.py::test_discount_rounding",
            "tests/test_checkout.py:42",
            'AssertionError: assert Decimal("9.99") == Decimal("10.00")',
            "exit code: 1",
        ),
        noise_fragment=" PASSED",
    ),
    LogFixtureCase(
        name="vitest_failure.txt",
        must_keep=(
            "$ npm test -- --run src/cart.test.ts",
            "FAIL src/cart.test.ts > cart totals > applies shipping discount",
            "AssertionError: expected 19.99 to be 14.99",
            "src/cart.test.ts:88:21",
            "exit code: 1",
        ),
        noise_fragment="PASS src/product.test.ts",
    ),
    LogFixtureCase(
        name="cargo_failure.txt",
        must_keep=(
            "$ cargo test -p checkout",
            "test checkout::tests::applies_tax ... FAILED",
            "crates/checkout/src/lib.rs:128:9",
            "thread 'checkout::tests::applies_tax' panicked at",
            "exit code: 101",
        ),
        noise_fragment="smoke_",
    ),
    LogFixtureCase(
        name="go_test_failure.txt",
        must_keep=(
            "$ go test ./...",
            "--- FAIL: TestRetryBackoff",
            "retry/retry_test.go:87",
            "expected delay 200ms, got 20ms",
            "exit code: 1",
        ),
        noise_fragment="ok github.com/acme/agent/noise",
    ),
    LogFixtureCase(
        name="maven_failure.txt",
        must_keep=(
            "$ mvn test -pl billing-service",
            "PaymentServiceTest.appliesDiscount:57 expected:<10.00> but was:<9.99>",
            "Failed to execute goal org.apache.maven.plugins:maven-surefire-plugin",
            "BUILD FAILURE",
            "exit code: 1",
        ),
        noise_fragment="Downloading dependency-",
    ),
    LogFixtureCase(
        name="noisy_install_build.txt",
        must_keep=(
            "$ npm ci && npm run build",
            "src/server/auth.ts:214:19 - error TS2345",
            "214     requireUser(session.user.id)",
            "ERROR: build failed while compiling src/server/auth.ts",
            "exit code: 2",
        ),
        noise_fragment="npm http fetch GET 200",
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


def _assert_fixture_contract(case: LogFixtureCase, content: str) -> None:
    missing = _missing_required_fragments(content, case.must_keep)
    assert not missing, f"{case.name} fixture is missing required evidence: {missing!r}"
    assert content.count(case.noise_fragment) >= 10, (
        f"{case.name} fixture needs enough repeated noise for compression acceptance"
    )


@pytest.mark.parametrize("case", LOG_FIXTURES, ids=lambda case: case.name)
def test_log_crusher_preserves_failure_evidence_and_collapses_noise(
    case: LogFixtureCase,
) -> None:
    original = _load_fixture(case.name)
    _assert_fixture_contract(case, original)

    compressor = LogCompressor(
        LogCompressorConfig(
            enable_ccr=True,
            min_lines_for_ccr=10,
            max_total_lines=24,
            max_warnings=2,
        )
    )

    result = compressor.compress(original)

    missing = _missing_required_fragments(result.compressed, case.must_keep)
    assert not missing, f"{case.name} compressed output dropped required evidence: {missing!r}"
    assert len(result.compressed) < len(original)
    assert result.compressed_line_count < result.original_line_count

    original_noise = original.count(case.noise_fragment)
    compressed_noise = result.compressed.count(case.noise_fragment)
    assert compressed_noise < original_noise
    assert compressed_noise <= max(5, original_noise // 4)

    # TODO(#19): replace these local stats assertions with accuracy-ledger
    # assertions once transform-level ledger emission exists.
    assert result.stats["evidence_guard_required"] == 1
    assert result.stats["evidence_guard_candidates"] > 0
    assert result.stats["evidence_guard_missing_after_guard"] == 0


def test_fixture_contract_catches_missing_critical_failure_line() -> None:
    case = LOG_FIXTURES[0]
    original = _load_fixture(case.name)
    damaged = original.replace(
        'E   AssertionError: assert Decimal("9.99") == Decimal("10.00")',
        "E   line removed from fixture",
    )

    with pytest.raises(AssertionError, match="missing required evidence"):
        _assert_fixture_contract(case, damaged)


def test_log_ccr_marker_is_parseable_injectable_and_retrievable() -> None:
    original = _load_fixture("cargo_failure.txt")
    compressor = LogCompressor(
        LogCompressorConfig(
            enable_ccr=True,
            min_lines_for_ccr=10,
            max_total_lines=24,
            max_warnings=2,
        )
    )

    result = compressor.compress(original)

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
