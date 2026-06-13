//! Test for finding F53-rust-core (partition rust-core, severity major).
//!
//! Original claim: `BlockAction::Compressed` documented
//! `original_tokens`/`compressed_tokens` as "Tokens ... per the model's
//! tokenizer", and `CompressionManifest::tokens_saved()` sums them as the
//! reported savings. But the live-zone dispatcher counts tokens via
//! `get_tokenizer(model)` with `model` defaulting to
//! `DEFAULT_MODEL = "claude-3-5-sonnet-20241022"`, and the registry routes
//! every `claude-*` name to the chars/3.5 `EstimatingCounter`, NOT a real
//! tokenizer. So the headline token-savings figure for the dominant Claude
//! traffic is a heuristic char-count estimate that was mislabeled as
//! tokenizer-measured truth.
//!
//! FIX (NN1 — truth in labeling): Anthropic does not publish a Claude
//! tokenizer, so routing `claude-*` to a real BPE backend (e.g. Tiktoken)
//! would produce *wrong* counts — that is not an honest fix. The honest fix
//! is to stop overclaiming: the `BlockAction::Compressed` / `tokens_saved()`
//! docs now state the counts are tokenizer-measured only when a real
//! tokenizer exists and are a calibrated *estimate* for `claude-*`, and a
//! provenance method `CompressionManifest::token_counts_are_estimated(model)`
//! lets callers/operators label the figure correctly.
//!
//! This test pins the corrected contract. It does NOT compile against the
//! unfixed code (the provenance method does not exist there), so it is RED on
//! unfixed code and GREEN after the fix.
//!
//! Run:
//!   cargo test -p headroom-core --test review_f53_rust_core

use headroom_core::tokenizer::{get_tokenizer, Backend};
use headroom_core::transforms::live_zone::{CompressionManifest, DEFAULT_MODEL};

/// The dispatcher's default model is the dominant production Claude model.
/// Pin the value so a future rename of `DEFAULT_MODEL` is caught here too.
#[test]
fn default_model_is_dominant_claude() {
    assert_eq!(
        DEFAULT_MODEL, "claude-3-5-sonnet-20241022",
        "finding assumes the live-zone dispatcher defaults to the dominant \
         production Claude model"
    );
}

/// The factual premise of the finding: the default Claude model resolves to
/// the chars/3.5 estimator, not a real tokenizer. (Anthropic publishes no
/// tokenizer, so this is expected — the bug was the *label*, not the backend.)
#[test]
fn default_model_resolves_to_the_estimator_not_a_real_tokenizer() {
    let backend = get_tokenizer(DEFAULT_MODEL).backend();
    assert_eq!(
        backend,
        Backend::Estimation,
        "Anthropic publishes no tokenizer; the default Claude model is \
         expected to fall back to the chars/cpt estimator. If this ever \
         routes to a real tokenizer, the labeling contract below should be \
         revisited."
    );
}

/// RED→GREEN: the corrected contract. For the default Claude model the
/// manifest must report its token counts as *estimated* (so the headline
/// savings figure is labeled an estimate, not a measured tokenizer count).
///
/// Compiles only against the fixed code: `token_counts_are_estimated` does
/// not exist on the unfixed `CompressionManifest`.
#[test]
fn default_model_token_counts_are_labeled_estimated() {
    assert!(
        CompressionManifest::token_counts_are_estimated(DEFAULT_MODEL),
        "for the default Claude model {DEFAULT_MODEL} the token counts that \
         feed tokens_saved() are a chars/cpt estimate, so the manifest must \
         report them as estimated (not mislabel them as tokenizer-measured)"
    );
}

/// A model WITH a real tokenizer (OpenAI BPE) must NOT be flagged as
/// estimated — the provenance helper has to actually discriminate, not just
/// return `true` for everything.
#[test]
fn real_tokenizer_model_is_not_labeled_estimated() {
    assert_eq!(
        get_tokenizer("gpt-4o").backend(),
        Backend::Tiktoken,
        "control: gpt-4o routes to a real tokenizer"
    );
    assert!(
        !CompressionManifest::token_counts_are_estimated("gpt-4o"),
        "gpt-4o counts come from a real BPE tokenizer, so they must NOT be \
         labeled estimated"
    );
}
