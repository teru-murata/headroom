# U003 OpenAI Responses Runtime Intake

Date: 2026-06-05

Scope: selected upstream OpenAI Responses runtime/cache/performance intake after
U001 and U002.

## Preflight

After `git fetch upstream`, the task started from:

```text
main...upstream/main:
  ahead 40
  behind 55
```

`upstream/main` was not merged.

New upstream commits existed after U002, including README/enterprise docs and a
Copilot OAuth endpoint regression fix, but none were direct OpenAI Responses
runtime/cache/performance follow-ups. They were not included in U003.

## Candidate commits inspected

| Upstream commit | Title | Decision | Reason |
|---|---|---|---|
| `d160f391` | Speed up OpenAI Responses compression units | Cherry-picked | Adds OpenAI Responses unit cache, duplicate-output reuse, bounded parallelism, and T3 replay coverage. |
| `4c86826e` | Cover OpenAI Responses unit cache edge cases | Cherry-picked | Adds cache edge-case coverage for the U003 runtime change. |
| `cfcaf0e3` | Rename tool output compression parallelism env | Cherry-picked | Renames the feature env var to `HEADROOM_TOOL_OUTPUT_COMPRESSION_PARALLELISM`; belongs with the runtime change. |
| `f58340d1` | Merge pull request #573 from OpenAI Responses parallel units | Skipped | Merge commit; individual commits above were used. |
| `18925b8c` | fix(copilot): restore generic endpoint for non-subscription OAuth | Skipped | Copilot auth scope, not OpenAI Responses performance/cache. |
| `63143608` | fix readme | Skipped | README scope; not U003. |
| `3df22cad` | docs: add enterprise.md | Skipped | Docs/enterprise scope; not U003. |
| `e6f788fb` | docs: add link to enterprisemd in README | Skipped | README/docs scope; not U003. |

## Applied commits

Applied with `git cherry-pick -x`, in order:

| Upstream commit | Local commit | Title |
|---|---|---|
| `d160f391` | `5495db1e` | Speed up OpenAI Responses compression units |
| `4c86826e` | `d5ec0385` | Cover OpenAI Responses unit cache edge cases |
| `cfcaf0e3` | `702becdd` | Rename tool output compression parallelism env |

## Touched files

- `headroom/proxy/handlers/openai.py`
- `tests/test_openai_responses_compression_units.py`
- `tests/test_openai_responses_t3_replay_regression.py`

## Conflict summary

No cherry-pick conflicts occurred.

`d160f391` and `cfcaf0e3` auto-merged `headroom/proxy/handlers/openai.py`.

## Guardrails

- `upstream/main` was not merged.
- README marketing was not restored.
- No Trendshift badge was added.
- No `60B+` leaderboard language was restored.
- No `compresses everything` claim was restored.
- No release/version bump was added.
- No `mishima-computing/coding-agent-bridge` files were touched.
- No SaaS/control-plane/billing/dashboard/deployment code was added.
- H001-H009 local behavior remains in scope and was covered by targeted
  regressions.

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
tests/test_openai_responses_compression_units.py: 12 passed
tests/test_openai_responses_t3_replay_regression.py: 2 passed
tests/test_provider_proxy_routes.py: 12 passed
tests/test_proxy_ccr.py: 30 passed
tests/test_ccr_tool_injection.py: 57 passed
tests/test_coding_agent_presets.py tests/test_provenance_ledger_emitter.py: 24 passed
tests/test_context_waste_benchmark.py tests/test_cache_aware_net_savings.py: 26 passed
tests/test_openai_responses_context_compaction.py focused short subset: 5 passed
ruff check headroom tests: passed
ruff format --check headroom tests: passed
git diff --check: passed
```

Timed out / caveats:

```text
Known Windows timeout from U002 remains:
  tests/test_openai_responses_context_compaction.py full file timed out in U002 after 184s.

Focused tests that timed out in U003 after 128s each:
  tests/test_openai_responses_context_compaction.py::test_codex_input_list_payload_reaches_router_without_skip
  tests/test_openai_responses_context_compaction.py::test_codex_payload_with_only_messages_field_also_reaches_router
  tests/test_openai_responses_context_compaction.py::test_compression_pass_debug_logs_are_suppressed
```

Full pytest was not run.

## Notes

The U003-targeted OpenAI Responses unit cache/parallelism tests and T3 replay
tests completed successfully. The timed-out context compaction tests are the
same existing long payload-router tests documented during U002; they were
rechecked because U003 touches `headroom/proxy/handlers/openai.py`.
