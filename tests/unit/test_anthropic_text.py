"""Unit tests for agent.utils.anthropic_text.extract_text.

Tests cover:
- Single text block returned stripped
- Thinking blocks preceding the text block are skipped
- Multiple text blocks are concatenated in order
- No text blocks returns an empty string
- Blocks without a real "text" type attribute are ignored
"""

from __future__ import annotations

from unittest.mock import MagicMock

from agent.utils.anthropic_text import extract_text


def _response(*blocks) -> MagicMock:
    response = MagicMock()
    response.content = list(blocks)
    return response


def test_single_text_block_returned_stripped():
    block = MagicMock(type="text", text="  hello world  ")
    assert extract_text(_response(block)) == "hello world"


def test_thinking_block_before_text_is_skipped():
    thinking = MagicMock(type="thinking", thinking="pondering...")
    text = MagicMock(type="text", text="the answer")
    assert extract_text(_response(thinking, text)) == "the answer"


def test_multiple_text_blocks_concatenated_in_order():
    first = MagicMock(type="text", text="first ")
    second = MagicMock(type="text", text="second")
    assert extract_text(_response(first, second)) == "first second"


def test_no_text_blocks_returns_empty_string():
    thinking = MagicMock(type="thinking", thinking="pondering...")
    assert extract_text(_response(thinking)) == ""


def test_block_without_type_attribute_is_ignored():
    bare = MagicMock()
    assert extract_text(_response(bare)) == ""
