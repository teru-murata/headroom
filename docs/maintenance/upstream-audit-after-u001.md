# Upstream Audit After U001

Date: 2026-06-05

Scope: audit-only recomputation of the current `main...upstream/main` divergence after
U001. This document does not merge `upstream/main`, does not cherry-pick commits, and
does not change implementation code.

## Current divergence

After `git fetch upstream`, the command capture before creating this audit
document returned:

```text
main...upstream/main:
  ahead 33
  behind 54
```

The previous reported `ahead 32 / behind 54` became `ahead 33 / behind 54`
because local `main` also contains `1ec61f1e Audit upstream README changes`,
which is not pushed to `origin/main` yet.

After committing this audit document locally, `git rev-list --left-right
--count main...upstream/main` reports:

```text
main...upstream/main:
  ahead 34
  behind 55
```

The classification below is based on the fetched `upstream/main` tip
`fe50f9da fix(ci): restore green lint gate on main`. The exact ahead count will
continue to change as local maintenance commits are added.

U001 remains content-covered even though the graph still reports upstream
commits as behind. Cherry-picks are new commits, so graph-based behind counts
do not shrink. Patch equivalence was checked with `git cherry -v main
upstream/main`; the U001 commits are reported with `-`.

Do not merge `upstream/main` wholesale. The diff would overwrite or remove many
fork-specific H001-H009 files, docs, validation logs, CCR marker/parser work,
SQLite CCR backend work, coding-agent preset work, telemetry ledger work, and
benchmark artifacts. Intake should stay selective.

## Method

Commands used:

```text
git status --short --branch --untracked-files=all
git fetch upstream
git log --oneline --left-right --cherry-pick main...upstream/main
git cherry -v main upstream/main
git log --oneline main..upstream/main
git diff --stat main..upstream/main
```

For each non-patch-equivalent upstream commit, I inspected the commit message,
touched files, and patch summary using `git show`.

## Already covered by U001

These upstream commits are patch-equivalent to local U001 cherry-picks and
should not be re-applied.

| Upstream commit | Title | Status |
|---|---|---|
| `07581b9e` | Fix: Upgrade litellm to 1.86.2 to remediate CVE-2026-42271 | Already covered |
| `0b9f11a2` | Fix: Update Next.js to 16.2.4 in docs/bun.lock to address GHSA-gx5p-jg67-6x7h | Already covered |
| `6eb6fb59` | fix(docs): update brace-expansion to 5.0.6 to remediate GHSA-jxxr-4gwj-5jf2 | Already covered |
| `db5d15f9` | Fix: Update Next.js to 16.2.6 in docs/package.json and package-lock.json | Already covered |
| `91e09372` | fix(docs): update bun.lock to next 16.2.6 | Already covered |
| `2f1538a6` | fix: decode/encode owned config, state and template assets as UTF-8 | Already covered |
| `d7973665` | fix(learn): finish gemini-flash-latest default model sweep | Already covered |
| `bdcfc322` | fix: ignore brackets inside JSON strings when splitting mixed content | Already covered |
| `0e551de9` | fix: correct tiktoken encoding for unknown gpt-4 model snapshots | Already covered |
| `e94a36cb` | test(codex): de-flake semaphore-tail ratio check on fast runners | Already covered |

## Commit classification

The following table covers upstream commits currently behind and not
patch-equivalent to local `main`.

