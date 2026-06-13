"""RED test for F09-proxy-core.

Claim: `_read_lean_ctx_lifetime_stats` returns an all-zero `base_payload`
(installed=True) on BOTH the non-zero-exit / empty-stdout path and on ANY
exception, with NO log line -- unlike the parallel
`_read_rtk_lifetime_stats` (PR-G2), which logs a warning on both paths.

Operators therefore cannot distinguish "lean-ctx ran and saved nothing"
from "lean-ctx crashed / failed"; dashboards show fabricated zeros silently.

This test asserts a warning is logged on the exception path. If the bug is
real (silent), it FAILS today.
"""

from __future__ import annotations

import logging
import subprocess

import pytest

from headroom.proxy import helpers


@pytest.fixture
def fake_lean_ctx_path(monkeypatch):
    """Make get_lean_ctx_path() return a truthy path so we reach the
    subprocess branch (not the installed=False early return)."""
    import headroom.lean_ctx as lean_ctx_mod

    monkeypatch.setattr(
        lean_ctx_mod, "get_lean_ctx_path", lambda: "/usr/local/bin/lean-ctx"
    )
    yield


def test_lean_ctx_logs_warning_on_subprocess_exception(
    fake_lean_ctx_path, monkeypatch, caplog
):
    def boom(*args, **kwargs):
        raise OSError("lean-ctx binary missing / crashed")

    monkeypatch.setattr(subprocess, "run", boom)

    with caplog.at_level(logging.WARNING, logger="headroom.proxy"):
        payload = helpers._read_lean_ctx_lifetime_stats()

    # The synthetic-zero fallback is returned ...
    assert payload is not None
    assert payload["installed"] is True
    assert payload["tokens_saved"] == 0

    # ... but, per PR-G2's contract for the parallel RTK reader, a WARNING
    # must be emitted so operators can tell "crashed" from "saved nothing".
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, (
        "expected a WARNING log on the lean-ctx subprocess-exception "
        "synthetic-zero path (parallel _read_rtk_lifetime_stats logs at "
        "helpers.py:1163); none was emitted -- the fabricated zeros are "
        "silent."
    )


def test_lean_ctx_logs_warning_on_non_zero_exit(
    fake_lean_ctx_path, monkeypatch, caplog
):
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "lean-ctx: fatal error"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeResult())

    with caplog.at_level(logging.WARNING, logger="headroom.proxy"):
        payload = helpers._read_lean_ctx_lifetime_stats()

    assert payload is not None
    assert payload["installed"] is True
    assert payload["tokens_saved"] == 0

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, (
        "expected a WARNING log on the lean-ctx non-zero-exit synthetic-zero "
        "path (parallel _read_rtk_lifetime_stats logs at helpers.py:1141); "
        "none was emitted."
    )
