# U006 Small Runtime Correctness Intake

Date: 2026-06-06

Scope: selected upstream runtime correctness intake after U005 residual audit.
This batch imports two small fixes only:

- clearer reporting for unbindable local proxy ports
- fail-open recovery for corrupt sticky tool / CCR golden bytes

## Preflight

After `git fetch upstream`, the task started from:

```text
main...upstream/main:
  ahead 51
  behind 63
```

`upstream/main` was not merged.

## Target Commits

| Upstream commit | Title | Decision | Reason |
|---|---|---|---|
| `6dfcaa83` | fix(wrap): report unbindable proxy ports (#602) | Cherry-picked | Small local proxy UX/runtime correctness fix. Reports reserved or otherwise unbindable loopback ports before spawning the proxy subprocess. |
| `2170a1b4` | fix(proxy): fail-open on corrupt golden bytes instead of RuntimeError (#603) | Cherry-picked | Runtime reliability fix. Corrupt sticky tool or CCR golden bytes no longer permanently break a session with `RuntimeError`; the path logs and skips/regenerates instead. |

No extra upstream commits were included. README, release/version, enterprise
support docs, and broad CI pipeline commits remain out of scope per U005.

## Applied Commits

Applied with `git cherry-pick -x`, in order:

| Upstream commit | Local commit | Title |
|---|---|---|
| `6dfcaa83` | `7657492c` | fix(wrap): report unbindable proxy ports (#602) |
| `2170a1b4` | `0e21e0c3` | fix(proxy): fail-open on corrupt golden bytes instead of RuntimeError (#603) |

`git cherry -v main upstream/main` reports both upstream commits as
patch-equivalent (`-`) after the cherry-picks.

## Touched Files

- `headroom/cli/wrap.py`
- `headroom/proxy/helpers.py`
- `headroom/proxy/server.py`
- `tests/test_cli/test_wrap_persistent.py`
- `tests/test_corrupt_golden_bytes_recovery.py`

## Conflict Summary

No cherry-pick conflicts occurred.

`6dfcaa83` auto-merged `headroom/cli/wrap.py`.
`2170a1b4` auto-merged `headroom/proxy/server.py`.

## Behavior Notes

- `_ensure_proxy` now checks whether the requested loopback port can be bound
  before starting the proxy subprocess. When the port is unavailable, it raises
  an actionable Click error that suggests a nearby alternate port.
- Sticky memory tool replay now logs corrupt golden bytes at error level and
  skips the corrupt entry rather than raising `RuntimeError`.
- Sticky CCR tool replay now logs corrupt golden bytes at error level and
  regenerates a fresh CCR definition rather than raising `RuntimeError`.
- Inbound proxy abort logging now uses error level with traceback context.

These are fail-open runtime reliability changes and do not alter local CCR
marker semantics, SQLite backend behavior, CodingAgentPreset behavior,
provenance ledger semantics, context waste benchmarking, or cache-aware
net-savings behavior.

## Guardrails

- `upstream/main` was not merged.
- Only the two U006 runtime correctness commits were cherry-picked.
- Both cherry-picks used `-x`.
- README marketing was not restored.
- No Trendshift badge was added.
- No `60B+` leaderboard language was restored.
- No `compresses everything` claim was restored.
- No release/version bump was added.
- No `mishima-computing/coding-agent-bridge` files were touched.
- No SaaS/control-plane/billing/dashboard/deployment code was added.
- H001-H009 behavior remains in scope and was covered by targeted regressions.

README guardrail check:

```text
Forbidden positive claims absent:
  60B
  leaderboard
  Trendshift
  headroom stats
  compresses everything
  production SaaS proxy
  hosted dashboard
  Redis backend shipped
  net savings as billing-grade or invoice basis
  conversation history compaction as shipped
  multimodal/realtime compression as shipped

Intentional negative/guardrail wording present:
  "Do not treat headline percentages as guaranteed savings..."
  "not invoice accounting"
  "not an invoice denominator"
```

## Validation

Passed:

```text
tests/test_corrupt_golden_bytes_recovery.py
tests/test_cli/test_wrap_persistent.py
tests/test_provider_proxy_routes.py:
  34 passed, 1 warning

tests/test_proxy_ccr.py
tests/test_ccr_tool_injection.py:
  87 passed, 3 warnings

tests/test_coding_agent_presets.py
tests/test_provenance_ledger_emitter.py
tests/test_context_waste_benchmark.py
tests/test_cache_aware_net_savings.py
tests/test_cli/test_wrap_copilot.py:
  70 passed

python -m ruff check headroom tests:
  passed

python -m ruff format --check headroom tests:
  passed

git diff --check:
  passed
```

No Windows timeout occurred during U006 validation.

Full pytest was not run.

## Recommendation

U006 covers the two small runtime correctness commits identified by U005. After
this batch, upstream intake can stop for now unless a separate docs-only or
CI-only audit is explicitly requested.
