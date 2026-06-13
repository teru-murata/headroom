//! RED test for finding F54-rust-core (partition rust-core, major).
//!
//! Claim: `auth_mode.rs:44-51` and `live_zone.rs:88-95` document
//! OAuth/Subscription as a "no lossy compressors. Lossless-only path."
//! But `compress_anthropic_live_zone_with_ccr` binds `_auth_mode` and
//! `dispatch_compressor` never consults it, so SmartCrusher (a lossy
//! row-drop compressor) runs identically for Payg, OAuth, and
//! Subscription.
//!
//! This test feeds a >512B JSON-array tool_result that SmartCrusher
//! provably compresses, but tags the request `AuthMode::OAuth`. If the
//! documented lossless gate were honored, the dispatcher would return
//! `NoChange`. The finding predicts it returns `Modified` today.
//!
//! Run:
//!   cargo test -p headroom-core --test review_f54_rust_core

use headroom_core::transforms::live_zone::DEFAULT_MODEL;
use headroom_core::transforms::{compress_anthropic_live_zone, AuthMode, LiveZoneOutcome};
use serde_json::{json, Value};

fn body_with_oauth_tool_result(text: &str) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 64,
        "messages": [{
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_f54",
                "content": text,
            }],
        }],
    }))
    .unwrap()
}

#[test]
fn oauth_request_must_not_run_lossy_smart_crusher() {
    // 200 homogeneous dicts (>512B) — SmartCrusher's bread-and-butter,
    // the exact shape the dispatch suite uses to prove a Modified.
    let array_of_dicts: Vec<Value> = (0..200)
        .map(|i| {
            json!({
                "id": i,
                "status": "ok",
                "value": format!("repeat-pattern-{}", i % 3),
            })
        })
        .collect();
    let payload = serde_json::to_string(&array_of_dicts).unwrap();
    assert!(
        payload.len() > 512,
        "precondition: payload must exceed the 512B JSON-array threshold (got {})",
        payload.len()
    );

    let body = body_with_oauth_tool_result(&payload);

    // Sanity: under Payg the dispatcher DOES run SmartCrusher and
    // returns Modified. (If this ever fails, the body stopped
    // triggering the compressor and the OAuth assertion below would be
    // vacuous.)
    let payg = compress_anthropic_live_zone(&body, 0, AuthMode::Payg, DEFAULT_MODEL)
        .expect("dispatcher returns Ok on valid body");
    assert!(
        matches!(payg, LiveZoneOutcome::Modified { .. }),
        "control: Payg should compress this body, else the OAuth check is vacuous"
    );

    // The documented OAuth contract: "no lossy compressors.
    // Lossless-only path." SmartCrusher row-drop is lossy, so a
    // correctly-gated dispatcher must return NoChange here.
    let oauth = compress_anthropic_live_zone(&body, 0, AuthMode::OAuth, DEFAULT_MODEL)
        .expect("dispatcher returns Ok on valid body");
    assert!(
        matches!(oauth, LiveZoneOutcome::NoChange { .. }),
        "OAuth is documented as lossless-only (no lossy compressors), but the \
         dispatcher ran SmartCrusher and returned Modified: {oauth:?}"
    );
}