| Commit | Title | Touched area | Classification | Recommended action | Rationale |
|---|---|---|---|---|---|
| `fe50f9da` | fix(ci): restore green lint gate on main | `headroom/proxy/helpers.py`, `headroom/transforms/code_compressor.py`, unsendable panic repro | Take carefully: follow-up lint for runtime fixes | Include with the security/tree-sitter/Codex runtime batch if those commits are taken. | This is a formatting and mypy follow-up for `38aefc1d` and `e8ecd088`; taking the runtime fixes without this may leave lint drift. |
| `5f5f261a` | Merge pull request #555 from ashishpatel26/fix/531-codex-wrap-fail-open-on-compression | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Changes are represented by `e8ecd088` plus follow-up `fe50f9da`. |
| `e87cece9` | Merge pull request #564 from mosatch/fix/thread-local-tree-sitter-parser | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Changes are represented by `38aefc1d`, `6a70ea65`, and follow-up `fe50f9da`. |
| `06d7cb9e` | Merge pull request #539 from neogenix/fix/security-and-reliability-blockers | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Changes are represented by `78f3a4dd`. |
| `78f3a4dd` | fix(security): patch loopback guard, retry None raise, blocking subprocess, and cache stats race | Proxy loopback guard, retry config, context tool stats, semantic cache stats, Neo4j env defaults | Take: security / correctness / portability | High-priority cherry-pick candidate, but test against H001-H009 proxy safety changes. | Adds loopback guard to `/debug/memory`, fixes retry `None` raise, avoids blocking subprocess work on the event loop, snapshots semantic cache stats, and removes hardcoded Neo4j password defaults. |
| `d8ac7472` | Merge pull request #601 from chopratejas/ci/intelligent-parallel-pipeline | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Changes are represented by CI commits `8062e7f7` through `2ea548a8`. |
| `2ea548a8` | ci: run relevance tests offline so fastembed doesn't 429 on cache HEAD | `.github/workflows/ci.yml` | Defer: CI pipeline | Defer unless fork CI is being realigned. | Useful upstream CI stability fix, but it changes CI structure rather than runtime behavior. |
| `51af24f7` | ci: cut over to the intelligent+parallel pipeline in ci.yml | `.github/workflows/ci.yml`, `.github/workflows/ci-fast.yml` | Defer: CI pipeline | Defer as a separate CI audit. | Large workflow cutover; not part of README/docs/provider runtime intake. |
| `6f0dc326` | ci: pin least-privilege GITHUB_TOKEN permissions (contents: read) | `.github/workflows/ci-fast.yml` | Take carefully: CI security | Consider as part of a dedicated CI permissions batch. | Least-privilege token permissions are useful, but the workflow itself is not yet adopted. |
| `a08a0bef` | ci: build the CI test wheel with a fast cargo profile | `.github/workflows/ci-fast.yml`, `Cargo.toml` | Defer: CI pipeline | Defer unless adopting upstream CI pipeline. | CI performance-only and may conflict with fork validation flow. |
| `9a16a59d` | ci: prefetch HF model once + run shards offline | `.github/workflows/ci-fast.yml` | Defer: CI pipeline | Defer unless adopting upstream CI pipeline. | Addresses upstream HF 429 pressure; not a local runtime fix. |
| `184b2904` | Merge pull request #540 from neogenix/docs/fix-stale-and-incorrect-docs | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Changes are represented by `0375f7f0` after branch merge. |
| `3599de8e` | Merge branch `main` into docs/fix-stale-and-incorrect-docs | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Branch merge only; no direct action. |
| `322d02ef` | ci: copy built `_core.so` into source tree so sharded tests import it | `.github/workflows/ci-fast.yml` | Defer: CI pipeline | Defer unless adopting upstream CI pipeline. | Workflow-specific fix. |
| `8062e7f7` | ci: add experimental intelligent+parallel pipeline | `.github/workflows/ci-fast.yml` | Defer: CI pipeline | Defer as CI audit, not U002. | Large workflow addition. |
| `6775e650` | ci(release-please): set versioned PR title pattern to fix tagging jam | `.release-please-config.json` | Defer: release automation | Defer. | Release automation is not part of current fork intake. |
| `8006293e` | Merge pull request #594 from release-please branch | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Represents release bump `f7c25522`. |
| `f7c25522` | chore: release main | Version files and changelog | Defer: release/version bump | Ignore for now. | Do not take release/version bump unless the fork is preparing a release. |
| `e8ecd088` | fix(codex): fail open for proxy compression timeout | OpenAI handler, compression failure action, Codex routing tests | Take carefully: provider/proxy runtime behavior | Candidate for a runtime batch with targeted Codex/OpenAI proxy tests. | Codex timeout behavior is user-facing and may prevent direct-proxy failures, but it changes fail-open/refuse policy for Codex only and must be checked against local safety boundaries. |
| `f4dff9b4` | Merge pull request #576 from copilot subscription auth | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Changes are represented by Copilot commits `ff4a0c6b`, `72da4612`, `5904e3fc`, and `6ed43027`. |
| `6ed43027` | style(copilot): ruff-format test_copilot_auth.py | Copilot auth tests | Take carefully: Copilot auth | Include with Copilot batch if prior Copilot commits are taken. | Formatting follow-up for Copilot tests. |
| `a5ff663a` | Merge pull request #579 from issue-561-anthropic-api-url | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Changes are represented by `b1d1f8cd` and `b9d36db7`. |
| `b9d36db7` | docs(proxy): document Anthropic API URL overrides | `wiki/proxy.md` | Docs/manual rewrite | Manual extract if wiki docs are kept. | Factual proxy docs change, but wiki/docs structure differs from fork docs policy. |
| `b1d1f8cd` | docs(proxy): document ANTHROPIC_TARGET_API_URL | `docs/content/docs/proxy.mdx`, `wiki/proxy.md` | Docs/manual rewrite | Manual extract into fork proxy docs if missing. | Useful factual env var documentation; avoid wholesale upstream docs wording. |
| `f58340d1` | Merge pull request #573 from OpenAI Responses parallel units | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Changes are represented by `d160f391`, `4c86826e`, and `cfcaf0e3`. |
| `5904e3fc` | docs(copilot): add cross-platform subscription testing guide + issue template | Copilot testing doc and issue template | Take carefully: Copilot auth docs/manual rewrite | Include only with Copilot auth batch, possibly manual rewrite. | Useful test guidance, but may overstate platform validation if not rewritten for fork boundaries. |
| `72da4612` | fix(copilot): deterministic subscription token handoff to the proxy | `headroom/cli/wrap.py`, Copilot tests | Take carefully: Copilot auth | Include with Copilot auth batch. | Follows `ff4a0c6b`; improves token handoff determinism and adds smoke tests. |
| `cfcaf0e3` | Rename tool output compression parallelism env | OpenAI handler and OpenAI Responses tests | Take carefully: provider/proxy runtime behavior | Include with OpenAI Responses batch. | Renames env var to `HEADROOM_TOOL_OUTPUT_COMPRESSION_PARALLELISM`; should move with the feature it configures. |
| `4c86826e` | Cover OpenAI Responses unit cache edge cases | OpenAI Responses tests | Take carefully: provider/proxy runtime behavior | Include with OpenAI Responses batch. | Test coverage for cache behavior introduced by `d160f391`. |
| `d160f391` | Speed up OpenAI Responses compression units | OpenAI handler and OpenAI Responses tests | Take carefully: provider/proxy runtime behavior | Include as OpenAI Responses performance/cache batch. | Adds unit cache, bounded parallelism, duplicate work collapse, and T3 replay regression coverage. |
| `bd0e8456` | Merge branch `chopratejas:main` into thread-local parser branch | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Branch merge only; no direct action. |
| `982d01b9` | Merge pull request #541 from learn gemini default | Merge commit | Direct merge commit / no direct action | No action. | U001 already covered the underlying `d7973665` change. |
| `6a70ea65` | test(code_compressor): add unsendable-panic repro and thread-local parser tests | Code compressor tests and repro script | Take: correctness / portability | Include with `38aefc1d`. | Tests the tree-sitter unsendable parser panic and thread-local parser behavior. |
| `38aefc1d` | fix: use thread-local tree-sitter parsers to prevent unsendable panic | `headroom/transforms/code_compressor.py` | Take: correctness / portability | High-priority candidate after security batch. | Fixes a concrete multi-threaded crash path in code-aware compression with tree-sitter >= 0.23. |
| `92075b95` | Merge pull request #536 from UTF-8 owned assets | Merge commit | Direct merge commit / no direct action | No action. | U001 already covered the underlying `2f1538a6` change. |
| `6272de63` | Merge pull request #560 from README perf command | Merge commit | Direct merge commit / no direct action | No action. | Local `1ec61f1e` manually covered the README command change. |
| `d99df78b` | docs: fix get started perf command | README | Already covered manually | Do not cherry-pick. | Local `1ec61f1e` changed `headroom stats` to `headroom perf` in the fork README and documented the decision. |
| `ff4a0c6b` | fix(copilot): support subscription auth through Headroom | Copilot auth, wrap CLI, proxy, platform auth helpers, tests, README | Take carefully: Copilot auth | Separate Copilot auth batch only. | Valuable but heavy credential/token handling. Needs Windows/macOS/Linux secret boundary review and targeted auth tests. |
| `378d77e7` | fix: update dashboard doc link | Dashboard template | Take: correctness / docs link | Safe small cherry-pick candidate. | Updates dashboard docs link from GitHub Pages to Vercel docs. Low risk. |
| `55579445` | fix(docs): mkdocs configuration to build with correct folder | `mkdocs.yml`, test formatting | Docs/manual rewrite | Likely skip or defer. | Fork docs use `docs/` and `fumadocs-mdx`; setting `docs_dir: wiki` may add tooling confusion. Needs docs tooling decision before adoption. |
| `a6a09e6c` | Merge pull request #522 from Leathal1/main | Merge commit | Direct merge commit / no direct action | Do not cherry-pick directly. | Includes README commits and already-covered lockfile work. |
| `0375f7f0` | docs: fix stale API references, retired class imports, and incorrect examples | README, docs pages, llms, provider route tests | Docs/manual rewrite | Review and extract factual docs fixes manually. | Removes stale `RollingWindowConfig` and retired public API references and updates extras list; useful but must be reconciled with M001/H001-H009 fork docs. |
| `a359dae3` | Add Trendshift badge to README | README | Skip: README marketing / badges / vanity | Reject. | Upstream vanity badge points to `chopratejas/headroom` and conflicts with fork README boundaries. |
| `1e8beb02` | Updated README | README | Already covered / claim reduction | No action. | Removes live leaderboard `60B+` community line. The fork already removed this class of claim. |
| `9f8b621e` | Updated README | README | Already covered / claim reduction | No action. | Removes `60B+ tokens saved` badge and leaderboard block. The fork already removed equivalent claims. |

