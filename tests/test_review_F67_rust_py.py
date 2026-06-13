"""RED test for finding F67-rust-py.

Claim: SmartCrusher.crush_array_json panics (pyo3 PanicException) on
malformed items_json and on non-array JSON, and compact_document_json
panics on malformed doc_json -- all inside py.allow_threads. These are
recoverable caller-supplied bad-input cases, so the FFI should raise a
clean ValueError (as the Python mirror does and as the crate's own
score_line/ctx_from_str convention prescribes), not a BaseException-
derived PanicException that escapes `except ValueError` / `except
Exception` handlers.

Each test asserts the INTENDED behavior (ValueError). It FAILS today
because a pyo3_runtime.PanicException is raised instead.
"""

import pytest

import headroom._core as core


@pytest.fixture()
def crusher():
    # Fresh instance per test; no shared on-disk state is touched.
    return core.SmartCrusher()


def test_crush_array_json_malformed_raises_valueerror(crusher):
    # Recoverable bad input: should be a clean ValueError, not a panic.
    with pytest.raises(ValueError):
        crusher.crush_array_json("not json")


def test_crush_array_json_non_array_raises_valueerror(crusher):
    # Valid JSON but not an array: still recoverable -> ValueError.
    with pytest.raises(ValueError):
        crusher.crush_array_json('{"a": 1}')


def test_compact_document_json_malformed_raises_valueerror(crusher):
    with pytest.raises(ValueError):
        crusher.compact_document_json("not json")
