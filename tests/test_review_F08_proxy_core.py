"""RED test for F08-proxy-core.

Claim: RecencyBoostRanker.rank rebuilds each MemoryCandidate without
passing id=c.id, so every ranked candidate's id resets to "".
"""

from headroom.proxy.memory_ranker import MemoryCandidate, RecencyBoostRanker


def test_rank_preserves_backend_id():
    ranker = RecencyBoostRanker()
    out = ranker.rank([MemoryCandidate(content="x", score=0.9, id="mem-123")])
    assert out[0].id == "mem-123", f"id was stripped, got {out[0].id!r}"
