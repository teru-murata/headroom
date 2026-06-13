"""RED test for finding F18-transforms.

Claim: the in-process `CompressionCache` inside
`headroom/transforms/content_router.py` keys results by
`content_key = hash(content)` (Python's builtin 64-bit str hash, computed at
content_router.py:2153) and NEVER re-verifies content equality on read
(`CompressionCache.get`, lines 228-249 stores only
`(compressed_text, ratio, strategy, timestamp)` — the originating content is
discarded). On a hash collision, `get()` returns a DIFFERENT message's
compressed bytes, which then silently replace this message's content via
`{**message, "content": cached_compressed}` (content_router.py:2169).

This file contains two tests:

1. ``test_cache_get_has_no_content_equality_recheck`` — a focused, robust
   assertion at the exact cited defect locus (the cache get/put). It proves
   the cache cannot detect a collision because it stores no originating
   content to compare against. This FAILS today.

2. ``test_apply_silently_substitutes_on_hash_collision`` — drives the real
   ``ContentRouter.apply()`` path end-to-end. ``builtins.hash`` is pinned to a
   constant (the mechanism named in the finding's exploit) so two DISTINCT
   tool messages collide on ``content_key``; the second message's emitted
   content is asserted NOT to be the first message's compressed bytes. This
   FAILS today, demonstrating the silent substitution at line 2169.
"""

from __future__ import annotations

import builtins

import pytest

import headroom.transforms.content_router as crm
from headroom.transforms.content_router import (
    CompressionCache,
    CompressionStrategy,
    ContentRouter,
    RouterCompressionResult,
    RoutingDecision,
)
from headroom.transforms.content_detector import ContentType


class _FakeTokenizer:
    """Minimal tokenizer: 1 token per whitespace-split word, enough to clear
    the ``min_tokens_to_compress`` gate in ``apply()``."""

    def count_text(self, text: str) -> int:
        return len(str(text).split())


def test_cache_get_has_no_content_equality_recheck() -> None:
    """The cited defect, isolated: ``CompressionCache.get(key)`` returns
    whatever was stored under ``key`` with NO way to verify it belongs to the
    content the caller actually holds.

    Content A and content B are distinct, but under the production keying
    scheme ``content_key = hash(content)`` a collision maps them to the same
    integer key. We simulate that single collision: A is cached first, then a
    lookup for B (same colliding key) returns A's compressed bytes.

    A correct cache would either store the originating content and return None
    on mismatch, or key on a strong digest with a stored-key equality check.
    This cache does neither, so the assertion below FAILS today.
    """
    cache = CompressionCache(ttl_seconds=1800)

    content_a = "AAAA tool output alpha " * 20
    content_b = "BBBB tool output bravo " * 20
    assert content_a != content_b

    colliding_key = 0xC0FFEE  # both contents map here under the collision

    # Message A compressed and cached under the colliding key, carrying its
    # originating content for the equality re-check.
    cache.put(colliding_key, content_a, "COMPRESSED_BYTES_FOR_A", 0.10, "text")

    # Message B (distinct content) computes the same key and looks it up,
    # passing ITS originating content. A correct cache compares the stored
    # originating content and, on mismatch, returns None (a miss) rather
    # than handing back A's compressed bytes.
    cached = cache.get(colliding_key, content_b)

    # The fix: a colliding key for distinct content is a miss, so B is
    # never served A's compressed bytes. RED on unfixed code, where get()
    # took only a key, stored no originating content, and returned A's
    # bytes for the colliding lookup (content_router.py:228-249).
    assert cached is None, (
        "CompressionCache.get returned an entry for a colliding key whose "
        "stored originating content does not match the looked-up content — "
        "no content-equality re-check on read. On a real hash collision "
        "this silently substitutes the wrong content into the prompt."
    )

    # And A still gets its own bytes back when it looks itself up.
    own = cache.get(colliding_key, content_a)
    assert own is not None and own[0] == "COMPRESSED_BYTES_FOR_A"


def test_apply_silently_substitutes_on_hash_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end reproduction through ``ContentRouter.apply()``.

    Setup:
      * ``builtins.hash`` pinned to a constant so two DISTINCT tool messages
        collide on ``content_key = hash(content)`` (content_router.py:2153).
      * ``ContentRouter.compress`` replaced with a deterministic stub that
        emits a unique, well-compressed result per input content, so the
        first message is actually cached (ratio < min_ratio).
      * ``_detect_content`` pinned to PLAIN_TEXT so no protection path fires.

    Sequence: apply([msg_A]) caches A's compressed bytes under the (constant)
    key. apply([msg_B]) — distinct content, same key — hits the cache and
    emits A's compressed bytes as B's content via line 2169.

    Assertion: B's emitted content must not equal A's compressed bytes. It
    does today, so this FAILS, demonstrating the silent substitution.
    """
    router = ContentRouter()
    tokenizer = _FakeTokenizer()

    content_a = "alpha " * 60 + "distinct content A payload"
    content_b = "bravo " * 60 + "distinct content B payload"
    assert content_a != content_b

    compressed_marker = {
        content_a: "<<COMPRESSED_A>>",
        content_b: "<<COMPRESSED_B>>",
    }

    def fake_compress(self, content, context=None, bias=1.0):  # noqa: ANN001
        return RouterCompressionResult(
            compressed=compressed_marker.get(content, "<<COMPRESSED_OTHER>>"),
            original=content,
            strategy_used=CompressionStrategy.TEXT,
            routing_log=[
                RoutingDecision(
                    content_type=ContentType.PLAIN_TEXT,
                    strategy=CompressionStrategy.TEXT,
                    original_tokens=100,
                    compressed_tokens=5,  # ratio 0.05 < default min_ratio
                )
            ],
        )

    monkeypatch.setattr(ContentRouter, "compress", fake_compress, raising=True)
    monkeypatch.setattr(ContentRouter, "_timed_compress", lambda self, c, ctx, b: (fake_compress(self, c, ctx, b), 0.0), raising=False)

    # Pin detection to plain text so protection paths don't divert the message.
    def fake_detect(content):  # noqa: ANN001
        from headroom.transforms.content_detector import DetectionResult

        return DetectionResult(ContentType.PLAIN_TEXT, 1.0, {})

    monkeypatch.setattr(crm, "_detect_content", fake_detect, raising=True)

    # Pin builtins.hash so the two distinct contents collide on content_key.
    real_hash = builtins.hash
    monkeypatch.setattr(builtins, "hash", lambda obj: 0x1234DEAD, raising=True)

    def _apply_one(content):
        msg = {"role": "tool", "tool_call_id": "tc-x", "content": content}
        result = router.apply(
            [msg],
            tokenizer,
            compress_system_messages=False,
        )
        out = result.messages[0]
        return out.get("content")

    out_a = _apply_one(content_a)
    out_b = _apply_one(content_b)

    # restore (monkeypatch also restores at teardown)
    monkeypatch.setattr(builtins, "hash", real_hash, raising=True)

    # Sanity: A was compressed and cached.
    assert out_a == "<<COMPRESSED_A>>", (
        f"precondition failed: message A was not compressed/cached as expected "
        f"(got {out_a!r}); the collision test below would be vacuous"
    )

    # The bug: B silently receives A's compressed bytes.
    assert out_b != "<<COMPRESSED_A>>", (
        "ContentRouter.apply() emitted message A's compressed bytes as message "
        "B's content after a hash collision on content_key — silent wrong-"
        "content substitution at content_router.py:2169 with no operator signal."
    )
