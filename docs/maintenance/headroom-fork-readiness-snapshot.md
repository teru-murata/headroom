# Headroom Fork Readiness Snapshot

Date: 2026-06-06

## 1. Purpose

This snapshot records the post-H001-H009 and post-U001-U006 state of the
`teru-murata/headroom` fork.

Its purpose is to decide whether the fork is ready to serve as the
compression/local-core dependency for
`mishima-computing/coding-agent-bridge`.

## 2. Summary

The fork is ready to use as the local compression and local telemetry producer
for Coding Agent Bridge / Kuchino work.

Headroom now has the local pieces needed for a bridge dependency:

- source-specific coding-agent context compression
- evidence-preserving log, diff, and file-tree compression coverage
- local CCR marker parsing, injection, retrieve, and storage
- local durable SQLite CCR backend
- local provenance event emission and JSONL export
- bridge-compatible local telemetry attribute names
- local context waste and cache-aware decision benchmarks
- selected upstream runtime, OpenAI Responses, Copilot auth, and safety fixes

This does not mean hosted SaaS is implemented in Headroom. The hosted bridge,
tenant policy, billing, dashboards, deployment profiles, remote retrieve policy,
and conformance authority remain `coding-agent-bridge` work.

## 3. Completed Headroom-Local Implementation Work

| Work | Completed scope | Why it matters for the SaaS bridge |
|---|---|---|
| H001 | CCR marker parsing and SmartCrusher `<<ccr:...>>` compatibility. | Gives the bridge a stable local marker/retrieve contract to depend on without inventing hosted marker policy in Headroom. |
| H002 | Local proxy CCR retrieve visibility / TOIN retrieve fix. | Ensures locally compressed originals can be retrieved through the proxy path that bridge adapters will exercise. |
| H003 | Local SQLite CCR backend. | Provides restart-surviving local/single-host CCR storage for development, demos, and local bridge workflows. |
| H004 | Evidence-preserving test/build log crusher acceptance tests. | Keeps failed test names, assertions, file paths, tracebacks, commands, and exit codes available for coding agents. |
| H005 | Diff and file-tree crusher acceptance tests. | Preserves edit targets, hunks, symbols, package roots, configs, and source/test tree shape for coding-agent workflows. |
| H006 | `CodingAgentPreset` source-specific routing. | Gives the bridge a local preset surface for routing logs, diffs, file trees, package metadata, tool output, MCP results, and source code safely. |
| H007 | Provenance ledger emitter, JSONL export, and `bridge.*` OTel-compatible attributes. | Lets Headroom produce local ledger-compatible events that bridge-side ingest can later consume. |
| H008 | Coding-agent context waste benchmark suite. | Provides local/offline evidence for where context is wasted and which source types benefit from compression. |
| H009 | Cache-aware net-savings benchmark and decision model. | Adds local decision support for compress-vs-skip choices while avoiding billing-grade claims. |

## 4. Upstream Intake Completed

| Batch | Completed scope |
|---|---|
| U001 | Security and small correctness batch. |
| U002 | Security/runtime correctness batch. |
| U003 | OpenAI Responses runtime/cache/performance batch. |
| U004 | Copilot subscription auth batch. |
| U005 | Residual upstream audit. |
| U006 | Small runtime correctness fixes. |

`upstream/main` was not merged. Selected upstream commits were cherry-picked
with `-x`.

README marketing, `60B+` / leaderboard language, Trendshift badge, release
bumps, and broad upstream claims were not restored.

Current repo relation after U006:

```text
main...origin/main:
  0 0

main...upstream/main:
  54 63
```

The remaining upstream behind count is expected because this fork uses
selective cherry-pick intake instead of merging upstream history.

## 5. Current Shipped Capabilities

Current shipped local/core capabilities include:

- coding-agent surrounding context compression
- evidence-preserving log compression
- diff and file-tree compression acceptance coverage
- `CodingAgentPreset` routing for supported coding-agent source types
- local CCR marker parsing for bracket retrieve markers and SmartCrusher
  `<<ccr:...>>` markers
- local CCR retrieve flow through tool injection and proxy retrieve paths
- local SQLite CCR backend for single-host durable storage
- provenance ledger-compatible local events
- local JSONL export
- `bridge.*` OTel-compatible attributes
- context waste benchmark
- cache-aware net-savings decision model
- selected OpenAI Responses upstream runtime/cache/performance improvements
- selected Copilot auth upstream improvements
- small runtime correctness fixes for local proxy startup and corrupt golden
  bytes fail-open recovery

Current non-capabilities:

