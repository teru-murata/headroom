"""RED test for finding F45-providers (SSRF via x-headroom-base-url).

Claim: the catchall passthrough route in headroom/providers/proxy_routes.py:639
reads the client-controlled request header ``x-headroom-base-url`` and forwards
the request to ``proxy.handle_passthrough(request, custom_base.rstrip('/'))``
with no allowlist / scheme / host validation. A client can therefore point the
proxy at an arbitrary internal URL (SSRF, e.g. the cloud metadata endpoint
169.254.169.254) and inbound Authorization / api-key headers are forwarded to
that attacker-chosen origin (credential exfiltration).

This test sends such a request and asserts the proxy REJECTS it (or at least
does not dispatch to the attacker host). If the bug is real, the proxy dispatches
to the metadata IP and forwards the Authorization header -> the test FAILS.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

from headroom.proxy.server import ProxyConfig, create_app

METADATA_URL = "http://169.254.169.254/"


def _app() -> Any:
    return create_app(
        ProxyConfig(
            optimize=False,
            cache_enabled=False,
            rate_limit_enabled=False,
            anthropic_api_url="https://api.anthropic.test",
            openai_api_url="https://api.openai.test",
            gemini_api_url="https://api.gemini.test",
            cloudcode_api_url="https://cloudcode.test",
        )
    )


def test_passthrough_rejects_unlisted_base_url() -> None:
    class FakeAsyncClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, str]]] = []

        async def request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append((method, url, dict(kwargs.get("headers", {}))))
            return httpx.Response(200, json={"reached": url})

        async def aclose(self) -> None:
            return None

    with TestClient(_app()) as client:
        fake = FakeAsyncClient()
        client.app.state.proxy.http_client = fake
        response = client.get(
            "/anything",
            headers={
                "x-headroom-base-url": METADATA_URL,
                "Authorization": "Bearer sk-victim-credential",
            },
        )

    # The proxy must NOT have dispatched the request to the attacker-chosen
    # internal metadata host. If it did, this is the SSRF / credential
    # exfiltration described by F45-providers.
    dispatched_to_metadata = [
        (method, url, headers)
        for (method, url, headers) in fake.calls
        if "169.254.169.254" in url
    ]
    assert not dispatched_to_metadata, (
        "SSRF: proxy dispatched the request to the attacker-chosen base URL "
        f"{METADATA_URL!r}. Calls={fake.calls}"
    )

    # And it should reject (4xx) rather than happily proxy an arbitrary origin.
    assert response.status_code >= 400, (
        "Expected the proxy to reject an unlisted base URL with a 4xx, "
        f"got {response.status_code}"
    )

    # The inbound credential must never have been forwarded to the
    # attacker-controlled origin.
    for _method, url, headers in fake.calls:
        if "169.254.169.254" in url:
            assert "authorization" not in {k.lower() for k in headers}, (
                "Credential exfiltration: Authorization header forwarded to "
                f"attacker origin {url}"
            )
