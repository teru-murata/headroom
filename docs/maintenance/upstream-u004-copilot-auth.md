# U004 Copilot Subscription Auth Intake

Date: 2026-06-05

Scope: selected upstream Copilot subscription auth and token handoff intake after
U001, U002, and U003.

## Preflight

After `git fetch upstream`, the task started from:

```text
main...upstream/main:
  ahead 44
  behind 61
```

`upstream/main` was not merged.

Current divergence after the U004 cherry-picks, before pushing the local
follow-up commits, was:

```text
main...upstream/main:
  ahead 49
  behind 63
```

The remaining behind count is expected for selective cherry-pick workflow.
Patch-equivalent U004 commits are recorded with `git cherry -v main
upstream/main`.

## Candidate commits inspected

| Upstream commit | Title | Decision | Reason |
|---|---|---|---|
| `ff4a0c6b` | fix(copilot): support subscription auth through Headroom | Cherry-picked | Main Copilot subscription auth implementation. |
| `72da4612` | fix(copilot): deterministic subscription token handoff to the proxy | Cherry-picked | Keeps wrapper-validated token consistent with proxy upstream auth. |
| `5904e3fc` | docs(copilot): add cross-platform subscription testing guide + issue template | Cherry-picked | Focused Copilot testing docs and issue template; adjusted fork links and token placeholders. |
| `6ed43027` | style(copilot): ruff-format test_copilot_auth.py | Cherry-picked | Formatting companion for Copilot auth tests. |
| `18925b8c` | fix(copilot): restore generic endpoint for non-subscription OAuth (#610) (#612) | Cherry-picked | Direct Copilot auth follow-up for generic endpoint routing and API URL override behavior. |
| `6f0dc326` | ci: pin least-privilege GITHUB_TOKEN permissions | Skipped | CI permissions scope, not Copilot subscription auth. |
| `6dfcaa83` | fix(wrap): report unbindable proxy ports (#602) | Skipped | Wrap/proxy port reporting scope, not Copilot auth. |
| `2170a1b4` | fix(proxy): fail-open on corrupt golden bytes instead of RuntimeError (#603) | Skipped | Proxy golden-byte handling scope, not Copilot auth. |

## Applied commits

Applied with `git cherry-pick -x`, in order:

| Upstream commit | Local commit | Title |
|---|---|---|
| `ff4a0c6b` | `5bbd9ba7` | fix(copilot): support subscription auth through Headroom |
| `72da4612` | `b8fd934c` | fix(copilot): deterministic subscription token handoff to the proxy |
| `5904e3fc` | `d8bc99c0` | docs(copilot): add cross-platform subscription testing guide + issue template |
| `6ed43027` | `d5dfb569` | style(copilot): ruff-format test_copilot_auth.py |
| `18925b8c` | `89525779` | fix(copilot): restore generic endpoint for non-subscription OAuth (#610) (#612) |

Local follow-up changes:

- Replaced real-looking fake token values with GitHub OAuth/PAT-style or
  provider-key-style prefixes in changed tests/docs with obvious placeholders
  such as `fake-*`, `test-provider-api-key`, and `<provider-api-key>`.
- Rewrote new Copilot test-report links from upstream to this fork.
- Kept the README Copilot section conservative by describing macOS validation as
  upstream smoke testing and Linux/Windows/Docker/CI paths as still requiring
  real OS validation.

## Touched files

- `.github/ISSUE_TEMPLATE/copilot-subscription-test-report.md`
- `README.md`
- `TESTING-copilot-subscription.md`
- `headroom/cli/wrap.py`
- `headroom/copilot_auth.py`
- `headroom/copilot_linux_secret.py`
- `headroom/copilot_macos_keychain.py`
- `headroom/proxy/server.py`
- `tests/test_cli/test_wrap_copilot.py`
- `tests/test_cli/test_wrap_persistent.py`
- `tests/test_copilot_auth.py`
- `tests/test_copilot_linux_secret.py`
- `tests/test_copilot_macos_keychain.py`
- `tests/test_copilot_subscription_smoke.py`
- `wiki/integration-guide.md`

## Conflict summary

No cherry-pick conflicts occurred.

`ff4a0c6b` auto-merged `README.md` and `headroom/proxy/server.py`.

## Security review

- No real Copilot/GitHub/API tokens were added.
- Test values that resembled real token prefixes were replaced with obvious
  fake placeholders.
- Runtime token handoff passes the wrapper-validated token to the proxy
  subprocess environment only; it does not mutate the parent `os.environ`.
- The proxy receives the token as `GITHUB_COPILOT_API_TOKEN`, keeping the
  upstream auth token deterministic for that proxy instance.
- macOS Keychain and Linux Secret Service helpers are optional and return
  `None` off-platform or when tooling is unavailable.
- Linux `secret-tool` lookup is subprocess-based and covered by hermetic tests,
  not real user secret stores.
- Docs instruct users to redact secrets in reports.
- Runtime bearer header construction and OAuth JSON keys are expected code
  paths, not committed secrets.

Secret grep sanity check over changed U004 files:

```text
checked:
  GitHub App, OAuth, session, PAT, and GitHub PAT style prefixes
  provider-key style prefix
  Slack bot token style prefix
  old explicit Copilot token placeholder
  bearer authorization header text
  OAuth JSON key names

remaining hits:
  headroom/cli/wrap.py: hyphenated word false positive for the provider-key prefix
  README.md: negative boundary saying headline percentages are not guaranteed savings
  headroom/copilot_auth.py: OAuth access token JSON key

No real-looking token values remain in the U004 changed tests/docs.
```

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
tests/test_copilot_auth.py
tests/test_copilot_linux_secret.py
tests/test_copilot_macos_keychain.py
tests/test_copilot_subscription_smoke.py
tests/test_cli/test_wrap_copilot.py:
  68 passed

tests/test_cli/test_wrap_persistent.py
tests/test_coding_agent_presets.py
tests/test_provenance_ledger_emitter.py
tests/test_context_waste_benchmark.py
tests/test_cache_aware_net_savings.py
tests/test_ccr_tool_injection.py
tests/test_proxy_ccr.py:
  149 passed, 3 warnings

python -m ruff check headroom tests:
  passed

python -m ruff format --check headroom tests:
  passed

git diff --check:
  passed, CRLF warnings only

npm exec fumadocs-mdx from docs/:
  passed
```

`ruff` was not on the PowerShell PATH in this environment, so validation used
the bundled runtime as `python -m ruff`.

Full pytest was not run.

## Platform caveats

- This Windows environment cannot validate real macOS Keychain behavior.
- This Windows environment cannot validate real Linux Secret Service /
  `secret-tool` behavior.
- Windows Credential Manager behavior is covered only by hermetic/off-platform
  tests here.
- Real Copilot subscription end-to-end validation still requires a user with a
  Copilot subscription and OS credential material.
