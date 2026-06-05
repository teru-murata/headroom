# Upstream Residual Audit After U004

Date: 2026-06-05

Scope: audit-only review of remaining `main...upstream/main` divergence after
U001 through U004. No upstream merge and no cherry-pick were performed for this
task.

## 1. Current Divergence

After `git fetch upstream`, the current divergence was:

```text
main...upstream/main:
  ahead 50
  behind 63
```

This repository uses selective cherry-pick intake. As a result, commits can
still appear in the behind count even when their patches are already represented
locally. Patch equivalence was checked with `git cherry -v main upstream/main`.

`git log --oneline --left-right --cherry-pick main...upstream/main` showed the
remaining non-equivalent upstream side as mostly merge commits, README/docs,
release/CI automation, and two small runtime correctness candidates:

```text
2170a1b4 fix(proxy): fail-open on corrupt golden bytes instead of RuntimeError (#603)
6dfcaa83 fix(wrap): report unbindable proxy ports (#602)
```

The full `git diff --stat main..upstream/main` is large and misleading as an
intake signal because a full upstream merge would delete or rewrite many fork
H001-H009 and M001 files. That is expected and reinforces the no-merge policy.

## 2. Completed Intake Batches

| Batch | Status | Scope |
|---|---|---|
| U001 | Completed and pushed | Security and small correctness fixes. |
| U002 | Completed and pushed | Security/runtime correctness fixes. |
| U003 | Completed and pushed | OpenAI Responses runtime/cache/performance fixes. |
| U004 | Completed and pushed | Copilot subscription auth and token handoff fixes. |

All four batches used selected `git cherry-pick -x` commits. `upstream/main`
was not merged.

## 3. Method

Commands run:

```text
git status
git fetch upstream
git log --oneline --left-right --cherry-pick main...upstream/main
git cherry -v main upstream/main
git log --oneline main..upstream/main
git diff --stat main..upstream/main
git log --oneline --merges main..upstream/main
git log --oneline --no-merges --right-only --cherry-pick main...upstream/main
git show --stat --name-status <remaining commit>
```

Additional focused patch inspection was run for likely runtime or docs
candidates:

```text
git show --patch 6dfcaa83 -- headroom/cli/wrap.py tests/test_cli/test_wrap_persistent.py
git show --patch 2170a1b4 -- headroom/proxy/helpers.py headroom/proxy/server.py tests/test_corrupt_golden_bytes_recovery.py
git show --patch 9f8b621e 1e8beb02 63143608 d99df78b -- README.md
git show --patch 3df22cad e6f788fb -- ENTERPRISE.md README.md
git show --patch b1d1f8cd b9d36db7 -- docs/content/docs/proxy.mdx wiki/proxy.md
```

Patch equivalence:

- `git cherry -v main upstream/main` marks already represented upstream patches
  with `-`.
- Remaining actionable upstream patches are marked `+`.
- U001, U002, U003, and U004 commits were confirmed as `-` where applicable.

## 4. Remaining Commit Classification Table

The table below covers every remaining non-equivalent upstream non-merge commit
reported by `git log --no-merges --right-only --cherry-pick
main...upstream/main`.

