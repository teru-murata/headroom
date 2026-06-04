"""Local provenance ledger events for compression and CCR retrieval.

This module is Headroom's producer-side ledger surface. It writes local JSONL
events and exposes OpenTelemetry-compatible ``bridge.*`` attribute names. Hosted
ingest, retention, reconciliation, dashboards, and billing remain outside
Headroom.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "ledger-event-v0"
DEFAULT_EVENT_GRADE = "source"
DEFAULT_DEPLOYMENT_MODE = "local_dev"
DEFAULT_BRIDGE_INSTANCE_ID = "headroom-local"
TOKEN_COUNT_METHOD = "estimated_chars_div_4"

_LOCAL_DEFAULT = "local"
_GLOBAL_EMITTER: LedgerEmitter | None = None
_GLOBAL_LOCK = threading.Lock()


def estimate_tokens(text: str) -> int:
    """Deterministically estimate tokens from characters.

    This is not provider billing tokenization. It is a stable local estimate
    for source-level attribution when an exact tokenizer is not available.
    """
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no"}


def _env_default(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


@dataclass
class LedgerEvent:
    """A ledger-event-v0-compatible local event."""

    event_type: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_grade: str = DEFAULT_EVENT_GRADE
    schema_version: str = SCHEMA_VERSION
    tenant_id: str = _LOCAL_DEFAULT
    project_id: str = _LOCAL_DEFAULT
    session_id: str = _LOCAL_DEFAULT
    request_id: str = _LOCAL_DEFAULT
    idempotency_key: str | None = None
    sequence_number: int = 0
    time_window: dict[str, str] | None = None
    occurred_at: str = field(default_factory=_utc_now)
    deployment_mode: str = DEFAULT_DEPLOYMENT_MODE
    bridge_instance_id: str = DEFAULT_BRIDGE_INSTANCE_ID

    source_id: str | None = None
    provider_request_id: str | None = None
    ingested_at: str | None = None
    turn_id: str | None = None
    source_type: str | None = None
    source_path: str | None = None
    provider: str | None = None
    model: str | None = None
    cache_zone: str | None = None
    original_tokens: int | None = None
    compressed_tokens: int | None = None
    saved_tokens: int | None = None
    token_count_method: str | None = None
    compression_method: str | None = None
    ccr_marker_id: str | None = None
    ccr_backend: str | None = None
    retrieved_count: int | None = None
    accuracy_guard: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    OTEL_KEYS: ClassVar[tuple[str, ...]] = (
        "event_id",
        "event_type",
        "event_grade",
        "tenant_id",
        "project_id",
        "session_id",
        "request_id",
        "source_id",
        "provider_request_id",
        "original_tokens",
        "compressed_tokens",
        "saved_tokens",
        "compression_method",
        "ccr_marker_id",
        "cache_zone",
        "deployment_mode",
        "bridge_instance_id",
        "source_type",
        "accuracy_guard",
    )

    @classmethod
    def create(cls, event_type: str, **fields: Any) -> LedgerEvent:
        """Create an event with explicit local defaults for required fields."""
        occurred_at = str(fields.pop("occurred_at", _utc_now()))
        tenant_id = str(
            fields.pop("tenant_id", _env_default("HEADROOM_LEDGER_TENANT_ID", _LOCAL_DEFAULT))
        )
        project_id = str(
            fields.pop("project_id", _env_default("HEADROOM_LEDGER_PROJECT_ID", _LOCAL_DEFAULT))
        )
        session_id = str(
            fields.pop("session_id", _env_default("HEADROOM_LEDGER_SESSION_ID", _LOCAL_DEFAULT))
        )
        request_id = str(
            fields.pop("request_id", _env_default("HEADROOM_LEDGER_REQUEST_ID", _LOCAL_DEFAULT))
        )
        deployment_mode = str(
            fields.pop(
                "deployment_mode",
                _env_default("HEADROOM_LEDGER_DEPLOYMENT_MODE", DEFAULT_DEPLOYMENT_MODE),
            )
        )
        bridge_instance_id = str(
            fields.pop(
                "bridge_instance_id",
                _env_default("HEADROOM_LEDGER_BRIDGE_INSTANCE_ID", DEFAULT_BRIDGE_INSTANCE_ID),
            )
        )
        time_window = fields.pop(
            "time_window",
            {
                "started_at": occurred_at,
                "ended_at": occurred_at,
            },
        )
        event = cls(
            event_type=event_type,
            occurred_at=occurred_at,
            tenant_id=tenant_id,
            project_id=project_id,
            session_id=session_id,
            request_id=request_id,
            deployment_mode=deployment_mode,
            bridge_instance_id=bridge_instance_id,
            time_window=time_window,
            **fields,
        )
        if event.idempotency_key is None:
            event.idempotency_key = f"{event.event_type}:{event.request_id}:{event.event_id}"
        return event

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable event dictionary."""
        data = asdict(self)
        data["ingested_at"] = data["ingested_at"] or _utc_now()
        if data["time_window"] is None:
            data["time_window"] = {
                "started_at": data["occurred_at"],
                "ended_at": data["occurred_at"],
            }
        return data

    def to_json(self) -> str:
        """Serialize as compact JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def to_otel_attributes(self) -> dict[str, Any]:
        """Return OpenTelemetry-compatible attributes with ``bridge.*`` keys."""
        data = self.to_dict()
        return {f"bridge.{key}": data[key] for key in self.OTEL_KEYS if data.get(key) is not None}


class LedgerEmitter:
    """Base local ledger emitter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sequence_number = 0

    def emit(self, event: LedgerEvent) -> LedgerEvent:
        """Emit an event and return the sequence-numbered event."""
        self._assign_sequence(event)
        self._emit(event)
        return event

    def _assign_sequence(self, event: LedgerEvent) -> None:
        if event.sequence_number > 0:
            return
        with self._lock:
            self._sequence_number += 1
            event.sequence_number = self._sequence_number

    def _emit(self, event: LedgerEvent) -> None:
        raise NotImplementedError