## Recommended batches

### U002: high-priority security and runtime correctness

Recommended next implementation batch:

```text
78f3a4dd  fix(security): patch loopback guard, retry None raise, blocking subprocess, and cache stats race
38aefc1d  fix: use thread-local tree-sitter parsers to prevent unsendable panic
6a70ea65  test(code_compressor): add unsendable-panic repro and thread-local parser tests
e8ecd088  fix(codex): fail open for proxy compression timeout
fe50f9da  fix(ci): restore green lint gate on main
```

Reason: these are security/correctness/runtime fixes discovered after the old
A2 plan. They should come before docs-only A2 cleanup because they affect
local safety, proxy behavior, and compression stability.

Expected focused validation:

```text
tests/test_proxy/test_compression_failure_action.py
tests/test_openai_codex_routing.py
tests/test_code_compressor_thread_safety.py
tests/test_proxy_ccr.py
tests/test_ccr_tool_injection.py
ruff check headroom tests
ruff format --check headroom tests
git diff --check
```

### U003: OpenAI Responses performance/cache batch

```text
d160f391  Speed up OpenAI Responses compression units
4c86826e  Cover OpenAI Responses unit cache edge cases
cfcaf0e3  Rename tool output compression parallelism env
```

Reason: useful but provider-runtime-specific. Keep separate from U002 so
OpenAI Responses cache/parallelism behavior can be tested in isolation.

