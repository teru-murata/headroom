"""RED test for finding F20-transforms.

Claim: LogCompressor._store_in_ccr computes its cache_key as
hashlib.md5(original)[:24] and passes it to CompressionStore.store as
explicit_hash. This diverges from CompressionStore's own default keying,
which moved OFF MD5 onto SHA-256[:24] (PR #395). The returned key is
therefore an MD5[:24] key, not the SHA-256[:24] key the store computes for
the same content.

This test asserts that the key returned by _store_in_ccr matches the key
CompressionStore.store computes by default for the same `original`. If the
shim were aligned to the store's SHA-256 keying (the fix), the keys would
match. Today they differ (MD5[:24] vs SHA-256[:24]), so this test FAILS.
"""

import hashlib

import pytest

from headroom.cache.compression_store import (
    CompressionStore,
    clear_request_compression_store,
    set_request_compression_store,
)
from headroom.transforms.log_compressor import LogCompressor


@pytest.fixture
def isolated_store():
    """Provide a fresh, request-scoped CompressionStore so the global
    singleton and any shared on-disk state are never touched."""
    store = CompressionStore(max_entries=100, default_ttl=300)
    set_request_compression_store(store)
    try:
        yield store
    finally:
        clear_request_compression_store()
        store.clear()
        store.close()


def test_store_in_ccr_uses_store_default_sha256_key(isolated_store):
    original = "x"
    compressed = "y"

    expected_sha = hashlib.sha256(original.encode()).hexdigest()[:24]
    legacy_md5 = hashlib.md5(original.encode()).hexdigest()[:24]
    # Sanity: the two functions genuinely disagree for this input.
    assert expected_sha != legacy_md5

    compressor = LogCompressor()
    returned_key = compressor._store_in_ccr(original, compressed, 1)

    # The shim should key content the same way the store does by default
    # (SHA-256[:24]). It instead returns the legacy MD5[:24] key.
    assert returned_key == expected_sha, (
        f"_store_in_ccr returned {returned_key!r} (legacy MD5[:24]) instead of "
        f"the store's default SHA-256[:24] key {expected_sha!r}"
    )
