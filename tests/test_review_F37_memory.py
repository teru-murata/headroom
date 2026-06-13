"""RED test for F37-memory.

Claim: SQLiteMemoryStore declares save/query/get/count/... as `async def`
but executes blocking sqlite3 calls directly on the event loop without
asyncio.to_thread/executor. Under concurrency this stalls the loop, so a
periodic heartbeat coroutine cannot tick while a slow query runs.

This test makes a single sqlite operation take ~0.3s (by wrapping the
connection's execute with a blocking sleep) and asserts that a 20ms
heartbeat coroutine keeps ticking during that window. If the sqlite call
runs on the loop (the defect), the heartbeat is starved and produces far
fewer ticks than expected -> test FAILS (RED).

Once the store offloads via asyncio.to_thread, the loop stays responsive
and the heartbeat ticks freely -> test passes (GREEN).
"""

from __future__ import annotations

import asyncio
import time

import pytest

from headroom.memory.adapters.sqlite import SQLiteMemoryStore
from headroom.memory.models import Memory
from headroom.memory.ports import MemoryFilter


BLOCK_SECONDS = 0.3
HEARTBEAT_INTERVAL = 0.02  # 20ms


class _BlockingConn:
    """Wraps a real sqlite3 connection; makes execute() block synchronously."""

    def __init__(self, real_conn):
        self._real = real_conn

    def execute(self, *args, **kwargs):
        # Synchronous, loop-blocking sleep -- mimics a slow disk/query.
        time.sleep(BLOCK_SECONDS)
        return self._real.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)


@pytest.mark.asyncio
async def test_store_query_does_not_block_loop(tmp_path, monkeypatch):
    store = SQLiteMemoryStore(tmp_path / "mem.db")

    # Seed one row so query has work to do (uses real, un-patched execute).
    await store.save(Memory(content="hello", user_id="alice"))

    # Now make every connection's execute block for BLOCK_SECONDS.
    real_get_conn = store._get_conn

    def slow_get_conn():
        return _BlockingConn(real_get_conn())

    monkeypatch.setattr(store, "_get_conn", slow_get_conn)

    ticks = 0
    stop = False

    async def heartbeat():
        nonlocal ticks
        while not stop:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            ticks += 1

    hb_task = asyncio.create_task(heartbeat())

    # Let heartbeat warm up briefly.
    await asyncio.sleep(0.05)

    start = time.monotonic()
    result = await store.query(MemoryFilter(user_id="alice"))
    elapsed = time.monotonic() - start

    stop = True
    hb_task.cancel()
    try:
        await hb_task
    except asyncio.CancelledError:
        pass

    # Sanity: our injected blocking sleep actually took effect.
    assert elapsed >= BLOCK_SECONDS
    assert len(result) == 1

    # During a ~0.3s query, a 20ms heartbeat should tick ~15 times if the
    # loop stayed responsive. If the sqlite call ran ON the loop, the
    # heartbeat is frozen and ticks ~0-1 times during that window.
    expected_min_ticks = int((BLOCK_SECONDS / HEARTBEAT_INTERVAL) * 0.5)
    assert ticks >= expected_min_ticks, (
        f"heartbeat starved: only {ticks} ticks during a {elapsed:.2f}s query "
        f"(expected >= {expected_min_ticks}); sqlite is blocking the event loop"
    )
