"""Tests for the local SQLite CCR backend."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from headroom.cache.backends import CompressionStoreBackend, SQLiteBackend
from headroom.cache.compression_store import (
    CompressionEntry,
    CompressionStore,
    get_compression_store,
    reset_compression_store,
)
from headroom.proxy.server import ProxyConfig, create_app


def make_entry(
    hash_key: str = "abc123def456",
    *,
    original: str = "original content",
    compressed: str = "compressed content",
    created_at: float | None = None,
    ttl: int = 300,
) -> CompressionEntry:
    return CompressionEntry(
        hash=hash_key,
        original_content=original,
        compressed_content=compressed,
        original_tokens=100,
        compressed_tokens=10,
        original_item_count=5,
        compressed_item_count=2,
        tool_name="sqlite_test_tool",
        tool_call_id="call_sqlite",
        query_context="sqlite query",
        created_at=time.time() if created_at is None else created_at,
        ttl=ttl,
        tool_signature_hash="feedface0000",
        compression_strategy="sqlite_test",
    )


@pytest.fixture
def sqlite_path(tmp_path: Path) -> Path:
    return tmp_path / "headroom-ccr.sqlite"


def test_sqlite_backend_stores_and_retrieves_value(sqlite_path: Path) -> None:
    backend = SQLiteBackend(sqlite_path)
    try:
        entry = make_entry()

        backend.set(entry.hash, entry)
        retrieved = backend.get(entry.hash)

        assert isinstance(backend, CompressionStoreBackend)
        assert retrieved is not None
        assert retrieved.hash == entry.hash
        assert retrieved.original_content == entry.original_content
        assert retrieved.compressed_content == entry.compressed_content
        assert retrieved.tool_signature_hash == "feedface0000"
        assert backend.get_stats()["backend_type"] == "sqlite"
    finally:
        backend.close()


def test_sqlite_backend_survives_restart(sqlite_path: Path) -> None:
    backend1 = SQLiteBackend(sqlite_path)
    store1 = CompressionStore(backend=backend1, enable_feedback=False)
    hash_key = store1.store(
        original='[{"id":1,"message":"persist me"}]',
        compressed='[{"id":1}]',
        original_item_count=1,
        compressed_item_count=1,
        tool_name="restart_test",
    )
    store1.close()

    backend2 = SQLiteBackend(sqlite_path)
    store2 = CompressionStore(backend=backend2, enable_feedback=False)
    try:
        entry = store2.retrieve(hash_key)

        assert entry is not None
        assert entry.original_content == '[{"id":1,"message":"persist me"}]'
        assert entry.tool_name == "restart_test"
    finally:
        store2.close()


def test_sqlite_backend_ttl_expiry_deletes_on_retrieve(sqlite_path: Path) -> None:
    backend = SQLiteBackend(sqlite_path)
    expired_hash = "abc123def456"
    backend.set(expired_hash, make_entry(hash_key=expired_hash, created_at=0, ttl=1))
    store = CompressionStore(backend=backend, enable_feedback=False)
    try:
        assert store.retrieve(expired_hash) is None
        assert backend.exists(expired_hash) is False
    finally:
        store.close()


def test_sqlite_backend_cleanup_expired_removes_rows(sqlite_path: Path) -> None:
    backend = SQLiteBackend(sqlite_path)
    expired_hash = "abc123def456"
    live_hash = "def456abc123"
    backend.set(expired_hash, make_entry(hash_key=expired_hash, created_at=0, ttl=1))
    backend.set(live_hash, make_entry(hash_key=live_hash))
    store = CompressionStore(backend=backend, enable_feedback=False)
    try:
        removed = store.cleanup_expired()

        assert removed == 1
        assert backend.get(expired_hash) is None
        assert backend.get(live_hash) is not None
    finally:
        store.close()


def test_sqlite_backend_multiple_instances_share_db(sqlite_path: Path) -> None:
    backend1 = SQLiteBackend(sqlite_path)
    backend2 = SQLiteBackend(sqlite_path)
    store1 = CompressionStore(backend=backend1, enable_feedback=False)
    store2 = CompressionStore(backend=backend2, enable_feedback=False)
    try:
        first_hash = store1.store(original="from store1", compressed="s1")
        first_entry = store2.retrieve(first_hash)
        assert first_entry is not None
        assert first_entry.original_content == "from store1"

        second_hash = store2.store(original="from store2", compressed="s2")
        second_entry = store1.retrieve(second_hash)
        assert second_entry is not None
        assert second_entry.original_content == "from store2"
    finally:
        store1.close()
        store2.close()


def test_sqlite_store_normalizes_markers_and_rejects_malformed_keys(
    sqlite_path: Path,
) -> None:
    backend = SQLiteBackend(sqlite_path)
    store = CompressionStore(backend=backend, enable_feedback=False)
    try:
        marker = "<<ccr:89F81E97033E 2_rows_offloaded>>"
        hash_key = store.store(
            original="smartcrusher original",
            compressed="smartcrusher compressed",
            explicit_hash=marker,
        )

        assert hash_key == "89f81e97033e"
        entry = store.retrieve("[5 items compressed to 1. Retrieve more: hash=89f81e97033e]")
        assert entry is not None
        assert entry.original_content == "smartcrusher original"

        with pytest.raises(ValueError, match="supported local CCR hash or marker"):
            store.store(original="bad", compressed="bad", explicit_hash="../89f81e97033e")

        with pytest.raises(ValueError, match="supported local CCR hash or marker"):
            store.store(
                original="bad",
                compressed="bad",
                explicit_hash="<<ccr:89f81e97033e ../secret>>",
            )
    finally:
        store.close()


def test_env_selects_sqlite_backend_and_ttl(
    monkeypatch: pytest.MonkeyPatch,
    sqlite_path: Path,
) -> None:
    reset_compression_store()
    monkeypatch.setenv("HEADROOM_CCR_BACKEND", "sqlite")
    monkeypatch.setenv("HEADROOM_CCR_SQLITE_PATH", str(sqlite_path))
    monkeypatch.setenv("HEADROOM_CCR_TTL_SECONDS", "120")
    try:
        store = get_compression_store()
        stats = store.get_stats()

        assert store._default_ttl == 120
        assert stats["backend"]["backend_type"] == "sqlite"
        assert stats["backend"]["db_path"] == str(sqlite_path)
    finally:
        reset_compression_store()


def test_proxy_retrieve_works_with_sqlite_backend(
    monkeypatch: pytest.MonkeyPatch,
    sqlite_path: Path,
) -> None:
    reset_compression_store()
    monkeypatch.setenv("HEADROOM_CCR_BACKEND", "sqlite")
    monkeypatch.setenv("HEADROOM_CCR_SQLITE_PATH", str(sqlite_path))
    config = ProxyConfig(
        optimize=False,
        cache_enabled=False,
        rate_limit_enabled=False,
        cost_tracking_enabled=False,
    )
    app = create_app(config)
    try:
        with TestClient(app, client=("127.0.0.1", 12345)) as client:
            store = get_compression_store()
            hash_key = store.store(
                original='[{"id":1,"source":"sqlite proxy"}]',
                compressed="[]",
                original_item_count=1,
                compressed_item_count=0,
            )
            marker = f"<<ccr:{hash_key} proxy_sqlite>>"

            response = client.post("/v1/retrieve", json={"hash": marker})
            malformed = client.post(
                "/v1/retrieve",
                json={"hash": "<<ccr:deadbeef0000 ../secret>>"},
            )
            missing = client.post("/v1/retrieve", json={"hash": "deadbeef0000"})

        assert response.status_code == 200
        assert response.json()["original_content"] == '[{"id":1,"source":"sqlite proxy"}]'
        assert malformed.status_code == 400
        assert missing.status_code == 404
    finally:
        reset_compression_store()
