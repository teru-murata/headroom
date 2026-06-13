//! RED test for review finding F59-rust-proxy.
//!
//! Claim: per-strategy `proxy_compression_ratio_by_strategy` samples
//! are emitted with `content_type` hardcoded to `"aggregate"`
//! (proxy.rs:794-800), even though the metric's own contract
//! (compression_ratio.rs:17-19) defines `content_type` as the
//! detection tier (`source_code` / `log` / `search` / `diff` /
//! `json_array` / `text`). `PerStrategyTokens` and the core
//! `BlockAction::Compressed` carry no content_type, so the axis is
//! structurally fabricated: every per-strategy sample lands under
//! `content_type="aggregate"` and any per-content-type Phase-H
//! dashboard reads a constant.
//!
//! This test drives a *real* live-zone compression through the proxy:
//! a `/v1/messages` body whose latest user message carries a
//! `tool_result` of 200 homogeneous JSON dicts. The content detector
//! classifies that block as `ContentType::JsonArray` (as_str =
//! "json_array") and dispatches it to `smart_crusher`, which shrinks
//! it (this exact recipe is pinned by
//! `crates/headroom-core/tests/live_zone_dispatch.rs::json_tool_result_routes_to_smart_crusher`).
//!
//! We then scrape `/metrics` and assert the per-strategy ratio sample
//! carries the *detected* content_type ("json_array"), NOT the
//! hardcoded "aggregate". It FAILS TODAY because the proxy emit-site
//! has no content_type to pass and hardcodes "aggregate".

mod common;

use common::start_proxy_with;
use serde_json::{json, Value};
use std::sync::{Arc, Mutex};
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

/// Scrape the proxy `/metrics` text exposition.
async fn scrape_metrics(proxy_url: &str) -> String {
    let resp = reqwest::Client::new()
        .get(format!("{proxy_url}/metrics"))
        .send()
        .await
        .expect("metrics scrape");
    assert_eq!(resp.status(), 200, "metrics endpoint must return 200");
    resp.text().await.unwrap()
}

/// Find a metric line matching the name + every label pair, return its
/// trailing numeric value.
fn find_value_with_labels(scrape: &str, metric: &str, label_pairs: &[(&str, &str)]) -> Option<f64> {
    for line in scrape.lines() {
        if !line.starts_with(metric) {
            continue;
        }
        if !label_pairs
            .iter()
            .all(|(k, v)| line.contains(&format!("{k}=\"{v}\"")))
        {
            continue;
        }
        if let Some(value_str) = line.rsplit_once(' ').map(|(_, v)| v.trim()) {
            if let Ok(f) = value_str.parse::<f64>() {
                return Some(f);
            }
        }
    }
    None
}

/// True if any line of the scrape names this metric+strategy at all,
/// regardless of content_type. Used to prove the emit-site fired.
fn any_line_for_strategy(scrape: &str, metric: &str, strategy: &str) -> Vec<String> {
    scrape
        .lines()
        .filter(|l| l.starts_with(metric) && l.contains(&format!("strategy=\"{strategy}\"")))
        .map(|l| l.to_string())
        .collect()
}

async fn mount_capture(upstream: &MockServer) -> Arc<Mutex<Option<Vec<u8>>>> {
    let captured: Arc<Mutex<Option<Vec<u8>>>> = Arc::new(Mutex::new(None));
    let captured_clone = captured.clone();
    Mock::given(method("POST"))
        .and(path("/v1/messages"))
        .respond_with(move |req: &wiremock::Request| {
            *captured_clone.lock().unwrap() = Some(req.body.clone());
            ResponseTemplate::new(200).set_body_string(r#"{"ok":true}"#)
        })
        .mount(upstream)
        .await;
    captured
}

/// Body whose latest user message carries a tool_result of 200
/// homogeneous JSON dicts — the smart_crusher recipe pinned by the
/// core dispatch test.
fn json_array_tool_result_body() -> Vec<u8> {
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
    serde_json::to_vec(&json!({
        "model": "claude-sonnet-4-6",
        "max_tokens": 64,
        "system": "you are a helpful assistant",
        "messages": [{
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_f59_test",
                "content": payload,
            }],
        }],
    }))
    .unwrap()
}

#[tokio::test]
async fn per_strategy_ratio_carries_detected_content_type_not_aggregate() {
    let upstream = MockServer::start().await;
    let _captured = mount_capture(&upstream).await;
    let proxy = start_proxy_with(&upstream.uri(), |c| {
        c.compression = true;
        c.compression_mode = headroom_proxy::config::CompressionMode::LiveZone;
    })
    .await;

    let body = json_array_tool_result_body();
    let resp = reqwest::Client::new()
        .post(format!("{}/v1/messages", proxy.url()))
        .header("content-type", "application/json")
        .body(body)
        .send()
        .await
        .unwrap();
    assert_eq!(resp.status(), 200);
    let _ = resp.bytes().await.unwrap();

    let scrape = scrape_metrics(&proxy.url()).await;

    // Pre-condition: the smart_crusher per-strategy sample must have
    // been emitted at all. If this fails, compression did not fire and
    // the test is inconclusive (not a refutation of the finding).
    let strategy_lines = any_line_for_strategy(
        &scrape,
        "proxy_compression_ratio_by_strategy_count",
        "smart_crusher",
    );
    assert!(
        !strategy_lines.is_empty(),
        "PRECONDITION: live-zone compression did not emit a smart_crusher \
         per-strategy ratio sample — cannot evaluate the content_type axis. \
         Scrape (ratio rows):\n{}",
        scrape
            .lines()
            .filter(|l| l.contains("proxy_compression_ratio_by_strategy"))
            .collect::<Vec<_>>()
            .join("\n"),
    );

    // The defect: the contract says content_type is the detection
    // tier. This block detects to ContentType::JsonArray (as_str =
    // "json_array"). So the per-strategy sample for smart_crusher MUST
    // carry content_type="json_array".
    let detected = find_value_with_labels(
        &scrape,
        "proxy_compression_ratio_by_strategy_count",
        &[("strategy", "smart_crusher"), ("content_type", "json_array")],
    );
    assert!(
        detected.is_some(),
        "F59: per-strategy ratio sample for smart_crusher must carry the \
         DETECTED content_type=\"json_array\" (the metric contract defines \
         content_type as the detection tier). Instead the emit-site \
         hardcodes \"aggregate\". smart_crusher rows actually seen:\n{}",
        strategy_lines.join("\n"),
    );
}
