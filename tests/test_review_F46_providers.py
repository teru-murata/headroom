"""RED test for finding F46-providers.

Claim: TokenizerRegistry.get() / get_tokenizer() silently substitutes the
EstimatingTokenCounter (a ~4-chars/token heuristic) whenever exact tokenizer
construction fails and fallback=True (the default), emitting only a warning
log. The returned counter is indistinguishable at the API boundary from an
exact counter, so callers (a context-headroom product) cannot detect that
exact tokenization has degraded to estimation -- risking silent context-window
overflow.

This test forces tiktoken construction to fail for an OpenAI model and asserts
that the degradation is OBSERVABLE through the public API: either the returned
counter exposes an estimated/degraded flag, or get() raises/signals the
degradation rather than returning a bare estimator.

If the bug is real, this test FAILS today (the estimator is returned silently
with no observable signal).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_registry_singleton():
    """Reset the TokenizerRegistry singleton and its caches around each test.

    The registry is a process-wide singleton with class-level dicts; isolate
    so we never leave a poisoned estimator in the shared cache.
    """
    from headroom.tokenizers import registry as reg

    # Snapshot
    prev_instance = reg.TokenizerRegistry._instance
    prev_tokenizers = dict(reg.TokenizerRegistry._tokenizers)
    prev_factories = dict(reg.TokenizerRegistry._factories)
    prev_cache = dict(reg.TokenizerRegistry._cache)

    # Hard reset to a clean state
    reg.TokenizerRegistry._instance = None
    reg.TokenizerRegistry._tokenizers = {}
    reg.TokenizerRegistry._factories = {}
    reg.TokenizerRegistry._cache = {}

    yield

    # Restore
    reg.TokenizerRegistry._instance = prev_instance
    reg.TokenizerRegistry._tokenizers = prev_tokenizers
    reg.TokenizerRegistry._factories = prev_factories
    reg.TokenizerRegistry._cache = prev_cache


def _force_tiktoken_construction_failure(monkeypatch):
    """Make exact tiktoken tokenizer construction fail.

    This simulates a real-world tokenizer-construction failure (broken/missing
    encoding data, incompatible tiktoken version, etc.). The registry's get()
    catches such errors (and _create_tiktoken catches ImportError) and silently
    substitutes EstimatingTokenCounter() when fallback=True.
    """
    import headroom.tokenizers.tiktoken_counter as tk

    class _BrokenTiktoken:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("simulated: tiktoken encoding unavailable")

    monkeypatch.setattr(tk, "TiktokenCounter", _BrokenTiktoken)


def test_tokenizer_fallback_is_observable(monkeypatch):
    from headroom.tokenizers.estimator import EstimatingTokenCounter
    from headroom.tokenizers.registry import get_tokenizer

    _force_tiktoken_construction_failure(monkeypatch)

    # Default fallback=True: per the source this silently returns an estimator.
    counter = get_tokenizer("gpt-4o")

    # Sanity: confirm we actually triggered the fallback path (else the test
    # would be vacuous / not reproducing the claimed scenario).
    assert isinstance(counter, EstimatingTokenCounter), (
        "Precondition: forcing tiktoken failure should route gpt-4o to the "
        "estimating fallback. If this assertion fails the test setup is wrong, "
        "not the finding."
    )

    # THE CLAIM: the degradation from exact -> estimated tokenization must be
    # observable at the API boundary. A context-headroom product needs to know
    # the count is an estimate (which can under-count and overflow the window).
    #
    # Accept ANY of the reasonable observability mechanisms:
    #   - an `is_estimate` / `is_exact` / `is_estimated` attribute
    #   - a `degraded` / `is_fallback` flag
    #   - an `accuracy` / `confidence` descriptor
    observable = (
        getattr(counter, "is_estimate", None) is True
        or getattr(counter, "is_estimated", None) is True
        or getattr(counter, "is_exact", None) is False
        or getattr(counter, "degraded", None) is True
        or getattr(counter, "is_fallback", None) is True
        or getattr(counter, "accuracy", None) in {"estimate", "estimated", "approximate"}
    )

    assert observable, (
        "Tokenizer construction for 'gpt-4o' degraded to EstimatingTokenCounter "
        "but exposes NO observable signal via the public TokenCounter API. "
        "count_text/count_messages return an estimate indistinguishable from an "
        "exact count -- callers cannot detect the degradation, risking silent "
        "context-window overflow (F46-providers)."
    )
