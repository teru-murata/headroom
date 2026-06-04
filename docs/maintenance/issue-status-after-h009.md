# Issue Status After H009

This note records repository maintenance status after the H001-H009 local
Headroom implementation sequence. It does not change GitHub issue state.

## Completed Headroom-Local Work

| Work | Issue status observed | Notes |
|---|---|---|
| H001 local CCR marker parsing and SmartCrusher `<<ccr:...>>` compatibility | #4 open, #13 open | Local parser, validation, tool injection, and retrieve-tool parsing are implemented. These issues are close-ready if their accepted scope is Headroom-local only. |
| H002 local proxy CCR retrieve visibility / TOIN retrieve fix | Covered by #13 / local CCR path | Local `/v1/retrieve` now shares store visibility and marker/hash normalization while preserving loopback safety. |
| H003 local SQLite CCR backend | #8 open | Local single-host SQLite backend is implemented. Keep #8 open only if it still tracks hosted/shared Redis or Valkey work delegated to coding-agent-bridge, or split that remainder into bridge scope. |
| H004 evidence-preserving test/build log crusher acceptance | #16 closed | Acceptance fixtures and evidence guard are shipped. |
| H005 diff and file-tree crusher acceptance | #17 closed | Diff and file-tree evidence preservation plus CCR retrievability are shipped. |
| H006 coding-agent output compression preset | #9 closed | Source-specific local routing is shipped. |
| H007 provenance ledger emitter, JSONL export, and `bridge.*` attributes | #19 open | Headroom producer is implemented; hosted ingest/retention/reconciliation remains bridge scope. |
| H008 context waste benchmark suite | #14 closed | Local/offline source taxonomy benchmark is shipped. |
| H009 cache-aware net-savings benchmark and decision model | #15 closed | Local compress-vs-skip decision support is shipped. |

Issue #11 is also closed; the README/docs claim-audit work is refreshed by
M001.

## Intentionally Open

These issues should remain open unless their scope is moved or closed explicitly:

| Issue | Reason |
|---|---|
| #5 token provenance and source attribution dashboard | Hosted dashboard and long-term reporting belong to coding-agent-bridge. Headroom currently emits local producer events. |
| #6 true cache-aware context alignment / delta mode | Future Headroom advanced core. H009 is decision support, not delta mode. |
| #7 reversible conversation-history compaction | Future Headroom advanced core. Current coding-agent behavior protects stable conversation/provider-prefix content. |
| #10 public/remote proxy deployment mode | Hosted/shared operation needs bridge-side auth, namespace, deployment, and retrieve policy. |
| #12 multimodal and realtime-agent compression roadmap | Future Headroom advanced core; not implemented by H001-H009. |
| #18 CCR namespace, auth, and remote retrieve policy | SaaS remote authorization belongs to coding-agent-bridge. |
| #19 provenance ledger and OpenTelemetry attributes | Headroom local producer exists; hosted ledger contract and ingest remain bridge work. |
| #20 Langfuse / LiteLLM export for compression ledger | Hosted export management belongs to coding-agent-bridge. |
| #21 sandbox output adapter and provenance bridge | Mostly bridge/integration layer. |
| #22 headroom core vs coding-agent-bridge boundary | Keep open as boundary tracker until ownership is fully documented across repos. |

## Recommended Follow-up Comments

- #4: comment that Headroom-local SmartCrusher `<<ccr:...>>` marker parsing,
  injection, and retrieve-tool compatibility shipped in H001; close if the issue
  is local-only.
- #13: comment that the local marker/retrieve contract shipped across H001-H003,
  including shared parser validation, proxy normalization, malformed-marker
  rejection, controlled not-found behavior, and SQLite local backend; close only
  if remote/SaaS marker policy is explicitly out of scope.
- #8: comment that the Headroom-local SQLite durable backend shipped in H003.
  Leave open or split if the remaining Redis/Valkey wording is delegated to
  coding-agent-bridge.
- #19/#20/#21/#22: keep open until bridge-side hosted ingest/export/sandbox
  provenance and boundary decisions are updated in coding-agent-bridge.

## Boundary

Headroom owns local compression behavior, local CCR marker parsing/retrieve,
local SQLite CCR storage, deterministic local presets, local ledger event
production, and local/offline benchmarks. Hosted/team bridge operation, tenant
auth, API keys, remote retrieve policy, hosted ledger ingest, billing,
dashboards, deployment profiles, conformance authority, Redis/Valkey hosted CCR,
and hosted Langfuse/LiteLLM export belong to
`mishima-computing/coding-agent-bridge`.
