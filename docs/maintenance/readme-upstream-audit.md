# README upstream audit

Date: 2026-06-05

Scope: README-only audit of selected upstream commits after U001. This audit does not merge
`upstream/main` and does not cherry-pick README commits wholesale.

## Decision rules

Adopt changes that correct real command names, security/install/compatibility details, or
conservative descriptions of shipped behavior.

Reject changes that reintroduce upstream marketing, leaderboard/badge vanity, guaranteed
savings, "compresses everything" claims, hosted SaaS implementation claims, Redis/Valkey
hosted backend claims, production billing-grade savings claims, conversation-history
compaction as shipped behavior, or multimodal/realtime compression as shipped behavior.

## Commit review

| Commit | README diff summary | Lines changed upstream | Decision | Reason |
|---|---|---|---|---|
| `9f8b621e` | Removed the `60B+ tokens saved` dashboard badge and the community leaderboard image block. | Removed the `headroomlabs.ai/dashboard` badge and the `60B+ tokens saved by the community` leaderboard block. | Already covered | M001 already removed the fork's equivalent leaderboard/headline guarantee surface. This direction matches the fork claim-audit boundary, but no additional patch is needed. |
| `1e8beb02` | Removed the Community section's live leaderboard line. | Removed `Live leaderboard -- 60B+ tokens saved and counting.` | Already covered | The current fork README does not contain the live leaderboard line. Keeping it absent matches the claim-audit boundary. |
| `a359dae3` | Added a Trendshift badge. | Added a `trendshift.io` badge for `chopratejas/headroom`. | Reject | This is upstream vanity/marketing and points at the upstream repository, not this fork's shipped local scope. |
| `d99df78b` | Corrected the Get started command from `headroom stats` to `headroom perf`. | Changed `headroom stats` to `headroom perf`. | Adopt | The current README still had this stale command in the Get started block, and `headroom perf` is the local CLI command for proxy performance analysis. |

## Applied patch

- Updated the README Get started command from `headroom stats` to `headroom perf`.

## Not applied

- No Trendshift badge.
- No upstream README marketing copy.
- No `60B+` leaderboard language.
- No "compresses everything" style claim.
- No hosted SaaS, Redis/Valkey hosted backend, billing-grade savings, conversation-history
  compaction, or multimodal/realtime compression shipped claims.
