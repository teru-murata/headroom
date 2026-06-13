"""RED test for finding F47-providers (NN1: self-reported numbers are not evidence).

The LLM's self-reported `estimated_tokens_saved` flows verbatim through
analyzer._parse_llm_response -> _safe_int (no recount / no measurement against
actual session deltas) and is then rendered by writer._build_section as
"*~{N:,} tokens/session saved*" directly into CLAUDE.md / MEMORY.md.

A self-authored savings number published as a quantified fact is exactly NN1.
This test asserts the rendered section either OMITS an unverified savings figure
or LABELS it as model-claimed / unverified.
"""

from headroom.learn.analyzer import _parse_llm_response
from headroom.learn.writer import _build_section


def test_tokens_saved_is_not_self_reported() -> None:
    bogus = 999999
    raw = {
        "context_file_rules": [
            {
                "section": "Build Commands",
                "content": "Use `make build` not `npm run build`.",
                "evidence_count": 3,
                "estimated_tokens_saved": bogus,
            }
        ],
        "memory_file_rules": [],
    }

    recs = _parse_llm_response(raw)
    assert recs, "expected the rule to be parsed into a Recommendation"

    # The value is taken verbatim from the LLM with no independent measurement.
    assert recs[0].estimated_tokens_saved == bogus

    section = _build_section(recs)

    rendered_figure = f"~{bogus:,} tokens/session saved"
    if rendered_figure in section:
        # If the self-reported figure IS published, it must be qualified as
        # unverified / model-claimed / estimated-by-model so the user is not
        # shown an LLM's self-grade as a measured fact.
        qualifiers = ("unverified", "model-claimed", "model claimed",
                      "self-reported", "self reported", "claimed by model",
                      "not measured", "estimate only")
        lowered = section.lower()
        assert any(q in lowered for q in qualifiers), (
            "writer published the LLM's self-reported "
            f"'{rendered_figure}' as a quantified fact with no "
            "unverified/model-claimed qualifier (NN1 violation):\n" + section
        )
