"""RED test for F44-providers.

Claim: headroom/tokenizers/huggingface.py:_load_tokenizer calls
AutoTokenizer.from_pretrained(tokenizer_name, trust_remote_code=True).
The tokenizer_name for a model routed to the huggingface backend but absent
from MODEL_TO_TOKENIZER (e.g. 'codegen-*', registry.py:64) is the model string
verbatim (get_tokenizer_name final branch, huggingface.py:149). So a
client-chosen model name becomes a literal HF repo id and arbitrary remote
Python executes at tokenizer-construction time via trust_remote_code=True.

This test injects a fake `transformers` module so the exact call site runs
without the real library, records the kwargs passed to from_pretrained, drives
the call through the public get_tokenizer entry point with an attacker-chosen
'codegen-evil/repo' model name, and asserts trust_remote_code is NOT True.

It FAILS today (True is passed) and would pass once the flag is removed or
defaulted False / gated.
"""

import sys
import types

import pytest


@pytest.fixture
def fake_transformers(monkeypatch):
    """Inject a fake transformers module recording from_pretrained kwargs."""
    calls = []

    class FakeTokenizer:
        def encode(self, text, add_special_tokens=False):
            return list(range(len(text)))

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(name, *args, **kwargs):
            calls.append({"name": name, "args": args, "kwargs": kwargs})
            return FakeTokenizer()

    fake_mod = types.ModuleType("transformers")
    fake_mod.AutoTokenizer = FakeAutoTokenizer
    monkeypatch.setitem(sys.modules, "transformers", fake_mod)

    # _load_tokenizer is lru_cached; clear so this call actually executes.
    from headroom.tokenizers import huggingface as hf

    hf._load_tokenizer.cache_clear()
    yield calls
    hf._load_tokenizer.cache_clear()


def test_huggingface_tokenizer_refuses_remote_code(fake_transformers):
    from headroom.tokenizers.registry import get_tokenizer

    # Attacker-chosen model name: routed to huggingface backend (registry.py:64
    # ^codegen) but absent from MODEL_TO_TOKENIZER -> passed verbatim as the HF
    # repo id.
    tok = get_tokenizer("codegen-evil/repo", backend="huggingface")
    tok.count_text("x")

    assert fake_transformers, (
        "AutoTokenizer.from_pretrained was never reached; test setup is wrong"
    )
    call = fake_transformers[-1]

    # The repo id must be the verbatim attacker string (confirms the routing).
    assert call["name"] == "codegen-evil/repo"

    # The defect: remote code execution is enabled for a client-chosen repo id.
    assert call["kwargs"].get("trust_remote_code") is not True, (
        "trust_remote_code=True was passed to AutoTokenizer.from_pretrained for "
        "a client-chosen HF repo id; this loads and executes arbitrary remote "
        "Python at tokenizer-construction time"
    )
