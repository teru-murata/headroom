"""RED test for finding F21-ccr-cache.

Claim: CCRResponseHandler.handle_response() is `async`, but it executes CCR
retrievals synchronously on the event loop:

    results = [self._execute_retrieval(call) for call in ccr_calls]   # L442

_execute_retrieval() calls store.retrieve()/store.search() which perform
blocking SQLite disk I/O + BM25 scoring + json parsing under a threading.Lock.
None of it is offloaded via asyncio.to_thread, so one slow/blocked retrieval
starves every other coroutine running on the same event loop.

This test patches the compression store so that a single retrieval blocks the
calling thread for a fixed window, and runs a concurrent "ticker" coroutine
that should keep making progress on the loop. If the retrieval is offloaded to
a worker thread (the fix), the ticker keeps ticking during the block window.
If the retrieval runs inline on the event loop (the bug), the ticker is starved
and records ~0 ticks during the block.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from headroom.ccr import response_handler as rh
from headroom.ccr.response_handler import (
    CCRResponseHandler,
    ResponseHandlerConfig,
)
from headroom.ccr.tool_injection import CCR_TOOL_NAME


# How long the blocking retrieval holds the thread.
BLOCK_SECONDS = 0.6
# Ticker fires this often; during BLOCK_SECONDS we expect many ticks if the
# event loop is NOT starved.
TICK_INTERVAL = 0.01


class _BlockingStore:
    """Fake compression store whose retrieve() blocks the calling thread.

    Mimics a cold SQLite page / lock contention: a plain synchronous sleep
    (time.sleep) that holds whatever thread runs it. If run on the event loop
    thread, the loop is frozen for BLOCK_SECONDS.
    """

    def __init__(self) -> None:
        self.entered_at: float | None = None
        self.exited_at: float | None = None

    def retrieve(self, hash_key, *args, **kwargs):
        self.entered_at = time.monotonic()
        time.sleep(BLOCK_SECONDS)  # synchronous, blocking I/O stand-in
        self.exited_at = time.monotonic()
        # Return None -> handler builds a "not found" tool result; that's fine,
        # the loop still ends after one round (next response has no CCR calls).
        return None

    def search(self, hash_key, query, *args, **kwargs):  # pragma: no cover
        return self.retrieve(hash_key)


def _anthropic_response_with_ccr_call() -> dict:
    """A response containing one CCR tool_use block (triggers a retrieval)."""
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": CCR_TOOL_NAME,
                # 12-hex marker is accepted by normalize_ccr_hash.
                "input": {"hash": "abcdef012345"},
            }
        ],
    }


def _anthropic_response_no_ccr() -> dict:
    """A plain assistant response with no CCR tool calls (ends the loop)."""
    return {
        "id": "msg_2",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "done"}],
    }


@pytest.mark.asyncio
async def test_handle_response_offloads_blocking_retrieval(monkeypatch):
    store = _BlockingStore()
    # Patch the store factory used inside _execute_retrieval.
    monkeypatch.setattr(rh, "get_compression_store", lambda: store)

    handler = CCRResponseHandler(ResponseHandlerConfig(enabled=True))

    async def api_call_fn(messages, tools):
        # Continuation call: respond with no CCR calls so the loop terminates.
        return _anthropic_response_no_ccr()

    # Concurrent ticker that should keep progressing if the loop is healthy.
    ticks_during_block: list[float] = []
    stop = False

    async def ticker():
        while not stop:
            # Only count ticks that happen while the retrieval is in-flight.
            if store.entered_at is not None and store.exited_at is None:
                ticks_during_block.append(time.monotonic())
            await asyncio.sleep(TICK_INTERVAL)

    ticker_task = asyncio.create_task(ticker())
    try:
        result = await handler.handle_response(
            _anthropic_response_with_ccr_call(),
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            api_call_fn=api_call_fn,
            provider="anthropic",
        )
    finally:
        stop = True
        await ticker_task

    # Sanity: the blocking retrieval actually ran.
    assert store.entered_at is not None and store.exited_at is not None
    blocked_for = store.exited_at - store.entered_at
    assert blocked_for >= BLOCK_SECONDS * 0.8

    # If the retrieval were offloaded (asyncio.to_thread / run_in_executor),
    # the event loop stays free and the ticker fires many times during the
    # ~0.6s block (roughly BLOCK_SECONDS / TICK_INTERVAL = ~60 ticks).
    # Require a conservative lower bound well above what a starved loop allows.
    expected_min_ticks = int((BLOCK_SECONDS / TICK_INTERVAL) * 0.3)  # ~18
    assert len(ticks_during_block) >= expected_min_ticks, (
        f"Event loop was starved during the blocking retrieval: only "
        f"{len(ticks_during_block)} concurrent ticks during a {blocked_for:.2f}s "
        f"block (expected >= {expected_min_ticks}). handle_response runs CCR "
        f"retrievals synchronously on the event loop instead of offloading via "
        f"asyncio.to_thread."
    )
