"""RED test for finding F11-proxy-core.

Claim: ``_read_request_body_bytes`` decompresses gzip/zstd/deflate/brotli
request bodies with NO cap on the *decompressed* size. ``MAX_REQUEST_BODY_SIZE``
(100 MB) is only ever applied to the COMPRESSED Content-Length by the handlers,
never to the inflated output. A small compression bomb therefore expands
unbounded inside ``_read_request_body_bytes`` -> memory-exhaustion DoS.

This test feeds a tiny (~hundreds of KB) gzip body that inflates to ~200 MB
(safely above the 100 MB compressed cap but small enough not to OOM CI) and
asserts the helper refuses to materialise a decompressed body larger than
``MAX_REQUEST_BODY_SIZE``. Today there is no such guard, so the helper happily
returns the full ~200 MB blob and the assertion FAILS -> bug confirmed.
"""

import asyncio
import gzip

import pytest

from headroom.proxy.helpers import (
    MAX_REQUEST_BODY_SIZE,
    _read_request_body_bytes,
)


class _FakeRequest:
    """Minimal stand-in for starlette Request used by the helper.

    The helper only touches ``.headers.get('content-encoding')`` and
    ``await .body()``.
    """

    def __init__(self, body: bytes, content_encoding: str) -> None:
        self._body = body
        self.headers = {"content-encoding": content_encoding}

    async def body(self) -> bytes:
        return self._body


def test_gzip_bomb_is_not_capped_at_decompressed_size():
    # ~200 MB of zeros compresses to a few hundred KB of gzip -> classic bomb.
    inflated_size = 200 * 1024 * 1024  # 200 MB, > 100 MB MAX_REQUEST_BODY_SIZE
    payload = b"\x00" * inflated_size
    bomb = gzip.compress(payload)

    # Sanity: the COMPRESSED body is small (a forwarder's Content-Length guard
    # would happily wave it through), but it inflates past the body-size cap.
    assert len(bomb) < MAX_REQUEST_BODY_SIZE
    assert inflated_size > MAX_REQUEST_BODY_SIZE

    request = _FakeRequest(bomb, "gzip")

    # Correct contract: the helper must NOT materialise a >MAX decompressed body.
    # It may satisfy this EITHER by raising ValueError (rejecting the bomb) OR by
    # returning a capped body. Returning the full ~200 MB blob is the bug.
    try:
        raw = asyncio.run(_read_request_body_bytes(request))
    except ValueError:
        return  # bomb rejected before full inflation -> fixed behavior (green)

    assert len(raw) <= MAX_REQUEST_BODY_SIZE, (
        f"_read_request_body_bytes inflated a {len(bomb)}-byte gzip body to "
        f"{len(raw)} bytes with no decompressed-size cap "
        f"(MAX_REQUEST_BODY_SIZE={MAX_REQUEST_BODY_SIZE}); a compression bomb "
        f"can exhaust memory."
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
