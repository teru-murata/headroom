"""Cache-aware compression net-savings benchmark helpers."""

from .model import (
    CACHE_ZONES,
    DECISIONS,
    CacheZone,
    NetSavingsDecision,
    NetSavingsInput,
    PricingConfig,
    classify_cache_zone,
    compute_net_savings_decision,
    emit_decision_ledger_event,
    estimate_cache_miss_penalty,
    estimate_ccr_retrieve_cost,
)


def run_net_savings_benchmark(*args, **kwargs):
    """Lazy wrapper that avoids importing the runner during ``python -m`` startup."""
    from .runner import run_net_savings_benchmark as _run_net_savings_benchmark

    return _run_net_savings_benchmark(*args, **kwargs)


__all__ = [
    "CACHE_ZONES",
    "DECISIONS",
    "CacheZone",
    "NetSavingsDecision",
    "NetSavingsInput",
    "PricingConfig",
    "classify_cache_zone",
    "compute_net_savings_decision",
    "emit_decision_ledger_event",
    "estimate_cache_miss_penalty",
    "estimate_ccr_retrieve_cost",
    "run_net_savings_benchmark",
]