### U004: Copilot subscription auth batch

```text
ff4a0c6b  fix(copilot): support subscription auth through Headroom
72da4612  fix(copilot): deterministic subscription token handoff to the proxy
5904e3fc  docs(copilot): add cross-platform subscription testing guide + issue template
6ed43027  style(copilot): ruff-format test_copilot_auth.py
```

Reason: valuable but heavier credential/secret/token handling. Treat as its
own auth/security batch and rewrite docs to avoid overstating platform
validation.

### U005: docs/config manual fixes

```text
0375f7f0  docs: fix stale API references, retired class imports, and incorrect examples
b1d1f8cd  docs(proxy): document ANTHROPIC_TARGET_API_URL
b9d36db7  docs(proxy): document Anthropic API URL overrides
378d77e7  fix: update dashboard doc link
```

Reason: factual docs/link fixes exist, but docs should be manually reconciled
with M001/H001-H009 fork boundaries. `378d77e7` is small and can be cherry-picked
or manually patched. Proxy env docs should be copied only where they fit fork docs.

### CI/deployment pipeline audit

```text
8062e7f7  ci: add experimental intelligent+parallel pipeline
322d02ef  ci: copy built _core.so into source tree so sharded tests import it
9a16a59d  ci: prefetch HF model once + run shards offline
a08a0bef  ci: build the CI test wheel with a fast cargo profile
6f0dc326  ci: pin least-privilege GITHUB_TOKEN permissions
51af24f7  ci: cut over to the intelligent+parallel pipeline
2ea548a8  ci: run relevance tests offline
```

