"""RED test for finding F17-transforms.

Claim: ContentRouter exports *whitespace word counts* as *token* metrics.
``_apply_strategy_to_content`` / ``_compress_pure`` set
``original_tokens = len(content.split())`` and derive ``compressed_tokens``
from ``len(result.compressed.split())`` for the routed strategies. Those
values flow through ``RoutingDecision`` into ``_observe()`` ->
``observer.record_compression(original_tokens, compressed_tokens)`` (the
Prometheus per-strategy savings surface). Meanwhile a real ``Tokenizer``
(``count_text``) is used elsewhere in ``apply()``, so the per-strategy
"token" savings are not real token counts.

This test routes punctuation-dense JSON (whose tokenizer count is far from
its whitespace word count) through ``ContentRouter`` with a recording
observer, and asserts that the ``original_tokens`` the observer receives is
a genuine token count rather than ``len(content.split())``.

RED today: the observer receives the whitespace word count (e.g. 1 for a
compact JSON blob), which is NOT a token count. GREEN once the router
forwards real tokenizer counts to the observer/result.
"""

from __future__ import annotations

import re

from headroom.transforms.content_router import ContentRouter


class _RecordingObserver:
    """Minimal CompressionObserver capturing record_compression args."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def record_compression(
        self, strategy: str, original_tokens: int, compressed_tokens: int
    ) -> None:
        self.calls.append((strategy, original_tokens, compressed_tokens))


def _reference_token_count(text: str) -> int:
    """A conservative lower-bound *token* count.

    Real tokenizers (BPE) emit separate tokens for punctuation, so for
    punctuation-dense content the token count is many times the whitespace
    word count. We do NOT need exact parity with any provider tokenizer:
    we only need a count that is unambiguously a *token* count and clearly
    distinct from ``len(text.split())``. Splitting into word-runs and
    individual punctuation marks is a strict, well-known under-estimate of
    BPE token counts, yet still far exceeds the whitespace word count for
    JSON.
    """
    return len(re.findall(r"\w+|[^\w\s]", text))


def test_observer_receives_token_counts_not_word_counts() -> None:
    # Punctuation-dense JSON: almost no whitespace, so len(split()) is tiny
    # while the real token count is large.
    content = '{"users":[{"id":1,"name":"Ann"},{"id":2,"name":"Bob"}]}'

    word_count = len(content.split())
    token_count = _reference_token_count(content)

    # Sanity: the two metrics genuinely diverge for this input.
    assert word_count != token_count
    assert token_count > word_count * 5  # punctuation-dense -> big gap

    observer = _RecordingObserver()
    router = ContentRouter(observer=observer)
    router.compress(content)

    assert observer.calls, "observer was never called for routed content"
    _strategy, original_tokens, _compressed_tokens = observer.calls[0]

    # The defect: original_tokens is the whitespace word count, not a real
    # token count. Assert it is a genuine token count (close to a real
    # tokenizer) rather than the word count.
    assert original_tokens != word_count, (
        "ContentRouter exported the whitespace word count "
        f"({word_count}) as original_tokens; expected a real token count "
        f"(~{token_count})"
    )
    # A real token count must be at least the under-estimate above.
    assert original_tokens >= token_count, (
        f"original_tokens={original_tokens} is below the conservative "
        f"token lower bound {token_count}; it is a word count, not tokens"
    )
