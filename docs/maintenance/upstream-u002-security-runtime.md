# U002 Security Runtime Intake

Date: 2026-06-05

Scope: selected upstream security/runtime correctness intake after U001.

## Target commits

Applied with `git cherry-pick -x`, in order:

| Upstream commit | Local commit | Title | Status |
|---|---|---|---|
| `78f3a4dd` | `09863115` | fix(security): patch loopback guard, retry None raise, blocking subprocess, and cache stats race | Applied |
| `38aefc1d` | `f7986576` | fix: use thread-local tree-sitter parsers to prevent unsendable panic | Applied |
| `6a70ea65` | `07a8c1c3` | test(code_compressor): add unsendable-panic repro and thread-local parser tests | Applied |
| `e8ecd088` | `6b62fec9` | fix(codex): fail open for proxy compression timeout | Applied |
| `fe50f9da` | `e1d1ec4d` | fix(ci): restore green lint gate on main | Applied |

No target commits were skipped.

## Touched areas

- Proxy loopback guard, retry validation, semantic cache stats, and async context-tool stats baseline.
- Neo4j local development credential defaults and `.env.example`.
- Code-aware compressor tree-sitter parser ownership, moving parser cache to thread-local storage.
- Codex/OpenAI proxy compression timeout handling, with Codex-specific fail-open behavior.
- Tests for thread-local tree-sitter parser behavior, Codex routing timeout behavior, and compression failure action.

## Conflict summary

No cherry-pick conflicts occurred.

`78f3a4dd` auto-merged `CHANGELOG.md` and `headroom/proxy/server.py`.
`e8ecd088` auto-merged `headroom/proxy/helpers.py`.

## Guardrails

- `upstream/main` was not merged.
- README marketing was not restored.
- No Trendshift badge was added.
- No `60B+` leaderboard language was restored.
- No `compresses everything` claim was restored.
- No release/version bump was added.
- No `mishima-computing/coding-agent-bridge` files were touched.
- No SaaS/control-plane/billing/dashboard/deployment code was added.

README guardrail check:

```text
README does not contain:
- 60B
- leaderboard
- Trendshift
- headroom stats
- compresses everything
```

The existing claim-audit line that says not to treat headline percentages as
guaranteed savings remains intentionally present as a negative boundary.

## Validation

Passed:

```text
tests/test_ccr_tool_injection.py: 57 passed
tests/test_proxy_ccr.py: 30 passed
tests/test_code_compressor_thread_safety.py tests/test_openai_codex_routing.py tests/test_proxy/test_compression_failure_action.py tests/test_provider_proxy_routes.py: 38 passed, 8 skipped
tests/test_coding_agent_presets.py: 12 passed
tests/test_provenance_ledger_emitter.py: 12 passed
tests/test_context_waste_benchmark.py: 14 passed
tests/test_cache_aware_net_savings.py: 12 passed
tests/test_openai_responses_compression_units.py: 6 passed
tests/test_proxy_openai_responses_bypass.py: 1 passed
tests/test_proxy_openai_responses_integration.py tests/test_openai_codex_ws_timings.py: 4 passed, 14 skipped
tests/test_transforms/test_code_compressor.py: 35 passed, 25 skipped
ruff check headroom tests: passed
ruff format --check headroom tests: passed
git diff --check: passed
```

Timed out / caveats:

```text
tests/test_openai_responses_context_compaction.py:
  full file timed out after 184s on Windows

Focused tests that also timed out after 124s each:
  tests/test_openai_responses_context_compaction.py::test_codex_input_list_payload_reaches_router_without_skip
  tests/test_openai_responses_context_compaction.py::test_codex_payload_with_only_messages_field_also_reaches_router
  tests/test_openai_responses_context_compaction.py::test_compression_pass_debug_logs_are_suppressed

Focused tests from the same file that passed:
  test_openai_responses_context_budget_breaks_out_static_and_live_buckets
  test_openai_tool_schema_compaction_preserves_invocation_shape
  test_openai_tool_schema_compaction_is_deterministic
  test_codex_payload_without_either_field_is_skipped
  test_content_router_retries_kompress_when_structured_strategy_noops
```

Full pytest was not run.

## Notes

The timed-out OpenAI Responses context compaction tests are existing long
payload router-path tests, not tests added by U002. They were run as additional
provider/proxy coverage because U002 touched the OpenAI handler. Directly
touched U002 tests and the required H001-H009 regression suites passed.
