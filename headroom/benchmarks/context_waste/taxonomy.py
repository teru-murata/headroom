"""Local source taxonomy for coding-agent context waste benchmarks."""

from __future__ import annotations

SOURCE_TAXONOMY_VERSION = "source-taxonomy-v0"

REQUIRED_SOURCE_TYPES: tuple[str, ...] = (
    "tool_definitions",
    "mcp_schemas",
    "tool_outputs",
    "build_logs",
    "test_logs",
    "search_results",
    "file_reads",
    "file_trees",
    "git_diffs",
    "rag_chunks",
    "api_db_responses",
    "conversation_history_residue",
    "agent_memory_files",
    "ccr_retrievals",
    "sandbox_artifacts",
)

COMPATIBILITY_SOURCE_TYPES: tuple[str, ...] = (
    "package_metadata",
    "mcp_tool_response",
)

ALL_SOURCE_TYPES: tuple[str, ...] = REQUIRED_SOURCE_TYPES + COMPATIBILITY_SOURCE_TYPES

_ALIASES = {
    "tool_definition": "tool_definitions",
    "mcp_schema": "mcp_schemas",
    "tool_output": "tool_outputs",
    "build_log": "build_logs",
    "test_log": "test_logs",
    "file_read": "file_reads",
    "file_tree": "file_trees",
    "git_diff": "git_diffs",
    "rag_chunk": "rag_chunks",
    "api_db_response": "api_db_responses",
    "conversation_history": "conversation_history_residue",
    "memory_files": "agent_memory_files",
    "ccr_retrieval": "ccr_retrievals",
    "sandbox_artifact": "sandbox_artifacts",
    "mcp_response": "mcp_tool_response",
}


def normalize_source_type(value: str) -> str:
    """Normalize and validate a local source-taxonomy-v0 value."""
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    normalized = _ALIASES.get(normalized, normalized)
    if normalized not in ALL_SOURCE_TYPES:
        supported = ", ".join(ALL_SOURCE_TYPES)
        msg = f"unsupported source_type {value!r}; supported values: {supported}"
        raise ValueError(msg)
    return normalized


def missing_required_source_types(values: set[str]) -> list[str]:
    """Return required taxonomy categories absent from a manifest."""
    return [source_type for source_type in REQUIRED_SOURCE_TYPES if source_type not in values]


def validate_required_source_types(values: set[str]) -> None:
    """Raise if a manifest does not cover every required source type."""
    missing = missing_required_source_types(values)
    if missing:
        msg = "manifest missing required source_type values: " + ", ".join(missing)
        raise ValueError(msg)