class NullLedgerEmitter(LedgerEmitter):
    """No-op emitter used when local ledger export is disabled."""

    def _emit(self, event: LedgerEvent) -> None:
        del event


class InMemoryLedgerEmitter(LedgerEmitter):
    """Test and embedding helper that keeps events in memory."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[LedgerEvent] = []

    def _emit(self, event: LedgerEvent) -> None:
        self.events.append(event)


class JsonlLedgerEmitter(LedgerEmitter):
    """Append ledger events to a local JSONL file."""

    def __init__(self, path: str | os.PathLike[str], *, strict: bool = False) -> None:
        super().__init__()
        self.path = Path(path)
        self.strict = strict

    def _emit(self, event: LedgerEvent) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(event.to_json())
                handle.write("\n")
        except Exception as exc:
            logger.warning("Ledger JSONL write failed for %s: %s", self.path, exc)
            if self.strict:
                raise


def get_ledger_emitter() -> LedgerEmitter:
    """Return the process-wide local ledger emitter."""
    global _GLOBAL_EMITTER
    with _GLOBAL_LOCK:
        if _GLOBAL_EMITTER is None:
            _GLOBAL_EMITTER = _build_env_emitter()
        return _GLOBAL_EMITTER


def set_ledger_emitter(emitter: LedgerEmitter | None) -> None:
    """Override the process-wide emitter; pass ``None`` to use Null."""
    global _GLOBAL_EMITTER
    with _GLOBAL_LOCK:
        _GLOBAL_EMITTER = emitter or NullLedgerEmitter()


def reset_ledger_emitter() -> None:
    """Reset the process-wide emitter so env configuration is re-read."""
    global _GLOBAL_EMITTER
    with _GLOBAL_LOCK:
        _GLOBAL_EMITTER = None


def _build_env_emitter() -> LedgerEmitter:
    if not _env_bool("HEADROOM_LEDGER_ENABLED", default=True):
        return NullLedgerEmitter()
    jsonl_path = os.environ.get("HEADROOM_LEDGER_JSONL_PATH")
    if jsonl_path is None or jsonl_path.strip() == "":
        return NullLedgerEmitter()
    strict = _env_bool("HEADROOM_LEDGER_STRICT", default=False)
    return JsonlLedgerEmitter(jsonl_path, strict=strict)


def event_to_otel_attributes(event: LedgerEvent) -> dict[str, Any]:
    """Convenience wrapper for OTel-compatible attribute mapping."""
    return event.to_otel_attributes()


__all__ = [
    "DEFAULT_BRIDGE_INSTANCE_ID",
    "DEFAULT_DEPLOYMENT_MODE",
    "InMemoryLedgerEmitter",
    "JsonlLedgerEmitter",
    "LedgerEmitter",
    "LedgerEvent",
    "NullLedgerEmitter",
    "SCHEMA_VERSION",
    "TOKEN_COUNT_METHOD",
    "estimate_tokens",
    "event_to_otel_attributes",
    "get_ledger_emitter",
    "reset_ledger_emitter",
    "set_ledger_emitter",
]