| SHA | Title | Touched area | Classification | Recommended action | Rationale |
|---|---|---|---|---|---|
| `2170a1b4` | fix(proxy): fail-open on corrupt golden bytes instead of RuntimeError (#603) | `headroom/proxy/helpers.py`, `headroom/proxy/server.py`, corrupt golden bytes tests | take-carefully: runtime correctness | Candidate U006 runtime intake | Real proxy recovery fix. Prevents permanently broken sessions after corrupt sticky tool/CCR golden bytes. Should be cherry-picked separately and validated against H001/H002 CCR/proxy behavior. |
| `6dfcaa83` | fix(wrap): report unbindable proxy ports (#602) | `headroom/cli/wrap.py`, persistent wrap tests | take-carefully: runtime correctness | Candidate U006 runtime intake | Small Windows-relevant correctness fix. Reports reserved/unbindable loopback ports before spawning proxy. Low scope but should be validated with wrap persistent tests. |
| `e6f788fb` | docs: add link to enterprisemd in README | README enterprise link | defer: advanced feature not aligned with fork roadmap | Do not apply now | Links to upstream enterprise/support surface. Fork README claim boundaries should not add enterprise support surface without an explicit fork decision. |
| `3df22cad` | docs: add enterprise.md | `ENTERPRISE.md` | defer: advanced feature not aligned with fork roadmap | Do not apply now | Adds enterprise support contact for upstream `headroomlabs.ai`. Not a headroom local-core fix and not appropriate for current fork public surface. |
| `63143608` | fix readme | README | skip: upstream README marketing / badge / leaderboard / vanity | Reject | Reintroduces Trendshift badge and "compresses everything" wording. Conflicts with M001 claim-audit boundaries. |
| `2ea548a8` | ci: run relevance tests offline so fastembed does not 429 on cache HEAD | `.github/workflows/ci.yml` | investigate: unclear scope | Defer to separate CI-only audit | CI-only fix inside upstream parallel pipeline. Could be useful, but it belongs to a full CI workflow review, not residual runtime intake. |
| `51af24f7` | ci: cut over to the intelligent+parallel pipeline in ci.yml | `.github/workflows/ci.yml`, deletes `ci-fast.yml` | investigate: unclear scope | Defer to separate CI-only audit | Broad CI rewrite. Risky for fork because local H001-H009 tests/docs differ from upstream. |
| `6f0dc326` | ci: pin least-privilege GITHUB_TOKEN permissions | `.github/workflows/ci-fast.yml` | investigate: unclear scope | Defer to CI audit | Security-positive in principle, but targets upstream `ci-fast.yml` pipeline that is not being imported as a whole. |
| `a08a0bef` | ci: build the CI test wheel with a fast cargo profile | `.github/workflows/ci-fast.yml`, `Cargo.toml` | investigate: unclear scope | Defer to CI audit | CI performance change plus Cargo profile. Should not be applied without adopting/reviewing the upstream CI pipeline. |
| `9a16a59d` | ci: prefetch HF model once + run shards offline | `.github/workflows/ci-fast.yml` | investigate: unclear scope | Defer to CI audit | CI network flake reduction, but depends on upstream sharded CI design. |
| `322d02ef` | ci: copy built `_core.so` into source tree | `.github/workflows/ci-fast.yml` | investigate: unclear scope | Defer to CI audit | CI import-path fix for upstream wheel/shard workflow. Not independently useful unless taking the pipeline. |
| `8062e7f7` | ci: add experimental intelligent+parallel pipeline | `.github/workflows/ci-fast.yml` | investigate: unclear scope | Defer to CI audit | Adds an experimental CI pipeline. Too broad for residual upstream intake. |
| `6775e650` | ci(release-please): set versioned PR title pattern | `.release-please-config.json` | skip: release/version bump | Skip | Release automation scope. Fork release policy has not been requested here. |
| `f7c25522` | chore: release main | release manifest, changelog, package versions | skip: release/version bump | Skip | Release/version bump. Explicitly out of scope. |
| `b9d36db7` | docs(proxy): document Anthropic API URL overrides | `wiki/proxy.md` | take-carefully: docs factual fix, manual rewrite only | Optional docs-only rewrite | Factual proxy docs improvement. Should not be cherry-picked wholesale because fork docs have diverged. |
| `b1d1f8cd` | docs(proxy): document `ANTHROPIC_TARGET_API_URL` | `docs/content/docs/proxy.mdx`, `wiki/proxy.md` | take-carefully: docs factual fix, manual rewrite only | Optional docs-only rewrite | Factual env-var documentation. Current `docs/content/docs/proxy.mdx` already lists `--anthropic-api-url`, but examples do not show `ANTHROPIC_TARGET_API_URL`. Manual rewrite is safer. |
| `d99df78b` | docs: fix get started perf command | README | already-covered / patch-equivalent | No action | Current README already uses `headroom perf`; `headroom stats` is absent. |
| `378d77e7` | fix: update dashboard doc link (#544) | `headroom/dashboard/templates/dashboard.html` | take-carefully: docs factual fix, manual rewrite only | Optional small docs/link fix | Factual link update from old GitHub Pages docs to current hosted docs. Safe-looking but not part of U005 because this task is audit-only. |
| `55579445` | fix(docs): mkdocs configuration to build with correct folder (#543) | `mkdocs.yml`, provider proxy route test formatting | take-carefully: docs factual fix, manual rewrite only | Optional docs tooling audit | Adds `docs_dir: wiki` to MkDocs. Fork currently validates docs with Fumadocs from `docs/`; MkDocs use should be confirmed before applying. |
| `0375f7f0` | docs: fix stale API references, retired class imports, and incorrect examples | README, docs, `llms.txt`, provider route test | take-carefully: docs factual fix, manual rewrite only | Optional docs-only audit | Contains useful stale-doc cleanup, but patch is broad and would conflict with M001/H001-H009 docs. Apply by manual excerpt only if needed. |
| `a359dae3` | Add Trendshift badge to README | README | skip: upstream README marketing / badge / leaderboard / vanity | Reject | Upstream vanity badge. Explicitly excluded. |
| `1e8beb02` | Updated README | README | already-covered / patch-equivalent | No action | Removes 60B leaderboard community line. Fork already removed/softened this through M001/README audit. |
| `9f8b621e` | Updated README | README | already-covered / patch-equivalent | No action | Removes 60B badge and leaderboard image block. Fork already removed/softened this through M001/README audit. |

## 5. Skip List

README marketing / vanity:

```text
a359dae3 Add Trendshift badge to README
63143608 fix readme
```

Already covered README cleanup:

```text
9f8b621e Updated README
1e8beb02 Updated README
d99df78b docs: fix get started perf command
```

Release/version scope:

```text
f7c25522 chore: release main
6775e650 ci(release-please): set versioned PR title pattern to fix tagging jam
```

Enterprise/support docs not aligned with the fork public surface:

```text
3df22cad docs: add enterprise.md
e6f788fb docs: add link to enterprisemd in README
```

Merge commits skipped because individual commits were either already taken,
classified above, or out of scope:

```text
44318f6e Merge pull request #611 from chopratejas/add-entmd
a549f9e8 Merge pull request #609 from chopratejas/readme-fix
5f5f261a Merge pull request #555 from ashishpatel26/fix/531-codex-wrap-fail-open-on-compression
e87cece9 Merge pull request #564 from mosatch/fix/thread-local-tree-sitter-parser
06d7cb9e Merge pull request #539 from neogenix/fix/security-and-reliability-blockers
d8ac7472 Merge pull request #601 from chopratejas/ci/intelligent-parallel-pipeline
184b2904 Merge pull request #540 from neogenix/docs/fix-stale-and-incorrect-docs
3599de8e Merge branch 'main' into docs/fix-stale-and-incorrect-docs
8006293e Merge pull request #594 from chopratejas/release-please--branches--main
f4dff9b4 Merge pull request #576 from chopratejas/fix/copilot-subscription-auth
a5ff663a Merge pull request #579 from praneetware/issue-561-anthropic-api-url
f58340d1 Merge pull request #573 from jamesx0416/codex-openai-responses-parallel-units
bd0e8456 Merge branch 'chopratejas:main' into fix/thread-local-tree-sitter-parser
982d01b9 Merge pull request #541 from evanclan/fix/learn-gemini-flash-latest-default
92075b95 Merge pull request #536 from SuperMarioYL/fix/utf8-encoding-owned-assets
6272de63 Merge pull request #560 from technote-space/fix-readme-perf-command
a6a09e6c Merge pull request #522 from Leathal1/main
```

## 6. Candidate Next Batch

Recommended next batch:

```text
U006: small upstream runtime correctness after U005

Candidate commits:
  6dfcaa83 fix(wrap): report unbindable proxy ports (#602)
  2170a1b4 fix(proxy): fail-open on corrupt golden bytes instead of RuntimeError (#603)
```

Suggested approach:

1. Cherry-pick each with `-x`, one at a time.
2. Resolve conflicts in favor of H001-H009 behavior.
3. Run focused tests:
   - `python -m pytest tests/test_cli/test_wrap_persistent.py`
   - `python -m pytest tests/test_corrupt_golden_bytes_recovery.py` if added
   - `python -m pytest tests/test_proxy_ccr.py`
   - `python -m pytest tests/test_ccr_tool_injection.py`
   - `python -m pytest tests/test_cli/test_wrap_copilot.py`
4. Run `python -m ruff check headroom tests`.
5. Run `python -m ruff format --check headroom tests`.
6. Run `git diff --check`.

Optional later docs-only batch:

```text
U007-docs-only:
  378d77e7 dashboard docs link
  b1d1f8cd / b9d36db7 Anthropic target API URL docs
  selected excerpts from 0375f7f0 stale docs cleanup
```

This should be manual rewrite only, not cherry-pick, because fork docs were
intentionally reshaped by M001.

No CI batch is recommended now. The upstream CI pipeline is broad and should be
audited separately if the fork wants to adopt it.

## 7. Risks and Caveats

- Full pytest was not run for U005.
- U005 is audit-only; no runtime tests were needed beyond repository hygiene.
- Prior Windows timeout caveats from earlier batches remain historical context,
  but no timeout occurred in this audit.
- `git diff --stat main..upstream/main` includes many deletions of fork-owned
  H001-H009 docs, tests, benchmarks, CCR parser/backend files, and validation
  logs. This is why `upstream/main` must not be merged wholesale.
- Docs tooling caveat: current fork docs checks use `npm exec fumadocs-mdx` from
  `docs/`; upstream MkDocs changes should be handled only after confirming
  MkDocs remains relevant to this fork.

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

## 8. Recommendation

Recommendation: proceed with next intake batch.

The remaining high-value upstream intake is narrow:

```text
Proceed with U006:
  6dfcaa83
  2170a1b4
```

Do not merge upstream/main.

Do not take README marketing, Trendshift, release/version, enterprise support
surface, or broad CI pipeline commits in this pass.

After U006, consider a separate docs-only manual rewrite for factual proxy/docs
items if desired. Otherwise, upstream intake can stop and work can return to the
fork roadmap.
