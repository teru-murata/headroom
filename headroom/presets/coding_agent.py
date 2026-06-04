"""Evidence-preserving compression preset for coding-agent tool outputs."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from headroom.ccr.markers import parse_ccr_markers
from headroom.transforms.content_detector import ContentType, detect_content_type

logger = logging.getLogger(__name__)

_SUPPORTED_SOURCE_TYPES = {
    "test_log",
    "build_log",
    "search_results",
    "file_tree",
    "git_diff",
    "package_metadata",
    "mcp_tool_response",
    "generic_tool_output",
    "source_code",
    "lockfile",
    "schema_or_openapi",
    "api_db_response",
}
_SOURCE_TYPE_ALIASES = {
    "test": "test_log",
    "tests": "test_log",
    "test_output": "test_log",
    "build": "build_log",
    "log": "build_log",
    "logs": "build_log",
    "rg": "search_results",
    "ripgrep": "search_results",
    "grep": "search_results",
    "search": "search_results",
    "tree": "file_tree",
    "diff": "git_diff",
    "package": "package_metadata",
    "package_json": "package_metadata",
    "metadata": "package_metadata",
    "mcp": "mcp_tool_response",
    "tool_response": "mcp_tool_response",
    "tool": "generic_tool_output",
    "generic": "generic_tool_output",
    "code": "source_code",
    "source": "source_code",
    "sourcecode": "source_code",
}
_PACKAGE_FILENAMES = {
    "package.json",
    "pyproject.toml",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "settings.gradle",
    "requirements.txt",
}
_LOCKFILE_NAMES = {
    "cargo.lock",
    "go.sum",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}
_SCRIPT_KEYS = {
    "scripts",
    "bin",
}
_DEPENDENCY_KEYS = {
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
    "bundledDependencies",
}
_TOOLCHAIN_KEYS = {
    "engines",
    "packageManager",
    "workspaces",
    "private",
    "type",
    "main",
    "module",
    "exports",
}
_COMMAND_RE = re.compile(
    r"^\s*(?:\$|>|command:|cmd:|running command:|original command:)\s+.+",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(
    r"\b(?:exit code|exited with code|status|success|failure|failed|returned non-zero)\b",
    re.IGNORECASE,
)
_ERROR_RE = re.compile(
    r"\b(?:ERROR|ERR!|FAIL|FAILED|FATAL|panic|panicked|AssertionError|Exception|"
    r"TypeError|ValueError|BUILD FAILED|BUILD FAILURE)\b",
    re.IGNORECASE,
)
_WARN_RE = re.compile(r"\b(?:WARN|WARNING)\b", re.IGNORECASE)
_FILE_LINE_RE = re.compile(
    r"(?:[A-Za-z]:)?(?:[\\/][A-Za-z0-9_.@+ -]+)+:\d+(?::\d+)?"
    r"|[A-Za-z0-9_.@+-]+(?:[\\/][A-Za-z0-9_.@+-]+)+:\d+(?::\d+)?"
    r"|[A-Za-z0-9_.@+-]+\.(?:py|js|jsx|ts|tsx|go|rs|java|kt|c|cc|cpp|h|hpp|cs|rb|php):"
    r"\d+(?::\d+)?"
)
_PROGRESS_RE = re.compile(
    r"^\s*(?:\[[=>#.\s-]{8,}\]|\d{1,3}%|\s*(?:download|fetch|install|build)\s+\d+/\d+)",
    re.IGNORECASE,
)
_JSON_PATH_RE = re.compile(
    r"(?:[A-Za-z0-9_.@+-]+[\\/]){1,}[A-Za-z0-9_.@+-]+(?:\.[A-Za-z0-9_.@+-]+)?"
)
_TEST_LOG_RE = re.compile(
    r"\b(?:pytest|unittest|jest|vitest|cargo test|go test|mvn test|gradle test|"
    r"FAILED\s+\S+|FAIL\s+\S+|--- FAIL:|short test summary)\b",
    re.IGNORECASE,
)
_BUILD_LOG_RE = re.compile(
    r"\b(?:npm run build|cargo build|go build|javac|tsc|mvn package|gradle build|"
    r"error\[E\d+\]|TS\d{4}|compilation failed|compile failed)\b",
    re.IGNORECASE,
)


@dataclass
class CodingAgentPresetConfig:
    """Configuration for the coding-agent preset."""

    enable_ccr: bool = True
    min_lines_for_ccr: int = 40
    min_chars_for_ccr: int = 1200
    max_log_lines: int = 48
    max_search_matches_per_file: int = 4
    max_search_matches: int = 24
    max_file_tree_lines: int = 90
    max_generic_lines: int = 80
    generic_leading_lines: int = 8
    max_mcp_results: int = 5
    max_dependency_names: int = 40


@dataclass
class CodingAgentPresetResult:
    """Compression result with stable metadata for coding-agent sources."""

    compressed: str
    original: str
    source_type: str
    compression_method: str
    accuracy_guard: str
    original_length: int
    compressed_length: int
    ccr_hash: str | None = None
    ccr_marker: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def saved_length(self) -> int:
        return max(0, self.original_length - self.compressed_length)

    @property
    def original_tokens(self) -> int:
        return len(self.original.split())

    @property
    def compressed_tokens(self) -> int:
        return len(self.compressed.split())


class CodingAgentPreset:
    """Route noisy coding-agent context sources to deterministic compressors."""

    def __init__(
        self,
        config: CodingAgentPresetConfig | None = None,
        ledger_emitter: Any | None = None,
    ) -> None:
        self.config = config or CodingAgentPresetConfig()
        self._ledger_emitter = ledger_emitter

    def route_and_compress(
        self,
        source_type: str | None,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> CodingAgentPresetResult:
        """Classify or accept a source type, then compress with the matching route."""
        metadata = dict(metadata or {})
        source = self._resolve_source_type(source_type, text, metadata)
        if source != "source_code" and self._looks_like_source_code(text):
            source = "source_code"

        context = str(metadata.get("context") or metadata.get("query") or "")
        if source == "test_log":
            result = self._compress_log(source, text, metadata, context)
        elif source == "build_log":
            result = self._compress_log(source, text, metadata, context)
        elif source == "search_results":
            result = self._compress_search(text, metadata, context)
        elif source == "file_tree":
            result = self._compress_file_tree(text, metadata, context)
        elif source == "git_diff":
            result = self._compress_diff(text, metadata, context)
        elif source in {"package_metadata", "lockfile"}:
            result = self._compress_package_metadata(source, text, metadata)
        elif source in {"mcp_tool_response", "api_db_response"}:
            result = self._compress_mcp_tool_response(source, text, metadata)
        elif source == "schema_or_openapi":
            result = self._compress_generic_tool_output(source, text, metadata)
        elif source == "source_code":
            result = self._passthrough_source_code(text, metadata)
        else:
            result = self._compress_generic_tool_output("generic_tool_output", text, metadata)
        self._emit_ledger_event(result, metadata)
        return result

    def compress(
        self,
        text: str,
        *,
        source_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CodingAgentPresetResult:
        """Keyword-friendly alias for ``route_and_compress``."""
        return self.route_and_compress(source_type, text, metadata)

    def _resolve_source_type(
        self,
        source_type: str | None,
        text: str,
        metadata: dict[str, Any],
    ) -> str:
        requested = source_type or metadata.get("source_type")
        if isinstance(requested, str):
            normalized = requested.strip().lower().replace("-", "_").replace(" ", "_")
            normalized = _SOURCE_TYPE_ALIASES.get(normalized, normalized)
            if normalized in _SUPPORTED_SOURCE_TYPES:
                return normalized
            return "generic_tool_output"

        filename = str(metadata.get("filename") or metadata.get("path") or "")
        if self._looks_like_package_metadata(text, filename):
            return "package_metadata"
        if self._looks_like_mcp_tool_response(text, metadata):
            return "mcp_tool_response"
        if _TEST_LOG_RE.search(text):
            return "test_log"
        if _BUILD_LOG_RE.search(text):
            return "build_log"

        detection = detect_content_type(text)
        if detection.content_type is ContentType.GIT_DIFF:
            return "git_diff"
        if detection.content_type is ContentType.FILE_TREE:
            return "file_tree"
        if detection.content_type is ContentType.SEARCH_RESULTS:
            return "search_results"
        if detection.content_type is ContentType.SOURCE_CODE:
            return "source_code"
        if detection.content_type is ContentType.BUILD_OUTPUT:
            return "test_log" if _TEST_LOG_RE.search(text) else "build_log"
        return "generic_tool_output"

    def _looks_like_source_code(self, text: str) -> bool:
        return detect_content_type(text).content_type is ContentType.SOURCE_CODE

    def _looks_like_package_metadata(self, text: str, filename: str = "") -> bool:
        basename = PurePath(filename.replace("\\", "/")).name.lower()
        if basename in _PACKAGE_FILENAMES or basename in _LOCKFILE_NAMES:
            return True
        stripped = text.lstrip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return False
            return isinstance(parsed, dict) and bool(
                {"name", "version", "scripts", *_DEPENDENCY_KEYS} & set(parsed)
            )
        lower = text[:4000].lower()
        return any(name in lower for name in _PACKAGE_FILENAMES)

    def _looks_like_mcp_tool_response(self, text: str, metadata: dict[str, Any]) -> bool:
        if metadata.get("mcp") or metadata.get("tool_name"):
            return True
        stripped = text.lstrip()
        if not stripped.startswith("{"):
            return False
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return False
        if not isinstance(parsed, dict):
            return False
        keys = set(parsed)
        return bool(
            {"tool", "tool_name", "arguments", "args", "result", "results", "status"} & keys
        )

    def _compress_log(
        self,
        source_type: str,
        text: str,
        metadata: dict[str, Any],
        context: str,
    ) -> CodingAgentPresetResult:
        from headroom.transforms.log_compressor import LogCompressor, LogCompressorConfig

        compressor = LogCompressor(
            LogCompressorConfig(
                enable_ccr=self.config.enable_ccr,
                min_lines_for_ccr=self.config.min_lines_for_ccr,
                max_total_lines=self.config.max_log_lines,
                max_warnings=4,
            )
        )
        result = compressor.compress(text, context=context)
        return self._result(
            compressed=result.compressed,
            original=text,
            source_type=source_type,
            compression_method="log_compressor",
            accuracy_guard="coding_agent_failure_evidence",
            extra_metadata={
                **metadata,
                "log_format": result.format_detected.value,
                "lines_omitted": result.lines_omitted,
                "stats": result.stats,
            },
        )

    def _compress_search(
        self,
        text: str,
        metadata: dict[str, Any],
        context: str,
    ) -> CodingAgentPresetResult:
        from headroom.transforms.search_compressor import SearchCompressor, SearchCompressorConfig

        query_lines = self._extract_query_lines(text, metadata)
        compressor = SearchCompressor(
            SearchCompressorConfig(
                enable_ccr=self.config.enable_ccr,
                min_matches_for_ccr=max(2, self.config.min_lines_for_ccr // 4),
                max_matches_per_file=self.config.max_search_matches_per_file,
                max_total_matches=self.config.max_search_matches,
                context_keywords=list(metadata.get("context_keywords", ())),
            )
        )
        result = compressor.compress(text, context=context or "\n".join(query_lines))
        compressed = self._prepend_missing_lines(result.compressed, query_lines)
        return self._result(
            compressed=compressed,
            original=text,
            source_type="search_results",
            compression_method="search_compressor",
            accuracy_guard="search_result_file_line_match_evidence",
            extra_metadata={
                **metadata,
                "files_affected": result.files_affected,
                "matches_omitted": result.matches_omitted,
                "summaries": result.summaries,
            },
        )

    def _compress_file_tree(
        self,
        text: str,
        metadata: dict[str, Any],
        context: str,
    ) -> CodingAgentPresetResult:
        from headroom.transforms.file_tree_compressor import (
            FileTreeCompressor,
            FileTreeCompressorConfig,
        )

        compressor = FileTreeCompressor(
            FileTreeCompressorConfig(
                enable_ccr=self.config.enable_ccr,
                min_lines_for_ccr=self.config.min_lines_for_ccr,
                max_lines=self.config.max_file_tree_lines,
            )
        )
        result = compressor.compress(text, context=context)
        return self._result(
            compressed=result.compressed,
            original=text,
            source_type="file_tree",
            compression_method="file_tree_compressor",
            accuracy_guard="edit_target_tree_evidence",
            extra_metadata={
                **metadata,
                "collapsed_directories": result.collapsed_directories,
                "omitted_line_count": result.omitted_line_count,
                "preserved_relevant_paths": result.preserved_relevant_paths,
            },
        )

    def _compress_diff(
        self,
        text: str,
        metadata: dict[str, Any],
        context: str,
    ) -> CodingAgentPresetResult:
        from headroom.transforms.diff_compressor import DiffCompressor

        result = DiffCompressor().compress(text, context=context)
        return self._result(
            compressed=result.compressed,
            original=text,
            source_type="git_diff",
            compression_method="diff_compressor",
            accuracy_guard="edit_target_diff_evidence",
            extra_metadata={
                **metadata,
                "files_affected": result.files_affected,
                "hunks_removed": result.hunks_removed,
                "additions": result.additions,
                "deletions": result.deletions,
            },
        )

    def _compress_package_metadata(
        self,
        source_type: str,
        text: str,
        metadata: dict[str, Any],
    ) -> CodingAgentPresetResult:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            compressed, omitted = self._compact_package_metadata_text(text)
        else:
            if isinstance(parsed, dict):
                compressed, omitted = self._compact_package_json(parsed, metadata)
            else:
                compressed, omitted = self._compact_package_metadata_text(text)

        compressed, ccr_hash, ccr_marker = self._append_ccr_if_needed(
            original=text,
            compressed=compressed,
            omitted_count=omitted,
            compression_strategy="coding_agent_package_metadata",
        )
        return self._result(
            compressed=compressed,
            original=text,
            source_type=source_type,
            compression_method="package_metadata_compactor",
            accuracy_guard="package_metadata_scripts_dependencies_toolchain",
            extra_metadata={**metadata, "omitted_items": omitted},
            explicit_ccr_hash=ccr_hash,
            explicit_ccr_marker=ccr_marker,
        )

    def _compact_package_json(
        self,
        parsed: dict[str, Any],
        metadata: dict[str, Any],
    ) -> tuple[str, int]:
        del metadata
        lines = ["package_metadata:"]
        omitted = 0
        for key in ("name", "version", "description"):
            if key in parsed:
                lines.append(f"{key}: {parsed[key]}")
        for key in _TOOLCHAIN_KEYS:
            if key in parsed:
                lines.append(f"{key}: {self._short_json(parsed[key])}")
        for key in _SCRIPT_KEYS:
            value = parsed.get(key)
            if isinstance(value, dict):
                lines.append(f"{key}:")
                for script_name, command in sorted(value.items()):
                    lines.append(f"- {script_name}: {command}")
            elif value is not None:
                lines.append(f"{key}: {self._short_json(value)}")
        for key in _DEPENDENCY_KEYS:
            value = parsed.get(key)
            if not isinstance(value, dict) or not value:
                continue
            names = sorted(str(name) for name in value)
            lines.append(f"{key} ({len(names)}): {', '.join(names)}")
        preserved_keys = {
            "name",
            "version",
            "description",
            *_TOOLCHAIN_KEYS,
            *_SCRIPT_KEYS,
            *_DEPENDENCY_KEYS,
        }
        omitted += max(0, len(set(parsed) - preserved_keys))
        return "\n".join(lines), omitted

    def _compact_package_metadata_text(self, text: str) -> tuple[str, int]:
        keep_patterns = (
            re.compile(r"^\s*(name|version|groupId|artifactId|package)\b", re.IGNORECASE),
            re.compile(r"^\s*(scripts|dependencies|devDependencies|workspaces|engines)\b"),
            re.compile(r"^\s*\[(project|tool|workspace|package|dependencies)", re.IGNORECASE),
            re.compile(r"^\s*(plugins|java|sourceCompatibility|targetCompatibility)\b"),
            re.compile(r"<(groupId|artifactId|version|dependency|plugin)>", re.IGNORECASE),
        )
        lines = []
        omitted = 0
        for line in text.splitlines():
            if any(pattern.search(line) for pattern in keep_patterns):
                lines.append(line.rstrip())
            else:
                omitted += 1
        if omitted:
            lines.append(f"[{omitted} package metadata lines omitted]")
        return "\n".join(lines) if lines else text, omitted

    def _compress_mcp_tool_response(
        self,
        source_type: str,
        text: str,
        metadata: dict[str, Any],
    ) -> CodingAgentPresetResult:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            compressed, omitted = self._compact_generic_lines(
                text,
                header="mcp_tool_response:",
            )
        else:
            if isinstance(parsed, dict):
                compressed, omitted = self._compact_mcp_json(parsed, metadata)
            else:
                compressed, omitted = self._compact_generic_lines(
                    text,
                    header="mcp_tool_response:",
                )

        compressed, ccr_hash, ccr_marker = self._append_ccr_if_needed(
            original=text,
            compressed=compressed,
            omitted_count=omitted,
            compression_strategy="coding_agent_mcp_tool_response",
        )
        return self._result(
            compressed=compressed,
            original=text,
            source_type=source_type,
            compression_method="mcp_tool_response_compactor",
            accuracy_guard="tool_response_status_error_results",
            extra_metadata={**metadata, "omitted_items": omitted},
            explicit_ccr_hash=ccr_hash,
            explicit_ccr_marker=ccr_marker,
        )

    def _compact_mcp_json(
        self,
        parsed: dict[str, Any],
        metadata: dict[str, Any],
    ) -> tuple[str, int]:
        tool_name = (
            parsed.get("tool")
            or parsed.get("tool_name")
            or parsed.get("name")
            or metadata.get("tool_name")
            or "unknown"
        )
        status = parsed.get("status") or parsed.get("state")
        raw_error = parsed.get("error")
        error = raw_error if raw_error is not None else None
        if error is None and parsed.get("status") == "error":
            error = parsed.get("message")
        if error is None and isinstance(parsed.get("error"), dict):
            error = self._short_json(parsed["error"])
        if status is None:
            status = "error" if error else "success"

        args = parsed.get("arguments", parsed.get("args", parsed.get("input")))
        results = self._extract_results(parsed)
        result_count = self._result_count(parsed, results)

        lines = [
            "mcp_tool_response:",
            f"tool: {tool_name}",
            f"status: {status}",
        ]
        if args is not None:
            lines.append(f"arguments: {self._short_json(args, limit=400)}")
        if error is not None:
            lines.append(f"error: {self._short_json(error, limit=500)}")
        lines.append(f"result_count: {result_count}")

        kept_results = results[: self.config.max_mcp_results]
        for index, item in enumerate(kept_results, start=1):
            lines.append(f"result[{index}]: {self._summarize_result_item(item)}")

        omitted = max(0, len(results) - len(kept_results))
        if omitted:
            lines.append(f"[{omitted} MCP result objects omitted]")
        extra_omitted = max(
            0,
            len(
                set(parsed)
                - {
                    "tool",
                    "tool_name",
                    "name",
                    "status",
                    "state",
                    "arguments",
                    "args",
                    "input",
                    "results",
                    "result",
                    "content",
                    "count",
                    "total",
                    "error",
                    "message",
                }
            ),
        )
        omitted += extra_omitted
        return "\n".join(lines), omitted

    def _extract_results(self, parsed: dict[str, Any]) -> list[Any]:
        for key in ("results", "items", "content"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
        value = parsed.get("result")
        if isinstance(value, list):
            return value
        if value is not None:
            return [value]
        return []

    def _result_count(self, parsed: dict[str, Any], results: list[Any]) -> int:
        for key in ("count", "total", "result_count"):
            value = parsed.get(key)
            if isinstance(value, int):
                return value
        return len(results)

    def _summarize_result_item(self, item: Any) -> str:
        if not isinstance(item, dict):
            return self._short_json(item, limit=400)
        parts: list[str] = []
        for key in ("path", "file", "uri", "resource_id", "id", "status", "error", "message"):
            if key in item:
                parts.append(f"{key}={self._short_json(item[key], limit=160)}")
        if not parts:
            for key, value in list(item.items())[:5]:
                parts.append(f"{key}={self._short_json(value, limit=120)}")
        paths = sorted({match.group(0) for match in _JSON_PATH_RE.finditer(self._short_json(item))})
        if paths:
            parts.append("paths=" + ", ".join(paths[:3]))
        return "; ".join(parts)

    def _compress_generic_tool_output(
        self,
        source_type: str,
        text: str,
        metadata: dict[str, Any],
    ) -> CodingAgentPresetResult:
        if self._looks_like_source_code(text):
            return self._passthrough_source_code(text, metadata)
        compressed, omitted = self._compact_generic_lines(text, header="generic_tool_output:")
        compressed, ccr_hash, ccr_marker = self._append_ccr_if_needed(
            original=text,
            compressed=compressed,
            omitted_count=omitted,
            compression_strategy="coding_agent_generic_tool_output",
        )
        return self._result(
            compressed=compressed,
            original=text,
            source_type=source_type,
            compression_method="generic_tool_output_compactor",
            accuracy_guard="generic_tool_error_path_status_evidence",
            extra_metadata={**metadata, "omitted_items": omitted},
            explicit_ccr_hash=ccr_hash,
            explicit_ccr_marker=ccr_marker,
        )

    def _compact_generic_lines(self, text: str, *, header: str) -> tuple[str, int]:
        lines = text.splitlines()
        output = [header, f"original_lines: {len(lines)}"]
        omitted = 0
        seen_counts: dict[str, int] = {}
        kept_indexes: set[int] = set()

        for index, line in enumerate(lines[: self.config.generic_leading_lines]):
            output.append(line.rstrip())
            kept_indexes.add(index)

        for index, line in enumerate(lines):
            stripped = line.rstrip()
            normalized = re.sub(r"\d+", "N", stripped)
            seen_counts[normalized] = seen_counts.get(normalized, 0) + 1
            if index in kept_indexes:
                continue
            if self._is_generic_evidence_line(stripped):
                output.append(stripped)
                kept_indexes.add(index)
            elif _PROGRESS_RE.match(stripped):
                omitted += 1

        for normalized, count in sorted(seen_counts.items()):
            if count > 3 and len(output) < self.config.max_generic_lines:
                output.append(f"[line repeated {count} times: {normalized[:120]}]")

        if len(output) > self.config.max_generic_lines:
            omitted += len(output) - self.config.max_generic_lines
            output = output[: self.config.max_generic_lines]

        omitted += max(0, len(lines) - len(kept_indexes) - omitted)
        if omitted > 0:
            output.append(f"[{omitted} generic tool output lines omitted]")
        return "\n".join(output), omitted

    def _is_generic_evidence_line(self, line: str) -> bool:
        return bool(
            _COMMAND_RE.search(line)
            or _STATUS_RE.search(line)
            or _ERROR_RE.search(line)
            or _WARN_RE.search(line)
            or _FILE_LINE_RE.search(line)
        )

    def _passthrough_source_code(
        self,
        text: str,
        metadata: dict[str, Any],
    ) -> CodingAgentPresetResult:
        return self._result(
            compressed=text,
            original=text,
            source_type="source_code",
            compression_method="source_code_passthrough",
            accuracy_guard="source_code_not_blindly_compressed",
            extra_metadata={**metadata, "bypass_reason": "source_code_preserved_verbatim"},
        )

    def _extract_query_lines(self, text: str, metadata: dict[str, Any]) -> list[str]:
        query_lines: list[str] = []
        command = metadata.get("command") or metadata.get("query")
        if command:
            query_lines.append(str(command))
        for line in text.splitlines()[:5]:
            stripped = line.strip()
            if re.match(r"^(?:\$|>)?\s*(?:rg|grep|ripgrep)\b", stripped):
                query_lines.append(line.rstrip())
        deduped: list[str] = []
        for line in query_lines:
            if line and line not in deduped:
                deduped.append(line)
        return deduped

    def _prepend_missing_lines(self, compressed: str, lines: list[str]) -> str:
        prefix = [line for line in lines if line not in compressed]
        if not prefix:
            return compressed
        return "\n".join([*prefix, compressed])

    def _append_ccr_if_needed(
        self,
        *,
        original: str,
        compressed: str,
        omitted_count: int,
        compression_strategy: str,
    ) -> tuple[str, str | None, str | None]:
        if (
            not self.config.enable_ccr
            or omitted_count <= 0
            or len(original) < self.config.min_chars_for_ccr
            or len(original.splitlines()) < self.config.min_lines_for_ccr
            or len(compressed) >= len(original)
        ):
            return compressed, None, None

        cache_key = hashlib.sha256(original.encode()).hexdigest()[:24]
        original_lines = len(original.splitlines())
        compressed_lines = len(compressed.splitlines()) + 1
        marker = (
            f"[{original_lines} lines compressed to {compressed_lines}. "
            f"Retrieve more: hash={cache_key}]"
        )
        final = f"{compressed.rstrip()}\n{marker}"
        try:
            from headroom.cache.compression_store import get_compression_store

            get_compression_store().store(
                original,
                final,
                original_item_count=original_lines,
                compressed_item_count=compressed_lines,
                explicit_hash=cache_key,
                compression_strategy=compression_strategy,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("CCR store write failed for %s: %s", compression_strategy, exc)
        return final, cache_key, marker

    def _result(
        self,
        *,
        compressed: str,
        original: str,
        source_type: str,
        compression_method: str,
        accuracy_guard: str,
        extra_metadata: dict[str, Any],
        explicit_ccr_hash: str | None = None,
        explicit_ccr_marker: str | None = None,
    ) -> CodingAgentPresetResult:
        ccr_marker = explicit_ccr_marker
        ccr_hash = explicit_ccr_hash
        if ccr_hash is None:
            markers = parse_ccr_markers(compressed)
            if markers:
                marker = markers[-1]
                ccr_hash = marker.hash
                ccr_marker = marker.raw

        result_metadata = {
            "source_type": source_type,
            "compression_method": compression_method,
            "accuracy_guard": accuracy_guard,
            "original_length": len(original),
            "compressed_length": len(compressed),
            "saved_length": max(0, len(original) - len(compressed)),
            "original_tokens": len(original.split()),
            "compressed_tokens": len(compressed.split()),
            "ccr_hash": ccr_hash,
            **extra_metadata,
        }
        return CodingAgentPresetResult(
            compressed=compressed,
            original=original,
            source_type=source_type,
            compression_method=compression_method,
            accuracy_guard=accuracy_guard,
            original_length=len(original),
            compressed_length=len(compressed),
            ccr_hash=ccr_hash,
            ccr_marker=ccr_marker,
            metadata=result_metadata,
        )

    def _emit_ledger_event(
        self,
        result: CodingAgentPresetResult,
        request_metadata: dict[str, Any],
    ) -> None:
        try:
            from headroom.telemetry.ledger import (
                TOKEN_COUNT_METHOD,
                LedgerEvent,
                estimate_tokens,
                get_ledger_emitter,
            )

            emitter = self._ledger_emitter or get_ledger_emitter()
            original_tokens = int(
                result.metadata.get("original_tokens") or estimate_tokens(result.original)
            )
            compressed_tokens = int(
                result.metadata.get("compressed_tokens") or estimate_tokens(result.compressed)
            )
            saved_tokens = max(0, original_tokens - compressed_tokens)
            event_type = (
                "bridge.compression.bypassed"
                if result.compression_method == "source_code_passthrough" or saved_tokens == 0
                else "bridge.compression.completed"
            )
            emitter.emit(
                LedgerEvent.create(
                    event_type,
                    source_id=str(
                        request_metadata.get("source_id")
                        or result.metadata.get("source_id")
                        or (
                            f"{result.source_type}:"
                            f"{hashlib.sha256(result.original.encode()).hexdigest()[:16]}"
                        )
                    ),
                    source_type=result.source_type,
                    source_path=request_metadata.get("source_path")
                    or request_metadata.get("path")
                    or request_metadata.get("filename"),
                    provider=request_metadata.get("provider"),
                    model=request_metadata.get("model"),
                    provider_request_id=request_metadata.get("provider_request_id"),
                    turn_id=request_metadata.get("turn_id"),
                    cache_zone=request_metadata.get("cache_zone"),
                    original_tokens=original_tokens,
                    compressed_tokens=compressed_tokens,
                    saved_tokens=saved_tokens,
                    token_count_method=TOKEN_COUNT_METHOD,
                    compression_method=result.compression_method,
                    ccr_marker_id=result.ccr_hash,
                    ccr_backend="local" if result.ccr_hash else None,
                    accuracy_guard=result.accuracy_guard,
                    attributes={
                        "original_length": result.original_length,
                        "compressed_length": result.compressed_length,
                        "saved_length": result.saved_length,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ledger emission failed for %s: %s", result.source_type, exc)

    def _short_json(self, value: Any, *, limit: int = 240) -> str:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if len(text) <= limit:
            return text
        return text[: limit - 15].rstrip() + " ...[truncated]"


__all__ = [
    "CodingAgentPreset",
    "CodingAgentPresetConfig",
    "CodingAgentPresetResult",
]
