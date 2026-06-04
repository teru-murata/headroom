"""Deterministic cache-aware compression net-savings model.

This module is intentionally local and estimate-based. It helps Headroom decide
whether compression is likely useful after provider prefix-cache effects and CCR
retrieval costs are considered. It is not a hosted ROI surface and it is not a
billing-grade provider pricing catalog.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from headroom.telemetry.ledger import LedgerEvent, get_ledger_emitter

CacheZone = Literal[
    "protected_prefix",
    "stable_prefix",
    "volatile_tail",
    "live_tool_output",
    "unknown",
]
Decision = Literal[
    "compress",
    "skip_preserve_cache",
    "bypass_protected_prefix",
    "bypass_accuracy_guard",
    "insufficient_signal",
]
Confidence = Literal["low", "medium", "high"]

CACHE_ZONES: tuple[CacheZone, ...] = (
    "protected_prefix",
    "stable_prefix",
    "volatile_tail",
    "live_tool_output",
    "unknown",
)
DECISIONS: tuple[Decision, ...] = (
    "compress",
    "skip_preserve_cache",
    "bypass_protected_prefix",
    "bypass_accuracy_guard",
    "insufficient_signal",
)

_LIVE_SOURCE_TYPES = {
    "tool_definitions",
    "mcp_schemas",
    "tool_outputs",
    "build_logs",
    "test_logs",
    "test_log",
    "build_log",
    "search_results",
    "file_reads",
    "file_trees",
    "file_tree",
    "git_diffs",
    "git_diff",
    "rag_chunks",
    "api_db_responses",
    "ccr_retrievals",
    "sandbox_artifacts",
    "mcp_tool_response",
    "generic_tool_output",
    "api_db_response",
}
_PROTECTED_ROLES = {"system", "developer"}
_VOLATILE_HINTS = {"tail", "latest", "current_turn", "volatile_tail", "live_zone"}
_LIVE_TEXT_RE = re.compile(
    r"(?m)(^\s*(?:\$|>)\s*(?:python -m pytest|pytest|npm|pnpm|cargo|go test|mvn)\b|"
    r"^diff --git\b|^@@\s+-\d+,\d+\s+\+\d+,\d+\s+@@|"
    r"\b(?:FAILED tests/|BUILD FAILURE|exit code:|Traceback \(most recent call last\))\b|"
    r"^\s*(?:\|--|`--|\+-{2}))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PricingConfig:
    """Caller-supplied local pricing estimate.

    Prices are per million tokens. They are optional benchmark inputs, not a
    production provider catalog.
    """

    input_token_price_per_million: float
    cached_token_price_per_million: float | None = None
    output_token_price_per_million: float | None = None


@dataclass(frozen=True)
class NetSavingsInput:
    """Inputs used by the deterministic net-savings decision model."""

    original_tokens_estimated: int
    compressed_tokens_estimated: int
    cache_zone: CacheZone = "unknown"
    provider_cached_tokens: int = 0
    provider_cache_reads: int = 0
    cache_miss_penalty_tokens_estimated: int | None = None
    stable_prefix_tokens_estimated: int | None = None
    cache_miss_penalty_multiplier: float = 1.0
    latency_ms: int | None = None
    compression_latency_ms: int | None = None
    pricing: PricingConfig | dict[str, float | None] | None = None
    ccr_marker_present: bool = False
    ccr_retrieve_rate_estimate: float = 0.1
    ccr_retrieve_cost_tokens_estimated: int | None = None
    retrieved_count: int | None = None
    task_accuracy_guard_passed: bool | None = None
    compression_method: str | None = None
    source_type: str | None = None
    accuracy_guard: str | None = None

    @property
    def saved_tokens_estimated(self) -> int:
        return max(0, self.original_tokens_estimated - self.compressed_tokens_estimated)


@dataclass(frozen=True)
class NetSavingsDecision:
    """Decision output for cache-aware compress-vs-skip logic."""

    decision: Decision
    reason: str
    gross_saved_tokens_estimated: int
    cache_miss_penalty_tokens_estimated: int
    ccr_retrieve_cost_tokens_estimated: int
    net_saved_tokens_estimated: int
    estimated_cost_before: float | None
    estimated_cost_after: float | None
    estimated_net_savings: float | None
    confidence: Confidence
    warnings: list[str] = field(default_factory=list)
    cache_zone: CacheZone = "unknown"
    source_type: str | None = None
    compression_method: str | None = None
    ledger_event_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_cache_zone(
    text: str,
    *,
    source_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> CacheZone:
    """Classify a local source item for cache-aware compression decisions."""

    metadata = metadata or {}
    explicit_zone = _normalize_cache_zone(metadata.get("cache_zone"))
    if explicit_zone is not None:
        return explicit_zone

    role = str(metadata.get("role") or metadata.get("message_role") or "").strip().lower()
    if role in _PROTECTED_ROLES or bool(metadata.get("protected_prefix")):
        return "protected_prefix"

    position = str(metadata.get("position") or metadata.get("zone") or "").strip().lower()
    if position in _VOLATILE_HINTS:
        return "volatile_tail"

    if (
        metadata.get("stable_prefix_hash")
        or metadata.get("prefix_hash")
        or metadata.get("is_stable_prefix")
        or metadata.get("cacheable_prefix")
        or _positive_int(metadata.get("provider_cached_tokens")) > 0
    ):
        return "stable_prefix"

    normalized_source = _normalize_source_type(source_type or metadata.get("source_type") or "")
    if normalized_source in _LIVE_SOURCE_TYPES:
        return "live_tool_output"

    head = text[:400].lstrip().lower()
    if head.startswith(("system:", "developer:", "<system>", "<developer>")):
        return "protected_prefix"
    if _LIVE_TEXT_RE.search(text[:8000]):
        return "live_tool_output"

    return "unknown"


def estimate_cache_miss_penalty(inputs: NetSavingsInput) -> int:
    """Estimate local token penalty from losing provider prefix cacheability."""

    if inputs.cache_miss_penalty_tokens_estimated is not None:
        return max(0, int(inputs.cache_miss_penalty_tokens_estimated))

    cached = max(0, int(inputs.provider_cached_tokens))
    stable = max(0, int(inputs.stable_prefix_tokens_estimated or 0))
    basis = cached or stable or max(0, int(inputs.original_tokens_estimated))
    multiplier = max(0.0, float(inputs.cache_miss_penalty_multiplier))

    if inputs.cache_zone == "protected_prefix":
        return int(max(basis, inputs.original_tokens_estimated) * max(multiplier, 4.0))
    if inputs.cache_zone == "stable_prefix":
        return int(basis * multiplier)
    if inputs.cache_zone == "unknown":
        return int(basis * 0.25 * multiplier)
    if inputs.cache_zone == "volatile_tail":
        return int(cached * 0.05 * multiplier)
    return 0


def estimate_ccr_retrieve_cost(inputs: NetSavingsInput) -> int:
    """Estimate token cost from expected CCR retrievals."""

    if inputs.ccr_retrieve_cost_tokens_estimated is not None:
        return max(0, int(inputs.ccr_retrieve_cost_tokens_estimated))
    if not inputs.ccr_marker_present:
        return 0
    if inputs.retrieved_count is not None:
        return max(0, int(inputs.original_tokens_estimated * inputs.retrieved_count))
    rate = max(0.0, float(inputs.ccr_retrieve_rate_estimate))
    return int(inputs.original_tokens_estimated * rate)


def compute_net_savings_decision(inputs: NetSavingsInput) -> NetSavingsDecision:
    """Return a deterministic cache-aware compression decision."""

    cache_zone = _normalize_cache_zone(inputs.cache_zone) or "unknown"
    normalized_inputs = _replace_cache_zone(inputs, cache_zone)
    gross_saved = normalized_inputs.saved_tokens_estimated
    cache_penalty = estimate_cache_miss_penalty(normalized_inputs)
    ccr_cost = estimate_ccr_retrieve_cost(normalized_inputs)
    net_saved = gross_saved - cache_penalty - ccr_cost
    pricing = _coerce_pricing(normalized_inputs.pricing)
    cost_before, cost_after, cost_net = _estimate_costs(
        normalized_inputs,
        pricing,
        cache_penalty,
        ccr_cost,
    )
    warnings = _build_warnings(normalized_inputs, pricing)

    if cache_zone == "protected_prefix":
        decision: Decision = "bypass_protected_prefix"
        reason = "protected prefix content is never rewritten by local compression"
    elif normalized_inputs.task_accuracy_guard_passed is False:
        decision = "bypass_accuracy_guard"
        reason = "accuracy guard failed or critical evidence was missing"
    elif cache_zone == "stable_prefix":
        threshold = _clear_positive_threshold(
            cache_zone,
            normalized_inputs.original_tokens_estimated,
        )
        if gross_saved > 0 and net_saved > threshold:
            decision = "compress"
            reason = "stable prefix net savings exceeded cache miss penalty by a clear margin"
        else:
            decision = "skip_preserve_cache"
            reason = "preserving provider prefix cacheability is estimated to be more valuable"
    elif cache_zone in {"volatile_tail", "live_tool_output"}:
        if gross_saved > 0 and net_saved > 0:
            decision = "compress"
            reason = "volatile or live output has positive estimated net token savings"
        else:
            decision = "insufficient_signal"
            reason = "compression did not produce positive net savings after penalties"
    else:
        threshold = _clear_positive_threshold(
            cache_zone, normalized_inputs.original_tokens_estimated
        )
        if gross_saved > 0 and net_saved > threshold:
            decision = "compress"
            reason = "unknown source had a clearly positive estimated net-savings signal"
        else:
            decision = "insufficient_signal"
            reason = "unknown source is kept conservative without a clear net-savings signal"

    confidence = _confidence(
        decision=decision,
        cache_zone=cache_zone,
        net_saved=net_saved,
        original_tokens=normalized_inputs.original_tokens_estimated,
        task_accuracy_guard_passed=normalized_inputs.task_accuracy_guard_passed,
    )
    ledger_fields = _ledger_event_fields(
        inputs=normalized_inputs,
        decision=decision,
        reason=reason,
        gross_saved=gross_saved,
        cache_penalty=cache_penalty,
        ccr_cost=ccr_cost,
        net_saved=net_saved,
        warnings=warnings,
    )

    return NetSavingsDecision(
        decision=decision,
        reason=reason,
        gross_saved_tokens_estimated=gross_saved,
        cache_miss_penalty_tokens_estimated=cache_penalty,
        ccr_retrieve_cost_tokens_estimated=ccr_cost,
        net_saved_tokens_estimated=net_saved,
        estimated_cost_before=cost_before,
        estimated_cost_after=cost_after,
        estimated_net_savings=cost_net,
        confidence=confidence,
        warnings=warnings,
        cache_zone=cache_zone,
        source_type=normalized_inputs.source_type,
        compression_method=normalized_inputs.compression_method,
        ledger_event_fields=ledger_fields,
    )


def emit_decision_ledger_event(
    decision: NetSavingsDecision,
    *,
    emitter: Any | None = None,
    **overrides: Any,
) -> LedgerEvent:
    """Emit a H007-compatible ledger event for a net-savings decision."""

    fields = {**decision.ledger_event_fields, **overrides}
    event_type = str(fields.pop("event_type"))
    attributes = dict(fields.pop("attributes", {}))
    event = LedgerEvent.create(event_type, attributes=attributes, **fields)
    selected_emitter = emitter or get_ledger_emitter()
    return selected_emitter.emit(event)


def _ledger_event_fields(
    *,
    inputs: NetSavingsInput,
    decision: Decision,
    reason: str,
    gross_saved: int,
    cache_penalty: int,
    ccr_cost: int,
    net_saved: int,
    warnings: list[str],
) -> dict[str, Any]:
    compressed_tokens = (
        inputs.compressed_tokens_estimated
        if decision == "compress"
        else inputs.original_tokens_estimated
    )
    saved_tokens = gross_saved if decision == "compress" else 0
    compression_method = (
        inputs.compression_method
        if decision == "compress"
        else "skip_preserve_cache"
        if decision == "skip_preserve_cache"
        else decision
    )
    return {
        "event_type": "bridge.compression.completed"
        if decision == "compress"
        else "bridge.compression.bypassed",
        "source_type": inputs.source_type,
        "cache_zone": inputs.cache_zone,
        "original_tokens": inputs.original_tokens_estimated,
        "compressed_tokens": compressed_tokens,
        "saved_tokens": saved_tokens,
        "compression_method": compression_method,
        "accuracy_guard": inputs.accuracy_guard,
        "attributes": {
            "decision": decision,
            "reason": reason,
            "gross_saved_tokens_estimated": gross_saved,
            "cache_miss_penalty_tokens_estimated": cache_penalty,
            "ccr_retrieve_cost_tokens_estimated": ccr_cost,
            "net_saved_tokens_estimated": net_saved,
            "warnings": warnings,
        },
    }


def _estimate_costs(
    inputs: NetSavingsInput,
    pricing: PricingConfig | None,
    cache_penalty: int,
    ccr_cost: int,
) -> tuple[float | None, float | None, float | None]:
    if pricing is None:
        return None, None, None

    input_price = max(0.0, float(pricing.input_token_price_per_million))
    cached_price = (
        max(0.0, float(pricing.cached_token_price_per_million))
        if pricing.cached_token_price_per_million is not None
        else input_price
    )
    original = max(0, int(inputs.original_tokens_estimated))
    compressed = max(0, int(inputs.compressed_tokens_estimated))
    cached = min(original, max(0, int(inputs.provider_cached_tokens)))
    uncached = max(0, original - cached)
    before = ((uncached * input_price) + (cached * cached_price)) / 1_000_000
    after_tokens = compressed + cache_penalty + ccr_cost
    after = (after_tokens * input_price) / 1_000_000
    return before, after, before - after


def _build_warnings(inputs: NetSavingsInput, pricing: PricingConfig | None) -> list[str]:
    warnings: list[str] = []
    if pricing is None:
        warnings.append("provider cost estimate was not computed because pricing was not supplied")
    if inputs.task_accuracy_guard_passed is None:
        warnings.append("accuracy guard signal was unavailable")
    if inputs.provider_cache_reads < 0:
        warnings.append("provider cache reads were negative and ignored by the model")
    return warnings


def _confidence(
    *,
    decision: Decision,
    cache_zone: CacheZone,
    net_saved: int,
    original_tokens: int,
    task_accuracy_guard_passed: bool | None,
) -> Confidence:
    if task_accuracy_guard_passed is None and decision == "compress":
        return "low"
    if decision in {"bypass_protected_prefix", "bypass_accuracy_guard"}:
        return "high"
    if decision == "skip_preserve_cache" and cache_zone == "stable_prefix":
        return "high"
    if decision == "compress":
        if net_saved >= max(512, int(original_tokens * 0.4)):
            return "high"
        return "medium"
    return "low"


def _clear_positive_threshold(cache_zone: CacheZone, original_tokens: int) -> int:
    if cache_zone == "stable_prefix":
        return max(128, int(original_tokens * 0.15))
    if cache_zone == "unknown":
        return max(128, int(original_tokens * 0.20))
    return 0


def _coerce_pricing(value: PricingConfig | dict[str, float | None] | None) -> PricingConfig | None:
    if value is None:
        return None
    if isinstance(value, PricingConfig):
        return value
    return PricingConfig(
        input_token_price_per_million=float(value["input_token_price_per_million"] or 0.0),
        cached_token_price_per_million=(
            None
            if value.get("cached_token_price_per_million") is None
            else float(value["cached_token_price_per_million"] or 0.0)
        ),
        output_token_price_per_million=(
            None
            if value.get("output_token_price_per_million") is None
            else float(value["output_token_price_per_million"] or 0.0)
        ),
    )


def _normalize_cache_zone(value: Any) -> CacheZone | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in CACHE_ZONES:
        return normalized  # type: ignore[return-value]
    if normalized in {"live_zone", "tool_output", "tool_result"}:
        return "live_tool_output"
    if normalized in {"prefix", "cached_prefix"}:
        return "stable_prefix"
    if normalized in {"tail", "latest_turn"}:
        return "volatile_tail"
    return None


def _normalize_source_type(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return ""
    try:
        from headroom.benchmarks.context_waste.taxonomy import normalize_source_type

        return normalize_source_type(normalized)
    except ValueError:
        return normalized


def _replace_cache_zone(inputs: NetSavingsInput, cache_zone: CacheZone) -> NetSavingsInput:
    if inputs.cache_zone == cache_zone:
        return inputs
    return NetSavingsInput(**{**asdict(inputs), "cache_zone": cache_zone})


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "CACHE_ZONES",
    "DECISIONS",
    "CacheZone",
    "Confidence",
    "Decision",
    "NetSavingsDecision",
    "NetSavingsInput",
    "PricingConfig",
    "classify_cache_zone",
    "compute_net_savings_decision",
    "emit_decision_ledger_event",
    "estimate_cache_miss_penalty",
    "estimate_ccr_retrieve_cost",
]
