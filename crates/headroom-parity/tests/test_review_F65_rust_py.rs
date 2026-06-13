//! RED test for finding F65-rust-py.
//!
//! Claim: the `parity-run` CLI sets `any_diffs` only inside the diffed loop, so
//! `exit(1)` fires only on an explicit Diff. Comparator errors become `Skipped`
//! and a missing/empty fixtures dir yields an empty report. Therefore a fully
//! broken or absent Rust port reports exit 0 — the parity gate is fail-open.
//!
//! This test drives the real `parity-run` binary (via `CARGO_BIN_EXE_*`) against
//! two fail-open scenarios and asserts the gate exits non-zero. If the gate is
//! fail-open (the bug), the process exits 0 and these assertions FAIL today.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn unique_tmpdir(tag: &str) -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!(
        "headroom-parity-F65-{tag}-{nanos}-{:?}",
        std::thread::current().id()
    ));
    fs::create_dir_all(&p).unwrap();
    p
}

/// Write a fixture JSON under `dir/<transform>/<name>.json`.
fn write_fixture(dir: &Path, transform: &str, name: &str, output: serde_json::Value) {
    let sub = dir.join(transform);
    fs::create_dir_all(&sub).unwrap();
    let fixture = serde_json::json!({
        "transform": transform,
        "input": "hello",
        "config": {},
        "output": output,
        "recorded_at": "2026-04-23T00:00:00Z",
        "input_sha256": "deadbeef",
    });
    let mut f = fs::File::create(sub.join(format!("{name}.json"))).unwrap();
    f.write_all(&serde_json::to_vec_pretty(&fixture).unwrap())
        .unwrap();
}

fn run_parity(fixtures: &Path, only: Option<&str>) -> std::process::ExitStatus {
    let bin = env!("CARGO_BIN_EXE_parity-run");
    let mut cmd = Command::new(bin);
    cmd.arg("run").arg("--fixtures").arg(fixtures);
    if let Some(o) = only {
        cmd.arg("--only").arg(o);
    }
    cmd.status().expect("failed to run parity-run")
}

/// Scenario A: a fixture exists for a stub comparator (`log_compressor`), whose
/// `run` always bails -> the fixture is Skipped. matched==0, diffed==0,
/// skipped==1. A fail-closed parity gate must NOT pass green here: every fixture
/// was skipped, so the port proved nothing. The gate should exit non-zero.
#[test]
fn all_skipped_must_not_exit_zero() {
    let tmp = unique_tmpdir("skipped");
    write_fixture(
        &tmp,
        "log_compressor",
        "case1",
        serde_json::json!({"compressed": "x"}),
    );
    let status = run_parity(&tmp, Some("log_compressor"));
    let _ = fs::remove_dir_all(&tmp);
    assert!(
        !status.success(),
        "parity gate passed green (exit 0) although the only fixture was SKIPPED \
         (comparator bailed). Fail-open gate: a fully-broken comparator proves nothing \
         yet the gate reports success."
    );
}

/// Scenario B: an empty/typo'd fixtures dir -> total==0 for every comparator.
/// A fail-closed parity gate must NOT pass green when it compared zero fixtures.
#[test]
fn zero_total_must_not_exit_zero() {
    let tmp = unique_tmpdir("empty");
    // No fixtures written at all -> every comparator's transform dir is absent
    // -> empty report -> total==0.
    let status = run_parity(&tmp, None);
    let _ = fs::remove_dir_all(&tmp);
    assert!(
        !status.success(),
        "parity gate passed green (exit 0) although it compared ZERO fixtures \
         (missing/empty fixtures dir). Fail-open gate: a fixtures-path typo makes \
         the gate vacuously pass."
    );
}
