"""File-tree compressor for repository listings.

This compressor targets `tree`, `find`, `git ls-files`, and status-prefixed
path listings. It keeps the repository shape a coding agent needs while
collapsing generated/cache subtrees such as node_modules, vendor, dist, build,
coverage, and cache directories.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_TREE_BRANCH_RE = re.compile(
    r"^(?P<prefix>(?:\|   |    )*)(?P<marker>\|--|\+--|`--)\s+(?P<name>.+)$"
)
_STATUS_PATH_RE = re.compile(
    r"^\s*(?:[MADRCU?!]{1,2}\s+)?(?P<path>(?:\.?[\\/])?[^\s:]+(?:[\\/][^\s:]+)+/?)\s*$"
)
_CONTEXT_PATH_RE = re.compile(
    r"(?:[A-Za-z0-9_.@+-]+[\\/]){1,}[A-Za-z0-9_.@+-]+(?:\.[A-Za-z0-9_.@+-]+)?"
)


def _default_collapse_dirs() -> tuple[str, ...]:
    return (
        ".cache",
        ".git",
        ".next",
        ".pytest_cache",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "target",
        "vendor",
    )


def _default_important_files() -> tuple[str, ...]:
    return (
        ".dockerignore",
        ".env.example",
        ".gitignore",
        "Cargo.toml",
        "Dockerfile",
        "Makefile",
        "README.md",
        "compose.yaml",
        "docker-compose.yml",
        "go.mod",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "pom.xml",
        "pyproject.toml",
        "requirements.txt",
        "tsconfig.json",
        "uv.lock",
        "yarn.lock",
    )


def _default_source_dirs() -> tuple[str, ...]:
    return (
        ".github",
        "app",
        "cmd",
        "components",
        "crates",
        "docs",
        "headroom",
        "internal",
        "lib",
        "packages",
        "src",
        "test",
        "tests",
    )


@dataclass
class FileTreeCompressorConfig:
    """Configuration for file-tree compression."""

    max_lines: int = 120
    max_depth: int = 4
    enable_ccr: bool = True
    min_lines_for_ccr: int = 50
    collapse_dirs: tuple[str, ...] = field(default_factory=_default_collapse_dirs)
    important_files: tuple[str, ...] = field(default_factory=_default_important_files)
    source_dirs: tuple[str, ...] = field(default_factory=_default_source_dirs)


@dataclass
class FileTreeCompressionResult:
    """Result of file-tree compression."""

    compressed: str
    original: str
    original_line_count: int
    compressed_line_count: int
    collapsed_directories: int
    omitted_line_count: int
    preserved_relevant_paths: int
    cache_key: str | None = None

    @property
    def compression_ratio(self) -> float:
        if self.original_line_count == 0:
            return 1.0
        return self.compressed_line_count / self.original_line_count

    @property
    def tokens_saved_estimate(self) -> int:
        chars_saved = len(self.original) - len(self.compressed)
        return max(0, chars_saved // 4)


@dataclass(frozen=True)
class _TreeLine:
    original: str
    depth: int
    path: str
    name: str
    components: tuple[str, ...]
    is_dir: bool


class FileTreeCompressor:
    """Compress repository file-tree listings without external dependencies."""

    def __init__(self, config: FileTreeCompressorConfig | None = None) -> None:
        self.config = config or FileTreeCompressorConfig()
        self._collapse_dirs = {d.lower() for d in self.config.collapse_dirs}
        self._important_files = {f.lower() for f in self.config.important_files}
        self._source_dirs = {d.lower() for d in self.config.source_dirs}

    def compress(self, content: str, context: str = "") -> FileTreeCompressionResult:
        lines = content.splitlines()
        if not lines:
            return FileTreeCompressionResult(
                compressed=content,
                original=content,
                original_line_count=0,
                compressed_line_count=0,
                collapsed_directories=0,
                omitted_line_count=0,
                preserved_relevant_paths=0,
                cache_key=None,
            )

        relevant_paths = self._extract_relevant_paths(context + "\n" + content)
        parsed = self._parse_lines(lines)
        output: list[str] = []
        omitted = 0
        collapsed_count = 0
        collapsed_roots: set[str] = set()
        preserved_relevant = 0
        skip_tree_depth: int | None = None

        for item in parsed:
            if skip_tree_depth is not None:
                if item.depth > skip_tree_depth:
                    omitted += 1
                    continue
                skip_tree_depth = None

            collapse_component = self._collapse_component(item.components)
            if collapse_component and not self._matches_relevant_path(item.path, relevant_paths):
                collapse_root = self._collapse_root(item.components, collapse_component)
                if collapse_root not in collapsed_roots:
                    output.append(self._collapse_summary(item, collapse_component))
                    collapsed_roots.add(collapse_root)
                    collapsed_count += 1
                omitted += 1
                if item.is_dir:
                    skip_tree_depth = item.depth
                continue

            keep_for_relevance = self._matches_relevant_path(item.path, relevant_paths)
            keep = keep_for_relevance or self._is_structural_keep(item)
            if keep and len(output) < self.config.max_lines:
                output.append(item.original)
                if keep_for_relevance:
                    preserved_relevant += 1
            else:
                omitted += 1

        if omitted > 0:
            output.append(f"[{omitted} file-tree lines omitted]")

        compressed = "\n".join(output)
        cache_key: str | None = None
        if (
            self.config.enable_ccr
            and omitted > 0
            and len(lines) >= self.config.min_lines_for_ccr
            and len(compressed) < len(content)
        ):
            cache_key = hashlib.sha256(content.encode()).hexdigest()[:24]
            marker = (
                f"[{len(lines)} lines compressed to {len(output) + 1}. "
                f"Retrieve more: hash={cache_key}]"
            )
            compressed = f"{compressed}\n{marker}"
            output.append(marker)
            self._persist_to_python_ccr(content, compressed, cache_key)

        return FileTreeCompressionResult(
            compressed=compressed,
            original=content,
            original_line_count=len(lines),
            compressed_line_count=len(output),
            collapsed_directories=collapsed_count,
            omitted_line_count=omitted,
            preserved_relevant_paths=preserved_relevant,
            cache_key=cache_key,
        )

    def _parse_lines(self, lines: list[str]) -> list[_TreeLine]:
        parsed: list[_TreeLine] = []
        tree_stack: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                parsed.append(
                    _TreeLine(line, 0, "", "", (), False),
                )
                continue

            if stripped in {".", "./"}:
                tree_stack = []
                parsed.append(_TreeLine(line, 0, ".", ".", (), True))
                continue

            branch = _TREE_BRANCH_RE.match(line)
            if branch:
                prefix = branch.group("prefix")
                depth = (len(prefix) // 4) + 1
                name = branch.group("name").strip()
                clean_name = name.rstrip("/")
                is_dir = name.endswith("/")
                tree_stack = tree_stack[: max(0, depth - 1)]
                components = (*tree_stack, clean_name)
                tree_stack = [*tree_stack, clean_name] if is_dir else tree_stack
                parsed.append(
                    _TreeLine(
                        original=line,
                        depth=depth,
                        path="/".join(components),
                        name=clean_name,
                        components=components,
                        is_dir=is_dir,
                    )
                )
                continue

            path_match = _STATUS_PATH_RE.match(line)
            if path_match:
                raw_path = path_match.group("path")
                components = self._split_path(raw_path)
                parsed.append(
                    _TreeLine(
                        original=line,
                        depth=max(0, len(components) - 1),
                        path="/".join(components),
                        name=components[-1] if components else stripped,
                        components=components,
                        is_dir=raw_path.endswith(("/", "\\")),
                    )
                )
                continue

            parsed.append(_TreeLine(line, 0, stripped, stripped, (stripped,), False))

        return parsed

    def _extract_relevant_paths(self, text: str) -> set[str]:
        paths: set[str] = set()
        for match in _CONTEXT_PATH_RE.finditer(text):
            components = self._split_path(match.group(0))
            if len(components) >= 2:
                paths.add("/".join(components))
        return paths

    def _split_path(self, path: str) -> tuple[str, ...]:
        normalized = path.strip().replace("\\", "/")
        normalized = normalized.removeprefix("./").removeprefix("/")
        normalized = normalized.removeprefix("a/").removeprefix("b/")
        return tuple(part for part in normalized.strip("/").split("/") if part)

    def _collapse_component(self, components: tuple[str, ...]) -> str | None:
        for component in components:
            if component.lower() in self._collapse_dirs:
                return component
        return None

    def _collapse_root(self, components: tuple[str, ...], component: str) -> str:
        index = components.index(component)
        return "/".join(components[: index + 1])

    def _collapse_summary(self, item: _TreeLine, component: str) -> str:
        indent = self._tree_indent(item.original)
        return f"{indent}[{component}/ omitted generated/cache subtree]"

    def _tree_indent(self, line: str) -> str:
        branch = _TREE_BRANCH_RE.match(line)
        if branch:
            return branch.group("prefix")
        leading = len(line) - len(line.lstrip())
        return " " * leading

    def _is_structural_keep(self, item: _TreeLine) -> bool:
        if item.path in {"", "."}:
            return True
        lower_components = {component.lower() for component in item.components}
        lower_name = item.name.lower()
        if item.depth <= self.config.max_depth:
            if lower_components & self._source_dirs:
                return True
            if lower_name in self._important_files:
                return True
            if item.is_dir and item.depth <= 2:
                return True
        if lower_name in self._important_files:
            return True
        return False

    def _matches_relevant_path(self, path: str, relevant_paths: set[str]) -> bool:
        if not path or not relevant_paths:
            return False
        normalized = "/".join(self._split_path(path))
        if not normalized:
            return False
        for relevant in relevant_paths:
            if (
                normalized == relevant
                or normalized.startswith(relevant + "/")
                or relevant.startswith(normalized + "/")
            ):
                return True
        return False

    def _persist_to_python_ccr(self, original: str, compressed: str, cache_key: str) -> None:
        """Persist omitted file-tree content through the local CCR store."""
        try:
            from ..cache.compression_store import get_compression_store
        except ImportError as e:
            logger.warning("CCR store import failed; cache_key %s won't persist: %s", cache_key, e)
            return
        try:
            store: Any = get_compression_store()
            store.store(
                original,
                compressed,
                original_item_count=len(original.splitlines()),
                explicit_hash=cache_key,
                compression_strategy="file_tree",
            )
        except Exception as e:
            logger.warning(
                "CCR store write failed; cache_key %s remains in-marker only: %s",
                cache_key,
                e,
            )


__all__ = [
    "FileTreeCompressor",
    "FileTreeCompressorConfig",
    "FileTreeCompressionResult",
]