Reason: these may be useful for upstream CI reliability, but they are a
separate workflow decision and should not be mixed with runtime or docs intake.

### Skip list

```text
a359dae3  Add Trendshift badge to README
```

Reason: upstream vanity/marketing badge.

### Defer list

```text
f7c25522  chore: release main
6775e650  ci(release-please): set versioned PR title pattern to fix tagging jam
55579445  fix(docs): mkdocs configuration to build with correct folder
```

Reason: release/version bump is not needed now. `mkdocs.yml docs_dir: wiki`
should be deferred unless the fork decides to support upstream MkDocs alongside
the current `docs/` Fumadocs flow.

## README extraction table

README commits were reviewed separately and should not be cherry-picked
wholesale.

| Commit | README change summary | Useful? | Decision | Reason |
|---|---|---|---|---|
| `9f8b621e` | Removes `60B+ tokens saved` badge and community leaderboard image block. | Yes, as claim reduction. | Already covered | M001 removed equivalent guarantee/leaderboard surface in the fork README. |
| `1e8beb02` | Removes Community line `Live leaderboard -- 60B+ tokens saved and counting.` | Yes, as claim reduction. | Already covered | Current fork README has no live leaderboard line. |
| `a359dae3` | Adds Trendshift badge for `chopratejas/headroom`. | No. | Reject | Upstream vanity badge conflicts with fork README boundaries. |
| `d99df78b` | Changes Get started command from `headroom stats` to `headroom perf`. | Yes. | Already manually covered | Local `1ec61f1e` applied this one-line README fix and documented the audit. |
| `0375f7f0` | Adds extras list entries such as `[code]`, `[memory]`, `[relevance]`, `[image]`; also changes stale docs references. | Partially. | Manual rewrite | Factual extras/API cleanup may be useful, but the README/docs patch must be reconciled with M001 shipped-state and claim-audit wording. |
| `ff4a0c6b` | Adds Copilot subscription mode README section. | Partially, only if Copilot auth batch is adopted. | Manual rewrite with U004 | Must avoid overstating platform validation or implying SaaS/control-plane behavior. |

Current README remains free of `60B`, leaderboard, Trendshift badge,
`headroom stats`, and `compresses everything` wording.

## Risks and caveats

- Full pytest was not run for this audit.
- U001's heavy scheduler test caveat remains: `tests/test_codex_ws_compression_scheduler.py::test_concurrent_compression_has_no_semaphore_tail` timed out after 184s on Windows during U001 validation.
- `git diff --stat main..upstream/main` is not an intake plan. It shows many
  apparent deletions of fork-specific files because the histories diverged. This
  is another reason not to merge `upstream/main` wholesale.
- Docs tooling differs: the fork currently validates docs from `docs/` with
  `npm exec fumadocs-mdx`; upstream still has MkDocs/wiki-related changes.
- README must keep M001 claim-audit boundaries: no guaranteed savings, no
  upstream leaderboard, no "compresses everything" headline, and no hosted SaaS
  implementation claim inside Headroom.
- Copilot subscription auth touches credential and OS secret flows. It needs
  separate targeted testing and careful doc wording.
- OpenAI Responses cache/parallelism changes touch provider runtime behavior and
  should be validated separately from docs/config changes.

## Proposed next task

Do not start the old U002 docs/config batch yet.

The next implementation task should be:

```text
U002: cherry-pick high-priority upstream security and runtime correctness fixes

Candidate commits:
78f3a4dd
38aefc1d
6a70ea65
e8ecd088
fe50f9da
```

Rationale: current upstream/main now contains new security/correctness fixes
that should be evaluated before docs/config cleanup. Keep README/docs marketing
commits out of this batch, preserve H001-H009 local fork changes, and do not
merge `upstream/main`.
