# Validation Logs

This directory contains checked-in validation evidence for the local Headroom
H001-H009 implementation sequence. These files are task logs, not proof that
the entire test suite passed unless a specific log says so.

## H001-H009 Logs

| Task | Log |
|---|---|
| H001 local CCR marker parsing and SmartCrusher marker compatibility | [h001-ccr-marker-parser.txt](h001-ccr-marker-parser.txt) |
| H002 local proxy CCR retrieve visibility / TOIN retrieve fix | [h002-proxy-ccr-retrieve.txt](h002-proxy-ccr-retrieve.txt) |
| H003 local SQLite CCR backend | [h003-sqlite-ccr-backend.txt](h003-sqlite-ccr-backend.txt) |
| H004 evidence-preserving test/build log crusher acceptance | [h004-log-crusher-acceptance.txt](h004-log-crusher-acceptance.txt) |
| H005 diff and file-tree crusher acceptance | [h005-diff-file-tree-crusher-acceptance.txt](h005-diff-file-tree-crusher-acceptance.txt) |
| H006 coding-agent output compression preset | [h006-coding-agent-output-preset.txt](h006-coding-agent-output-preset.txt) |
| H007 provenance ledger emitter, JSONL export, and `bridge.*` attributes | [h007-provenance-ledger-emitter.txt](h007-provenance-ledger-emitter.txt) |
| H008 coding-agent context waste benchmark suite | [h008-context-waste-benchmark.txt](h008-context-waste-benchmark.txt) |
| H009 cache-aware net-savings benchmark and decision model | [h009-cache-aware-net-savings.txt](h009-cache-aware-net-savings.txt) |

Additional session-extracted quality-gate evidence:

- [h001-h004-session-extracted-quality-gates.txt](h001-h004-session-extracted-quality-gates.txt)
