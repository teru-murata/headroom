"""RED test for F23-ccr-cache.

Claim: ResponseHandlerConfig.continuation_timeout_ms (default 120000) is never
read anywhere in the module. CCRResponseHandler.handle_response awaits
api_call_fn(...) with no asyncio.wait_for, so a hung upstream blocks the CCR
continuation indefinitely. Operators who configure continuation_timeout_ms get
silent no-op protection.

This test configures a tiny continuation_timeout_ms and supplies an api_call_fn
that hangs forever. If the timeout were honored, handle_response would return
(or raise) promptly. If the bug is real, handle_response hangs and the outer
asyncio.wait_for guard fires -> test FAILS (RED).
"""

from __future__ import annotations

import asyncio

import pytest

from headroom.ccr.response_handler import (
    CCRResponseHandler,
    ResponseHandlerConfig,
)
from headroom.ccr.tool_injection import CCR_TOOL_NAME


def _anthropic_response_with_ccr_tool_call() -> dict:
    """An Anthropic-shaped response containing a CCR (headroom_retrieve) tool_use.

    This forces handle_response to perform at least one continuation API call.
    """
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_001",
                "name": CCR_TOOL_NAME,
                # 12-hex marker; store lookup will simply miss, but the
                # retrieval (and hence the continuation api_call_fn) still runs.
                "input": {"hash": "abcdef012345"},
            }
        ],
        "stop_reason": "tool_use",
    }


@pytest.mark.asyncio
async def test_continuation_respects_timeout():
    # Configure a small continuation timeout (50 ms).
    config = ResponseHandlerConfig(
        enabled=True,
        max_retrieval_rounds=3,
        continuation_timeout_ms=50,
    )
    handler = CCRResponseHandler(config)

    hang_started = asyncio.Event()

    async def hanging_api_call_fn(messages, tools):
        # Simulate a hung upstream: never returns.
        hang_started.set()
        await asyncio.sleep(3600)
        return {"content": []}

    response = _anthropic_response_with_ccr_tool_call()

    # If continuation_timeout_ms were honored (50 ms), handle_response would
    # return/raise well within this 2 s budget. The bug means it hangs forever;
    # the outer wait_for then raises TimeoutError -> RED.
    try:
        result = await asyncio.wait_for(
            handler.handle_response(
                response=response,
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                api_call_fn=hanging_api_call_fn,
                provider="anthropic",
            ),
            timeout=2.0,
        )
    except asyncio.TimeoutError:
        assert hang_started.is_set(), "api_call_fn was never reached"
        pytest.fail(
            "handle_response hung past the outer 2s guard despite "
            "continuation_timeout_ms=50: the configured continuation_timeout_ms "
            "is never enforced (no asyncio.wait_for around api_call_fn)."
        )

    # If we get here, the continuation call did NOT hang indefinitely, meaning
    # the configured timeout (or some guard) was honored.
    assert result is not None
