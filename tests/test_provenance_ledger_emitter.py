from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from headroom.cache.compression_store import get_compression_store, reset_compression_store
from headroom.presets import CodingAgentPreset, CodingAgentPresetConfig
from headroom.telemetry.ledger import (
    TOKEN_COUNT_METHOD,
    InMemoryLedgerEmitter,
    JsonlLedgerEmitter,
    LedgerEvent,
    event_to_otel_attributes,
    reset_ledger_emitter,
    set_ledger_emitter,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "coding_agent_presets"
LOG_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "log_crusher"
DIFF_TREE_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "diff_file_tree_crusher"


@pytest.fixture(autouse=True)
def _clean_state() -> Generator[None, None, None]:
    reset_compression_store()
    reset_ledger_emitter()
    try:
        yield
    finally:
        reset_compression_store()
        reset_ledger_emitter()


def _load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _preset(emitter: InMemoryLedgerEmitter | None = None) -> CodingAgentPreset:
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
        ),
        ledger_emitter=emitter,
    )


def test_ledger_event_serializes_required_local_fields() -> None:
    event = LedgerEvent.create(
        "bridge.compression.completed",
        source_type="test_log",
        compression_method="log_compressor",
        original_tokens=100,
        compressed_tokens=40,
        saved_tokens=60,
    )

    data = event.to_dict()

    assert data["schema_version"] == "ledger-event-v0"
    assert data["event_type"] == "bridge.compression.completed"
    assert data["event_id"]
    assert data["event_grade"] == "source"
    assert data["tenant_id"] == "local"
    assert data["project_id"] == "local"
    assert data["session_id"] == "local"
    assert data["request_id"] == "local"
    assert data["deployment_mode"] == "local_dev"
    assert data["bridge_instance_id"] == "headroom-local"
    assert data["idempotency_key"].startswith("bridge.compression.completed:local:")
    assert data["time_window"]["started_at"]
    assert data["occurred_at"]
    assert json.loads(event.to_json())["event_id"] == data["event_id"]


def test_env_defaults_fill_project_session_and_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEADROOM_LEDGER_PROJECT_ID", "proj-local")
    monkeypatch.setenv("HEADROOM_LEDGER_SESSION_ID", "sess-123")
    monkeypatch.setenv("HEADROOM_LEDGER_DEPLOYMENT_MODE", "local_test")
    monkeypatch.setenv("HEADROOM_LEDGER_BRIDGE_INSTANCE_ID", "headroom-dev")

    event = LedgerEvent.create("bridge.source.attributed")
    data = event.to_dict()

    assert data["tenant_id"] == "local"
    assert data["project_id"] == "proj-local"
    assert data["session_id"] == "sess-123"
    assert data["deployment_mode"] == "local_test"
    assert data["bridge_instance_id"] == "headroom-dev"


def test_jsonl_emitter_writes_one_event_per_line(tmp_path: Path) -> None:
    path = tmp_path / "ledger" / "events.jsonl"
    emitter = JsonlLedgerEmitter(path)

    emitter.emit(LedgerEvent.create("bridge.compression.completed", source_type="test_log"))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event_type"] == "bridge.compression.completed"


def test_jsonl_emitter_appends_multiple_events(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    emitter = JsonlLedgerEmitter(path)

    emitter.emit(LedgerEvent.create("bridge.compression.completed"))
    emitter.emit(LedgerEvent.create("bridge.compression.bypassed"))

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["sequence_number"] for line in lines] == [1, 2]
    assert [line["event_type"] for line in lines] == [
        "bridge.compression.completed",
        "bridge.compression.bypassed",
    ]


def test_otel_attributes_use_bridge_namespace() -> None:
    event = LedgerEvent.create(
        "bridge.compression.completed",
        source_id="source-1",
        provider_request_id="provider-1",
        source_type="git_diff",
        compression_method="diff_compressor",
        original_tokens=80,
        compressed_tokens=20,
        saved_tokens=60,
        ccr_marker_id="abcdefabcdefabcdefabcdef",
        cache_zone="prompt",
        accuracy_guard="edit_target_diff_evidence",
    )

    attrs = event_to_otel_attributes(event)

    assert attrs["bridge.event_type"] == "bridge.compression.completed"
    assert attrs["bridge.source_type"] == "git_diff"
    assert attrs["bridge.compression_method"] == "diff_compressor"
    assert attrs["bridge.ccr_marker_id"] == "abcdefabcdefabcdefabcdef"
    assert attrs["bridge.accuracy_guard"] == "edit_target_diff_evidence"
    assert all(key.startswith("bridge.") for key in attrs)


def test_no_kuchino_identifiers_in_telemetry_code() -> None:
    telemetry_dir = Path(__file__).parents[1] / "headroom" / "telemetry"
    content = "\n".join(path.read_text(encoding="utf-8") for path in telemetry_dir.rglob("*.py"))
    assert "kuchino." not in content.lower()
    assert "KUCHINO_" not in content


def test_coding_agent_preset_emits_test_log_event() -> None:
    emitter = InMemoryLedgerEmitter()
    original = _load(LOG_FIXTURE_DIR / "pytest_failure.txt")

    result = _preset(emitter).route_and_compress(
        "test_log",
        original,
        {"source_id": "pytest-log", "provider": "openai", "model": "gpt-test"},
    )

    assert result.compression_method == "log_compressor"
    assert len(emitter.events) == 1
    event = emitter.events[0].to_dict()
    assert event["event_type"] == "bridge.compression.completed"
    assert event["source_id"] == "pytest-log"
    assert event["source_type"] == "test_log"
    assert event["compression_method"] == "log_compressor"
    assert event["accuracy_guard"] == "coding_agent_failure_evidence"
    assert event["provider"] == "openai"
    assert event["model"] == "gpt-test"
    assert event["original_tokens"] > event["compressed_tokens"]
    assert event["saved_tokens"] > 0
    assert event["token_count_method"] == TOKEN_COUNT_METHOD


