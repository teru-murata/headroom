"""Tests for CCR tool injection and MCP integration."""

import json

import pytest

from headroom.cache.compression_store import get_compression_store, reset_compression_store
from headroom.ccr import (
    CCR_TOOL_NAME,
    CCRToolInjector,
    create_ccr_tool_definition,
    create_system_instructions,
    is_supported_ccr_hash,
    normalize_ccr_hash,
    parse_ccr_markers,
    parse_first_ccr_marker,
    parse_tool_call,
)


class TestCCRMarkerParsing:
    """Test central CCR marker parsing."""

    def test_existing_bracket_marker_parses(self):
        """Existing bracket retrieve marker parses through the shared parser."""
        text = "[100 items compressed to 10. Retrieve more: hash=abc123def456abc123def456]"

        markers = parse_ccr_markers(text)

        assert len(markers) == 1
        marker = markers[0]
        assert marker.raw == text
        assert marker.family == "bracket_retrieve"
        assert marker.hash == "abc123def456abc123def456"
        assert marker.start == 0
        assert marker.end == len(text)

    def test_smartcrusher_angle_marker_parses(self):
        """SmartCrusher row-drop angle marker parses and captures metadata."""
        text = 'sentinel {"_ccr_dropped":"<<ccr:89f81e97033e 15_rows_offloaded>>"}'

        marker = parse_first_ccr_marker(text)

        assert marker is not None
        assert marker.family == "angle_ccr"
        assert marker.hash == "89f81e97033e"
        assert marker.metadata == "15_rows_offloaded"

    def test_smartcrusher_opaque_blob_marker_parses(self):
        """SmartCrusher opaque-blob angle marker parses comma metadata."""
        marker = parse_first_ccr_marker('{"blob":"<<ccr:abc123def456,base64,4.5KB>>"}')

        assert marker is not None
        assert marker.family == "angle_ccr"
        assert marker.hash == "abc123def456"
        assert marker.metadata == ",base64,4.5KB"

    def test_supported_hash_validation_matches_local_emitters(self):
        """Local CCR supports SmartCrusher 12-hex and store/live-zone 24-hex keys."""
        assert is_supported_ccr_hash("abc123def456")
        assert is_supported_ccr_hash("abc123def456abc123def456")
        assert normalize_ccr_hash("ABC123DEF456") == "abc123def456"

    @pytest.mark.parametrize(
        "value",
        [
            "abc123",
            "abc123def456abc123def456abc123",
            "abc123xyz456",
            "abc123def456\n",
            "../abc123def456",
            "abc123def456/secret",
            "",
        ],
    )
    def test_rejects_unsupported_hash_values(self, value):
        """Malformed hash values are not accepted as local CCR hashes."""
        assert not is_supported_ccr_hash(value)
        with pytest.raises(ValueError):
            normalize_ccr_hash(value)

    @pytest.mark.parametrize(
        "text",
        [
            "<<ccr:abc123def456 ../secret>>",
            "<<ccr:abc123def456,path\\secret>>",
            "<<ccr:abc123def456..secret>>",
            "[10 items compressed to 1. Retrieve more: hash=abc123def456 ../secret]",
            "[10 items compressed to 1. Retrieve more: hash=abc123def456x]",
        ],
    )
    def test_rejects_malformed_marker_text(self, text):
        """Markers with unsafe suffixes or malformed hash boundaries are rejected."""
        assert parse_ccr_markers(text) == []
        with pytest.raises(ValueError):
            normalize_ccr_hash(text)

    def test_multiple_markers_are_returned_in_text_order(self):
        """Multiple marker families in one text are deterministic."""
        text = (
            "<<ccr:111111111111 3_rows_offloaded>> "
            "[20 lines compressed to 2. Retrieve more: hash=222222222222222222222222] "
            "<<ccr:333333333333,base64,1.0KB>>"
        )

        markers = parse_ccr_markers(text)

        assert [m.hash for m in markers] == [
            "111111111111",
            "222222222222222222222222",
            "333333333333",
        ]
        assert [m.family for m in markers] == [
            "angle_ccr",
            "bracket_retrieve",
            "angle_ccr",
        ]


