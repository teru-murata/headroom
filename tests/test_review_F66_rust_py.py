"""RED test for finding F66-rust-py.

The Python binding `compress_openai_responses_live_zone`
(crates/headroom-py/src/lib.rs:1550) matches the dispatcher result's
error arm as `Err(_)`, collapsing every `LiveZoneError` variant into a
single opaque passthrough reason `"dispatch_error"` and discarding `e`.

The Rust proxy (crates/headroom-proxy/src/compression/live_zone_responses.rs)
deliberately distinguishes the same two error variants as distinct
operator-visible signals:
    Err(LiveZoneError::BodyNotJson(_))   -> reason "not_json"
    Err(LiveZoneError::NoMessagesArray)  -> reason "no_messages"

This test injects each failure shape at the binding boundary and asserts
that the two error variants yield DISTINCT operator-visible reason
signals (as the proxy contract requires). It FAILS today because the
binding returns the same "dispatch_error" for both, proving genuine
faults are indistinguishable from benign passthrough.
"""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

_core = pytest.importorskip("headroom._core")


def _reason(body: bytes) -> str:
    # Return tuple shape: (bytes, modified, saved, transforms, reason)
    result = _core.compress_openai_responses_live_zone(body, "payg", "")
    return result[4]


def test_error_variants_produce_distinct_operator_signals():
    # Variant A: body is not valid JSON -> LiveZoneError::BodyNotJson
    reason_not_json = _reason(b"this is not json")
    # Variant B: valid JSON but no input/messages array -> NoMessagesArray
    reason_no_messages = _reason(b'{"model": "gpt-4o"}')

    # The proxy distinguishes these two variants ("not_json" vs
    # "no_messages"); each must be a distinct operator-visible signal.
    assert reason_not_json != reason_no_messages, (
        "binding collapses distinct LiveZoneError variants into one opaque "
        f"reason: BodyNotJson -> {reason_not_json!r}, "
        f"NoMessagesArray -> {reason_no_messages!r}"
    )

    # A genuine fault must not masquerade behind a single opaque token.
    assert reason_not_json != "dispatch_error"
    assert reason_no_messages != "dispatch_error"