- hosted SaaS is not implemented in Headroom
- remote/team tenant authorization is not implemented in Headroom
- Redis/Valkey hosted CCR profile is not implemented in Headroom
- production billing-grade savings are not implemented in Headroom
- Headroom does not claim all context is compressed
- source code is not blindly compressed
- reversible conversation-history compaction is not implemented
- multimodal/realtime compression is not implemented
- true transport-level delta mode is not implemented

## 6. Boundary With Coding-Agent-Bridge

Headroom owns:

- compression algorithms
- local runtime
- local proxy safety
- local CCR behavior
- marker parser compatibility
- coding-agent presets
- compression acceptance tests
- local emitter/exporter compatibility
- local benchmark tooling

`coding-agent-bridge` owns:

- hosted/shared bridge deployment
- tenant/project/session namespace
- API key/auth/policy enforcement
- signed check-in
- SaaS ledger ingest/retention/reconciliation
- billing and usage metering
- dashboard
- ROI reporting
- deployment profiles
- conformance authority
- partner-runnable certification suite
- hosted observability integrations
- SaaS control plane

Shared versioned public contracts:

- `ledger-event-v0`
- `otel-attributes-v0`
- `source-taxonomy-v0`
- `ccr-marker-v0`
- `bridge-checkin-v0`

This snapshot records the boundary only. It does not define the full
bridge-side authorization, billing, deployment, or conformance contract.

## 7. Validation Status

Recent task logs record targeted validation through H001-H009, M001, and
U001-U006.

Validation status that is safe to claim:

- H001-H009 targeted suites passed for their respective implementation scopes.
- U001-U006 targeted suites passed for selected upstream intake scopes.
- `ruff check` passed in each implementation/intake task where it was run.
- `ruff format --check` passed in each implementation/intake task where it was
  run.
- `git diff --check` passed for each checked-in task.
- `npm exec fumadocs-mdx` passed from `docs/` for docs maintenance tasks where
  docs changed.

Full pytest was not completed end-to-end in this Windows environment. Do not
state that the full suite passed.

Recorded Windows caveats from prior maintenance logs:

- U001: `tests/test_codex_ws_compression_scheduler.py::test_concurrent_compression_has_no_semaphore_tail` timed out after 184 seconds on Windows.
- U002/U003: full or focused `tests/test_openai_responses_context_compaction.py`
  runs timed out on Windows in recorded checks.
- H003: a broader row-drop subset timed out after 184 seconds, and a full
  `tests/test_adapter_hooks.py` run still had unrelated Windows storage URI
  parsing failures.
- H004: a focused `tests/test_transforms/test_content_router.py` run timed out
  after 124 seconds.

These caveats do not override the targeted passing suites, but they prevent
claiming full-suite completion.

## 8. Known Caveats

- Full pytest has not been completed end-to-end in this Windows environment.
- Some broad or focused test modules timed out on Windows; targeted suites
  passed.
- Token counts in benchmarks are estimates, not provider billing truth.
- Net savings is decision/ROI support, not an invoice denominator.
- SQLite CCR backend is a local/single-host durable backend, not hosted/team
  multi-tenant storage.
- Redis/Valkey hosted profile is delegated to `coding-agent-bridge`.
- Hosted ledger ingest, dashboards, billing, deployment profiles, and SaaS
  control plane are not implemented in Headroom.
- Remote/team retrieve authorization is not implemented in Headroom.
- The checked-in validation logs are evidence for targeted tasks, not proof of
  full-suite health.

## 9. Remaining Headroom Roadmap

Advanced Headroom core items still open or deferred:

- #6 true cache-aware alignment / delta mode
- #7 reversible conversation-history compaction
- #12 multimodal and realtime-agent compression roadmap

Open items intentionally left as bridge or integration boundaries:

- #10 remote/shared proxy deployment mode
- #18 remote CCR auth policy
- #19 hosted ledger side remains `coding-agent-bridge`
- #20 hosted export management remains `coding-agent-bridge`
- #21 sandbox/code-execution provenance bridge remains mostly SaaS/integration
  side

These items are not shipped by the H001-H009 or U001-U006 work.

## 10. Recommendation

Recommendation: return to `mishima-computing/coding-agent-bridge` next.

Rationale: the Headroom fork now has enough local/core capability to serve as
the compression and local telemetry producer for the Kuchino / Coding Agent
Bridge SaaS implementation. Further Headroom work should be treated as
advanced-core roadmap work, not as a blocker for starting the SaaS executable
platform.

Do not continue upstream intake by default. The remaining upstream divergence is
mostly README/docs/release/CI material that should be handled only by explicit
manual audit if needed.