class TestCCRToolDefinition:
    """Test tool definition creation for different providers."""

    def test_anthropic_format(self):
        """Anthropic tool definition has correct format."""
        tool = create_ccr_tool_definition("anthropic")

        assert tool["name"] == CCR_TOOL_NAME
        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"
        assert "hash" in tool["input_schema"]["properties"]
        assert "query" in tool["input_schema"]["properties"]
        assert tool["input_schema"]["required"] == ["hash"]

    def test_openai_format(self):
        """OpenAI tool definition has correct format."""
        tool = create_ccr_tool_definition("openai")

        assert tool["type"] == "function"
        assert tool["function"]["name"] == CCR_TOOL_NAME
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]
        assert tool["function"]["parameters"]["required"] == ["hash"]

    def test_google_format(self):
        """Google tool definition has correct format."""
        tool = create_ccr_tool_definition("google")

        assert tool["name"] == CCR_TOOL_NAME
        assert "parameters" in tool
        assert tool["parameters"]["required"] == ["hash"]


class TestCCRToolInjector:
    """Test CCRToolInjector functionality."""

    def test_scan_for_markers_finds_hash(self):
        """Scanner detects compression markers in messages."""
        messages = [
            {"role": "user", "content": "Find errors"},
            {
                "role": "tool",
                "content": '[{"id": 1}]\n[100 items compressed to 10. Retrieve more: hash=abc123def456abc123def456]',
            },
        ]

        injector = CCRToolInjector()
        hashes = injector.scan_for_markers(messages)

        assert len(hashes) == 1
        assert "abc123def456abc123def456" in hashes
        assert injector.has_compressed_content

    def test_scan_for_smartcrusher_angle_marker_finds_hash(self):
        """Scanner detects SmartCrusher angle markers in messages."""
        messages = [
            {
                "role": "tool",
                "content": '[{"id":1},{"_ccr_dropped":"<<ccr:89f81e97033e 15_rows_offloaded>>"}]',
            },
        ]

        injector = CCRToolInjector()
        hashes = injector.scan_for_markers(messages)

        assert hashes == ["89f81e97033e"]
        assert injector.has_compressed_content

    def test_scan_for_markers_multiple_hashes(self):
        """Scanner finds multiple distinct hashes."""
        messages = [
            {
                "role": "tool",
                "content": "[50 items compressed to 5. Retrieve more: hash=aaa111111111aaa111111111]",
            },
            {
                "role": "tool",
                "content": "[200 items compressed to 20. Retrieve more: hash=bbb222222222bbb222222222]",
            },
        ]

        injector = CCRToolInjector()
        hashes = injector.scan_for_markers(messages)

        assert len(hashes) == 2
        assert "aaa111111111aaa111111111" in hashes
        assert "bbb222222222bbb222222222" in hashes

    def test_scan_no_duplicates(self):
        """Scanner deduplicates repeated hashes."""
        messages = [
            {
                "role": "tool",
                "content": "[100 items compressed to 10. Retrieve more: hash=aabbcc123456aabbcc123456]",
            },
            {
                "role": "assistant",
                "content": "I see [100 items compressed to 10. Retrieve more: hash=aabbcc123456aabbcc123456]",
            },
        ]

        injector = CCRToolInjector()
        hashes = injector.scan_for_markers(messages)

        assert len(hashes) == 1

    def test_scan_anthropic_content_blocks(self):
        """Scanner handles Anthropic's content block format."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Find errors"},
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_result",
                        "content": "[100 items compressed to 10. Retrieve more: hash=b10cf0a2b3c4b10cf0a2b3c4]",
                    },
                ],
            },
        ]

        injector = CCRToolInjector()
        hashes = injector.scan_for_markers(messages)

        assert "b10cf0a2b3c4b10cf0a2b3c4" in hashes

    def test_inject_tool_when_compression_detected(self):
        """Tool is injected when compression markers are found."""
        messages = [
            {
                "role": "tool",
                "content": "[100 items compressed to 10. Retrieve more: hash=abc123def456abc123def456]",
            },
        ]

        injector = CCRToolInjector(provider="anthropic")
        injector.scan_for_markers(messages)
        tools, was_injected = injector.inject_tool_definition(None)

        assert was_injected
        assert len(tools) == 1
        assert tools[0]["name"] == CCR_TOOL_NAME

    def test_inject_tool_when_smartcrusher_marker_detected(self):
        """Tool is injected when SmartCrusher angle markers are found."""
        messages = [
            {
                "role": "tool",
                "content": '[{"_ccr_dropped":"<<ccr:89f81e97033e 15_rows_offloaded>>"}]',
            },
        ]

        injector = CCRToolInjector(provider="anthropic")
        injector.scan_for_markers(messages)
        tools, was_injected = injector.inject_tool_definition(None)

        assert was_injected
        assert len(tools) == 1
        assert tools[0]["name"] == CCR_TOOL_NAME

    def test_inject_tool_adds_to_existing(self):
        """CCR tool is added to existing tools list."""
        messages = [
            {
                "role": "tool",
                "content": "[100 items compressed to 10. Retrieve more: hash=e1e2e3f4f5f6e1e2e3f4f5f6]",
            },
        ]
        existing_tools = [{"name": "other_tool", "input_schema": {}}]

        injector = CCRToolInjector(provider="anthropic")
        injector.scan_for_markers(messages)
        tools, was_injected = injector.inject_tool_definition(existing_tools)

        assert was_injected
        assert len(tools) == 2
        assert tools[0]["name"] == "other_tool"
        assert tools[1]["name"] == CCR_TOOL_NAME

    def test_skip_injection_if_tool_present_anthropic(self):
        """Injection skipped if tool already present (Anthropic format)."""
        messages = [
            {
                "role": "tool",
                "content": "[100 items compressed to 10. Retrieve more: hash=aac123456789aac123456789]",
            },
        ]
        # Tool already present (e.g., from MCP)
        existing_tools = [{"name": CCR_TOOL_NAME, "input_schema": {}}]

        injector = CCRToolInjector(provider="anthropic")
        injector.scan_for_markers(messages)
        tools, was_injected = injector.inject_tool_definition(existing_tools)

        assert not was_injected
        assert len(tools) == 1  # Not duplicated

    def test_skip_injection_if_tool_present_openai(self):
        """Injection skipped if tool already present (OpenAI format)."""
        messages = [
            {
                "role": "tool",
                "content": "[100 items compressed to 10. Retrieve more: hash=bbc456789012bbc456789012]",
            },
        ]
        # OpenAI format tool already present
        existing_tools = [
            {"type": "function", "function": {"name": CCR_TOOL_NAME, "parameters": {}}}
        ]

        injector = CCRToolInjector(provider="openai")
        injector.scan_for_markers(messages)
        tools, was_injected = injector.inject_tool_definition(existing_tools)

        assert not was_injected
        assert len(tools) == 1

    def test_no_injection_without_compression(self):
        """No injection when no compression markers found."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "tool", "content": '{"result": "ok"}'},
        ]

        injector = CCRToolInjector()
        injector.scan_for_markers(messages)
        tools, was_injected = injector.inject_tool_definition(None)

        assert not was_injected
        assert tools == []

    def test_inject_system_instructions(self):
        """System instructions are injected when compression detected."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {
                "role": "tool",
                "content": "[100 items compressed to 10. Retrieve more: hash=abc123def456abc123def456]",
            },
        ]

        injector = CCRToolInjector(inject_system_instructions=True)
        injector.scan_for_markers(messages)
        updated = injector.inject_into_system_message(messages)

        assert "Compressed Context Available" in updated[0]["content"]
        assert "abc123def456abc123def456" in updated[0]["content"]

    def test_process_request_full_flow(self):
        """process_request handles complete injection flow."""
        messages = [
            {"role": "system", "content": "Assistant"},
            {"role": "user", "content": "Search for errors"},
            {
                "role": "tool",
                "content": "[500 items compressed to 25. Retrieve more: hash=f011f10abcdef011f10abcde]",
            },
        ]

        injector = CCRToolInjector(
            provider="anthropic",
            inject_tool=True,
            inject_system_instructions=True,
        )
        updated_messages, updated_tools, was_injected = injector.process_request(messages, None)

        assert was_injected
        assert updated_tools is not None
        assert len(updated_tools) == 1
        assert updated_tools[0]["name"] == CCR_TOOL_NAME
        assert "Compressed Context Available" in updated_messages[0]["content"]


class TestParseToolCall:
    """Test parsing of tool calls from LLM responses."""

    def test_parse_anthropic_format(self):
        """Parse Anthropic tool call format."""
        tool_call = {
            "id": "toolu_123",
            "name": CCR_TOOL_NAME,
            "input": {"hash": "abc123def456abc123def456", "query": "errors"},
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")

        assert hash_key == "abc123def456abc123def456"
        assert query == "errors"

    def test_parse_openai_format(self):
        """Parse OpenAI tool call format."""
        tool_call = {
            "id": "call_123",
            "function": {
                "name": CCR_TOOL_NAME,
                "arguments": json.dumps({"hash": "def456abc123def456abc123", "query": None}),
            },
        }

        hash_key, query = parse_tool_call(tool_call, "openai")

        assert hash_key == "def456abc123def456abc123"
        assert query is None

    def test_parse_non_ccr_tool(self):
        """Returns None for non-CCR tool calls."""
        tool_call = {
            "name": "other_tool",
            "input": {"param": "value"},
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")

        assert hash_key is None
        assert query is None

    def test_parse_malformed_openai_args(self):
        """Handles malformed JSON in OpenAI arguments."""
        tool_call = {
            "id": "call_123",
            "function": {
                "name": CCR_TOOL_NAME,
                "arguments": "not valid json",
            },
        }

        hash_key, query = parse_tool_call(tool_call, "openai")

        assert hash_key is None

    def test_parse_accepts_smartcrusher_hash(self):
        """Parse accepts SmartCrusher's 12-hex local CCR hash."""
        tool_call = {
            "id": "toolu_123",
            "name": CCR_TOOL_NAME,
            "input": {"hash": "89f81e97033e", "query": "errors"},
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")

        assert hash_key == "89f81e97033e"
        assert query == "errors"

    def test_parse_accepts_smartcrusher_marker_text(self):
        """Parse accepts full SmartCrusher marker text and normalizes to hash."""
        tool_call = {
            "id": "toolu_123",
            "name": CCR_TOOL_NAME,
            "input": {"hash": "<<ccr:89f81e97033e 15_rows_offloaded>>"},
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")

        assert hash_key == "89f81e97033e"
        assert query is None

    def test_parse_accepts_bracket_marker_text(self):
        """Parse accepts full bracket marker text and normalizes to hash."""
        marker = "[100 items compressed to 10. Retrieve more: hash=abc123def456abc123def456]"
        tool_call = {
            "id": "toolu_123",
            "name": CCR_TOOL_NAME,
            "input": {"hash": marker},
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")

        assert hash_key == "abc123def456abc123def456"
        assert query is None


class TestHashSecurityValidation:
    """Test hash validation security measures.

    Local CCR hashes must match one of the explicit supported emitter
    forms: 12 hex chars for SmartCrusher markers or 24 hex chars for
    compression_store/live-zone keys.
    """

    def test_rejects_short_hash(self):
        """Rejects hash that's too short (potential spoofing attack)."""
        tool_call = {
            "name": CCR_TOOL_NAME,
            "input": {"hash": "abc123"},  # Only 6 chars
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")
        assert hash_key is None  # Rejected

    def test_rejects_long_hash(self):
        """Rejects hash that's too long."""
        tool_call = {
            "name": CCR_TOOL_NAME,
            "input": {"hash": "abc123def456abc123def456abc123"},  # 30 chars
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")
        assert hash_key is None  # Rejected

    def test_rejects_non_hex_characters(self):
        """Rejects hash with non-hex characters."""
        tool_call = {
            "name": CCR_TOOL_NAME,
            "input": {"hash": "abc123xyz456abc123xyz456"},  # Contains xyz
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")
        assert hash_key is None  # Rejected

    def test_rejects_path_traversal_marker(self):
        """Rejects marker text with unsafe path traversal metadata."""
        tool_call = {
            "name": CCR_TOOL_NAME,
            "input": {"hash": "<<ccr:abc123def456 ../secret>>"},
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")
        assert hash_key is None
        assert query is None

    def test_rejects_hash_with_whitespace(self):
        """Rejects raw hash strings with whitespace."""
        tool_call = {
            "name": CCR_TOOL_NAME,
            "input": {"hash": "abc123def456 "},
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")
        assert hash_key is None
        assert query is None

    def test_accepts_valid_24_char_hash(self):
        """Accepts properly formatted 24-char hex hash."""
        tool_call = {
            "name": CCR_TOOL_NAME,
            "input": {"hash": "abc123def456abc123def456"},
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")
        assert hash_key == "abc123def456abc123def456"

    def test_accepts_valid_12_char_hash(self):
        """Accepts properly formatted 12-char SmartCrusher hash."""
        tool_call = {
            "name": CCR_TOOL_NAME,
            "input": {"hash": "89f81e97033e"},
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")
        assert hash_key == "89f81e97033e"

    def test_accepts_uppercase_hex(self):
        """Accepts uppercase hex characters and normalizes to lowercase."""
        tool_call = {
            "name": CCR_TOOL_NAME,
            "input": {"hash": "ABC123DEF456ABC123DEF456"},
        }

        hash_key, query = parse_tool_call(tool_call, "anthropic")
        assert hash_key == "abc123def456abc123def456"


class TestSystemInstructions:
    """Test system instruction generation."""

    def test_create_instructions_single_hash(self):
        """Instructions include single hash."""
        instructions = create_system_instructions(["hash123"])

        assert "hash123" in instructions
        assert CCR_TOOL_NAME in instructions
        assert "Compressed Context Available" in instructions

    def test_create_instructions_multiple_hashes(self):
        """Instructions include multiple hashes."""
        hashes = ["hash1", "hash2", "hash3"]
        instructions = create_system_instructions(hashes)

        for h in hashes:
            assert h in instructions

    def test_create_instructions_truncates_many_hashes(self):
        """Instructions truncate when many hashes present."""
        hashes = [f"hash{i}" for i in range(10)]
        instructions = create_system_instructions(hashes)

        # First 5 should be present, rest truncated
        assert "hash0" in instructions
        assert "hash4" in instructions
        assert "..." in instructions


class TestAlternativeMarkerFormats:
    """Test CCR marker detection for different compressor formats.

    Different compressors use slightly different marker formats:
    - SmartCrusher: [N items compressed to M. Retrieve more: hash=xxx]
    - TextCompressor: [N lines compressed to M. Retrieve more: hash=xxx]
    - LogCompressor: [N lines compressed to M. Retrieve more: hash=xxx]
    - SearchCompressor: [N matches compressed to M. Retrieve more: hash=xxx]
    - Kompress: [N items compressed to M. Retrieve more: hash=xxx]

    The CCRToolInjector should detect all these formats.
    """

    def test_textcompressor_format(self):
        """Detects TextCompressor marker format (lines)."""
        messages = [
            {
                "role": "assistant",
                "content": "Build output:\n[500 lines compressed to 50. Retrieve more: hash=aabbccddeeff001122334455]",
            },
        ]

        injector = CCRToolInjector()
        hashes = injector.scan_for_markers(messages)

        assert len(hashes) == 1
        assert "aabbccddeeff001122334455" in hashes

    def test_searchcompressor_format(self):
        """Detects SearchCompressor marker format (matches)."""
        messages = [
            {
                "role": "assistant",
                "content": "Search results:\n[100 matches compressed to 10. Retrieve more: hash=112233445566778899001122]",
            },
        ]

        injector = CCRToolInjector()
        hashes = injector.scan_for_markers(messages)

        assert len(hashes) == 1
        assert "112233445566778899001122" in hashes

    def test_mixed_compressor_formats(self):
        """Detects multiple marker formats in same conversation."""
        messages = [
            {
                "role": "assistant",
                "content": "Search results:\n[50 matches compressed to 5. Retrieve more: hash=aaaa11111111aaaa11111111]",
            },
            {
                "role": "assistant",
                "content": "Build logs:\n[200 lines compressed to 20. Retrieve more: hash=bbbb22222222bbbb22222222]",
            },
            {
                "role": "assistant",
                "content": "Database:\n[1000 items compressed to 100. Retrieve more: hash=cccc33333333cccc33333333]",
            },
        ]

        injector = CCRToolInjector()
        hashes = injector.scan_for_markers(messages)

        assert len(hashes) == 3
        assert "aaaa11111111aaaa11111111" in hashes
        assert "bbbb22222222bbbb22222222" in hashes
        assert "cccc33333333cccc33333333" in hashes

    def test_generic_compressed_marker(self):
        """Detects generic compression markers via fallback pattern."""
        messages = [
            {
                "role": "assistant",
                "content": "Data:\n[Content compressed for efficiency. hash=fedcba9876543210fedcba98]",
            },
        ]

        injector = CCRToolInjector()
        hashes = injector.scan_for_markers(messages)

        assert len(hashes) == 1
        assert "fedcba9876543210fedcba98" in hashes


class TestCCRMarkerRetrieveIntegration:
    """Integration tests for marker text through local retrieve flow."""

    def test_existing_bracket_marker_tool_call_resolves_store_entry(self):
        """Bracket marker text can parse, inject, and retrieve from compression_store."""
        reset_compression_store()
        try:
            store = get_compression_store()
            original = json.dumps([{"id": 1, "message": "full original"}])
            hash_key = store.store(original=original, compressed="[]")
            marker = f"[10 items compressed to 1. Retrieve more: hash={hash_key}]"

            parsed_marker = parse_first_ccr_marker(marker)
            assert parsed_marker is not None
            assert parsed_marker.hash == hash_key

            injector = CCRToolInjector()
            hashes = injector.scan_for_markers([{"role": "tool", "content": marker}])
            assert hashes == [hash_key]

            parsed_hash, query = parse_tool_call(
                {"name": CCR_TOOL_NAME, "input": {"hash": marker}},
                "anthropic",
            )
            assert parsed_hash == hash_key
            assert query is None

            entry = store.retrieve(parsed_hash)
            assert entry is not None
            assert entry.original_content == original
        finally:
            reset_compression_store()

    def test_smartcrusher_marker_end_to_end_resolves_store_entry(self):
        """SmartCrusher-emitted marker flows through parser, injection, tool call, and store."""
        pytest.importorskip("headroom._core")

        from headroom.config import CCRConfig
        from headroom.config import SmartCrusherConfig as PyConfig
        from headroom.transforms.smart_crusher import SmartCrusher

        reset_compression_store()
        try:
            crusher = SmartCrusher(PyConfig(), ccr_config=CCRConfig(), with_compaction=False)
            original = [
                {
                    "id": i,
                    "level": "error" if i % 30 == 0 else "info",
                    "message": f"line {i}",
                }
                for i in range(80)
            ]
            content = json.dumps(original)

            crushed, was_modified, info = crusher._smart_crush_content(content)

            assert was_modified, f"expected SmartCrusher modification, got info={info!r}"
            assert "<<ccr:" in crushed

            markers = [m for m in parse_ccr_markers(crushed) if m.family == "angle_ccr"]
            assert markers, f"expected angle CCR marker in {crushed[:200]!r}"
            marker = markers[0]

            injector = CCRToolInjector()
            hashes = injector.scan_for_markers([{"role": "tool", "content": crushed}])
            assert marker.hash in hashes

            parsed_hash, query = parse_tool_call(
                {"name": CCR_TOOL_NAME, "input": {"hash": marker.raw}},
                "anthropic",
            )
            assert parsed_hash == marker.hash
            assert query is None

            entry = get_compression_store().retrieve(parsed_hash)
            assert entry is not None
            assert json.loads(entry.original_content) == original
        finally:
            reset_compression_store()
