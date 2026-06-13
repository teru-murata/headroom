"""CCR marker parsing and local hash validation.

Headroom currently has two local marker families:

- bracket retrieve markers, e.g.
  ``[100 items compressed to 10. Retrieve more: hash=...]``
- SmartCrusher angle markers, e.g.
  ``<<ccr:HASH 15_rows_offloaded>>`` or ``<<ccr:HASH,base64,4.5KB>>``

This module deliberately covers the local hash-backed profile only. Hosted
tenant namespaces, signatures, and opaque remote marker policy are outside
Headroom's local CCR parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

CCRMarkerFamily = Literal["bracket_retrieve", "angle_ccr"]

# Local emitters currently produce:
# - SmartCrusher row-drop / opaque markers: SHA-256 prefix, 12 hex chars.
# - Python compression_store and Rust live-zone CCR keys: 24 hex chars.
#
# INTENTIONAL: accepting BOTH 12- and 24-hex lengths is by design, not a
# weakened 24-only check. The 12-hex SmartCrusher format is a first-class
# RETRIEVABLE marker — smart_crusher.py mirrors a 12-char SHA-256 hash to the
# store specifically "so /v1/retrieve resolves it" (see
# test_smartcrusher_angle_marker_parses / _opaque_blob_marker_parses). So the
# length set must NOT be narrowed to 24-only and the retrieve path must NOT
# reject 12-hex; either would break SmartCrusher retrieval.
#
# Security note (the real anti-spoof axis is tenant isolation, NOT hash
# length): a 12-hex prefix is a 48-bit space, so a collision/brute-force can
# only reach content WITHIN the active store. The protection that matters for
# untrusted multi-tenant use is the per-request tenant-scoped store
# (compression_store._request_ccr_store), which bounds any reachable content
# to the caller's own tenant. Hosted/SaaS hardening therefore enforces that
# tenant scoping on the retrieve path (and may add hash-length as
# defense-in-depth) — it does not, and must not, ban 12-hex globally. This is
# a deliberate self-host-loose / hosted-hardened differentiation
# (owner ruling 2026-06-13), not an oversight.
SUPPORTED_CCR_HASH_LENGTHS = frozenset({12, 24})

_HASH_RE = re.compile(r"^[0-9A-Fa-f]+$")
_ANGLE_MARKER_RE = re.compile(r"<<ccr:(?P<hash>[0-9A-Fa-f]+)(?P<metadata>[^>\r\n]*)>>")
_BRACKET_MARKER_RE = re.compile(
    r"\[(?P<body>[^\]\r\n]*?hash=(?P<hash>[0-9A-Fa-f]+)(?P<metadata>[^\]\r\n]*))\]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CCRMarker:
    """A parsed local CCR marker."""

    raw: str
    family: CCRMarkerFamily
    hash: str
    metadata: str | None
    start: int
    end: int


def is_supported_ccr_hash(value: object) -> bool:
    """Return True when ``value`` is a supported local CCR hash token."""
    return (
        isinstance(value, str)
        and len(value) in SUPPORTED_CCR_HASH_LENGTHS
        and _HASH_RE.fullmatch(value) is not None
    )


def normalize_ccr_hash(value: object) -> str:
    """Normalize a raw local CCR hash or full marker text to lowercase hash.

    Raises:
        ValueError: if ``value`` is not a supported local hash or marker.
    """
    if not isinstance(value, str):
        raise ValueError(f"CCR hash must be a string, got {type(value).__name__}")

    if is_supported_ccr_hash(value):
        return value.lower()

    marker = parse_first_ccr_marker(value)
    if marker is not None:
        return marker.hash

    raise ValueError(f"Unsupported CCR hash or marker: {value!r}")


def parse_first_ccr_marker(text: str) -> CCRMarker | None:
    """Return the first supported CCR marker in ``text``, if any."""
    markers = parse_ccr_markers(text)
    return markers[0] if markers else None


def parse_ccr_markers(text: str) -> list[CCRMarker]:
    """Parse supported local CCR markers in deterministic text order."""
    if not isinstance(text, str) or not text:
        return []

    markers: list[CCRMarker] = []
    markers.extend(_parse_angle_markers(text))
    markers.extend(_parse_bracket_markers(text))
    markers.sort(key=lambda marker: (marker.start, marker.end))
    return markers


def _parse_angle_markers(text: str) -> list[CCRMarker]:
    markers: list[CCRMarker] = []
    for match in _ANGLE_MARKER_RE.finditer(text):
        hash_value = match.group("hash")
        metadata = match.group("metadata")
        if not is_supported_ccr_hash(hash_value):
            continue
        if not _metadata_has_allowed_separator(metadata, allowed=(" ", ",")):
            continue
        if not _metadata_is_safe(metadata):
            continue
        markers.append(
            CCRMarker(
                raw=match.group(0),
                family="angle_ccr",
                hash=hash_value.lower(),
                metadata=metadata.strip() or None,
                start=match.start(),
                end=match.end(),
            )
        )
    return markers


def _parse_bracket_markers(text: str) -> list[CCRMarker]:
    markers: list[CCRMarker] = []
    for match in _BRACKET_MARKER_RE.finditer(text):
        raw = match.group(0)
        raw_lower = raw.lower()
        if not (
            "compressed" in raw_lower
            or "retrieve more:" in raw_lower
            or "retrieve original:" in raw_lower
        ):
            continue
        hash_value = match.group("hash")
        metadata = match.group("metadata")
        if not is_supported_ccr_hash(hash_value):
            continue
        if not _metadata_has_allowed_separator(metadata, allowed=(" ", "\t", ".", ",", ";", ":")):
            continue
        if not _metadata_is_safe(metadata):
            continue
        markers.append(
            CCRMarker(
                raw=raw,
                family="bracket_retrieve",
                hash=hash_value.lower(),
                metadata=metadata.strip() or None,
                start=match.start(),
                end=match.end(),
            )
        )
    return markers


def _metadata_has_allowed_separator(metadata: str, *, allowed: tuple[str, ...]) -> bool:
    return metadata == "" or metadata[0] in allowed


def _metadata_is_safe(metadata: str) -> bool:
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in metadata):
        return False
    if "/" in metadata or "\\" in metadata:
        return False
    return ".." not in metadata