def test_coding_agent_preset_emits_file_tree_event_with_ccr_marker() -> None:
    emitter = InMemoryLedgerEmitter()
    original = _load(DIFF_TREE_FIXTURE_DIR / "repository_tree.txt")

    result = _preset(emitter).route_and_compress(
        "file_tree",
        original,
        {"context": "src/server/auth.ts tests/checkout/session.test.ts"},
    )

    assert result.ccr_hash is not None
    event = emitter.events[0].to_dict()
    assert event["event_type"] == "bridge.compression.completed"
    assert event["source_type"] == "file_tree"
    assert event["compression_method"] == "file_tree_compressor"
    assert event["ccr_marker_id"] == result.ccr_hash
    assert event["accuracy_guard"] == "edit_target_tree_evidence"


def test_coding_agent_preset_emits_search_event_with_source_metadata() -> None:
    emitter = InMemoryLedgerEmitter()
    original = _load(FIXTURE_DIR / "rg_results.txt")

    _preset(emitter).route_and_compress(
        "search_results",
        original,
        {"source_path": "rg:requireUser", "query": "requireUser"},
    )

    event = emitter.events[0].to_dict()
    assert event["source_type"] == "search_results"
    assert event["source_path"] == "rg:requireUser"
    assert event["compression_method"] == "search_compressor"
    assert event["original_tokens"] >= event["compressed_tokens"]
    assert event["saved_tokens"] >= 0


def test_source_code_bypass_emits_bypassed_event() -> None:
    emitter = InMemoryLedgerEmitter()
    original = _load(FIXTURE_DIR / "source_code.py")

    result = _preset(emitter).route_and_compress("source_code", original)

    assert result.compressed == original
    event = emitter.events[0].to_dict()
    assert event["event_type"] == "bridge.compression.bypassed"
    assert event["source_type"] == "source_code"
    assert event["compression_method"] == "source_code_passthrough"
    assert event["saved_tokens"] == 0


def test_telemetry_write_failure_does_not_fail_compression(tmp_path: Path) -> None:
    emitter = JsonlLedgerEmitter(tmp_path)
    original = _load(FIXTURE_DIR / "generic_noisy_output.txt")

    result = _preset(emitter).route_and_compress("generic_tool_output", original)

    assert result.compression_method == "generic_tool_output_compactor"


def test_ccr_retrieve_emits_retrieved_event() -> None:
    emitter = InMemoryLedgerEmitter()
    set_ledger_emitter(emitter)
    store = get_compression_store()
    hash_key = store.store(
        "original content for ledger retrieve",
        "compressed content",
        original_tokens=24,
        compressed_tokens=8,
        original_item_count=3,
        compressed_item_count=1,
        tool_signature_hash="source-ccr",
        compression_strategy="coding_agent_generic_tool_output",
    )

    entry = store.retrieve(hash_key, query="ledger")

    assert entry is not None
    event = emitter.events[-1].to_dict()
    assert event["event_type"] == "bridge.ccr.retrieved"
    assert event["source_id"] == "source-ccr"
    assert event["source_type"] == "coding_agent_generic_tool_output"
    assert event["compression_method"] == "coding_agent_generic_tool_output"
    assert event["ccr_marker_id"] == hash_key
    assert event["ccr_backend"].endswith("Backend")
    assert event["retrieved_count"] == 1



def test_ledger_token_count_method_label_matches_computation() -> None:
    """RED for fork-review finding #2 (NN2): the coding-agent preset records
    word-count (.split()) values in result.metadata['original_tokens'] /
    ['compressed_tokens'], and _emit_ledger_event emits those as saved_tokens
    while labelling token_count_method=TOKEN_COUNT_METHOD ('estimated_chars_div_4').
    The declared method must match the emitted numbers. Isolated from the Rust
    compressor by constructing the result directly."""
    from headroom.telemetry.ledger import estimate_tokens
    from headroom.presets.coding_agent import CodingAgentPresetResult

    emitter = InMemoryLedgerEmitter()
    preset = _preset(emitter)
    original = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    compressed = "alpha beta gamma"
    # Mirror exactly what the preset writes today: WORD COUNTS.
    metadata = {
        "source_type": "test_log",
        "compression_method": "log_compressor",
        "accuracy_guard": "coding_agent_failure_evidence",
        "original_length": len(original),
        "compressed_length": len(compressed),
        "original_tokens": len(original.split()),
        "compressed_tokens": len(compressed.split()),
    }
    result = CodingAgentPresetResult(
        compressed=compressed,
        original=original,
        source_type="test_log",
        compression_method="log_compressor",
        accuracy_guard="coding_agent_failure_evidence",
        original_length=len(original),
        compressed_length=len(compressed),
        metadata=metadata,
    )
    preset._emit_ledger_event(result, {"source_id": "x", "provider": "openai", "model": "gpt-test"})
    event = emitter.events[0].to_dict()
    assert event["token_count_method"] == "estimated_chars_div_4"
    # The emitted token counts must BE the method they are labelled with.
    assert event["original_tokens"] == estimate_tokens(original), (
        f"label says estimated_chars_div_4 but original_tokens={event['original_tokens']} "
        f"!= estimate_tokens={estimate_tokens(original)} (word-count vs chars/4 mislabel)"
    )
