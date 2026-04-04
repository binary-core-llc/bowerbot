# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test token management: compression, summarization, and budget tracking."""

import json
from unittest.mock import AsyncMock, patch

from bowerbot.config import LLMSettings
from bowerbot.token_manager import TokenCounter, TokenManager, TokenUsage


def make_settings(**overrides) -> LLMSettings:
    """Create LLMSettings with test defaults."""
    defaults = {
        "model": "gpt-4o",
        "api_key": "test-key",
        "context_window": 8000,
        "max_tokens": 1000,
        "summarization_threshold": 0.75,
        "tool_result_age_threshold": 2,
        "min_keep_recent": 6,
        "summary_max_tokens": 512,
    }
    defaults.update(overrides)
    return LLMSettings(**defaults)


def build_history(user_turns: int) -> list[dict]:
    """Build a simple conversation history with N user/assistant pairs."""
    history = []
    for i in range(user_turns):
        history.append({"role": "user", "content": f"User message {i}"})
        history.append({"role": "assistant", "content": f"Assistant response {i}"})
    return history


def build_history_with_tools(user_turns: int) -> list[dict]:
    """Build history with tool calls interleaved."""
    history = []
    for i in range(user_turns):
        history.append({"role": "user", "content": f"User message {i}"})
        history.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"call_{i}",
                "function": {"name": "list_scene", "arguments": "{}"},
            }],
        })
        history.append({
            "role": "tool",
            "tool_call_id": f"call_{i}",
            "content": json.dumps([{
                "prim_path": f"/Scene/Furniture/Table_{i:02d}",
                "asset": f"assets/table_{i}.usdz",
                "position": {"x": 5.0, "y": 0.0, "z": 4.0},
                "bounds": {
                    "min": {"x": 4.5, "y": 0.0, "z": 3.5},
                    "max": {"x": 5.5, "y": 0.81, "z": 4.5},
                },
            }]),
        })
        history.append({"role": "assistant", "content": f"Done with step {i}"})
    return history


# ─── TokenCounter ────────────────────────────────────────────────


def test_token_counter_fallback():
    """TokenCounter falls back to char-based estimate on error."""
    with patch("litellm.token_counter", side_effect=Exception("no tokenizer")):
        count = TokenCounter.count_messages(
            "unknown-model",
            [{"role": "user", "content": "hello world"}],
        )
        assert count > 0


def test_token_counter_context_limit_fallback():
    """get_context_limit returns 128k default on error."""
    with patch("litellm.get_model_info", side_effect=Exception("unknown")):
        limit = TokenCounter.get_context_limit("unknown-model")
        assert limit == 128_000


# ─── Tool Result Compression ────────────────────────────────────


def test_compress_old_list_scene_results():
    """Old list_scene tool results are compressed to summaries."""
    settings = make_settings()
    manager = TokenManager(settings)

    history = build_history_with_tools(user_turns=5)

    compressed = manager._compress_tool_results(history)

    # Old tool results (more than 2 user turns ago) should be compressed
    compressed_count = 0
    for msg in compressed:
        if msg.get("role") == "tool":
            content = json.loads(msg["content"])
            if isinstance(content, dict) and "summary" in content:
                compressed_count += 1

    assert compressed_count > 0, "Expected some tool results to be compressed"


def test_recent_tool_results_preserved():
    """Tool results within the age threshold are NOT compressed."""
    settings = make_settings()
    manager = TokenManager(settings)

    history = build_history_with_tools(user_turns=2)

    compressed = manager._compress_tool_results(history)

    # With only 2 turns, nothing should be compressed
    for msg in compressed:
        if msg.get("role") == "tool":
            content = json.loads(msg["content"])
            assert isinstance(content, list), (
                "Recent tool result should be preserved as-is"
            )


def test_compress_search_results():
    """Old search results with uid/name are compressed."""
    settings = make_settings()
    manager = TokenManager(settings)

    search_result = json.dumps([
        {"uid": "abc123", "name": "Round Table", "tags": ["furniture"]},
        {"uid": "def456", "name": "Coffee Mug", "tags": ["props"]},
    ])

    history = [
        {"role": "user", "content": "search for stuff"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_0",
            "function": {
                "name": "sketchfab__search_my_models",
                "arguments": "{}",
            },
        }]},
        {"role": "tool", "tool_call_id": "call_0", "content": search_result},
        {"role": "assistant", "content": "Found 2 models"},
        # Add enough user turns to make the above "old"
        {"role": "user", "content": "msg 1"},
        {"role": "assistant", "content": "resp 1"},
        {"role": "user", "content": "msg 2"},
        {"role": "assistant", "content": "resp 2"},
        {"role": "user", "content": "msg 3"},
        {"role": "assistant", "content": "resp 3"},
    ]

    compressed = manager._compress_tool_results(history)

    tool_msg = [m for m in compressed if m.get("role") == "tool"][0]
    content = json.loads(tool_msg["content"])
    assert "summary" in content
    assert "Round Table" in content["names"]
    assert "Coffee Mug" in content["names"]


def test_compress_non_json_tool_results_unchanged():
    """Non-JSON tool results pass through without modification."""
    settings = make_settings()
    manager = TokenManager(settings)

    result = manager._compress_single_result("plain text result")
    assert result == "plain text result"


# ─── Safe Split ──────────────────────────────────────────────────


def test_safe_split_on_user_message():
    """Split point lands on a user message boundary."""
    settings = make_settings(min_keep_recent=4)
    manager = TokenManager(settings)

    history = build_history(user_turns=6)
    split = manager._find_safe_split(history)

    assert split > 0
    assert history[split]["role"] == "user"


def test_safe_split_short_history():
    """Short history returns split=0 (no summarization needed)."""
    settings = make_settings(min_keep_recent=6)
    manager = TokenManager(settings)

    history = build_history(user_turns=2)
    split = manager._find_safe_split(history)

    assert split == 0


def test_safe_split_never_breaks_tool_pairs():
    """Split never lands on a tool result message."""
    settings = make_settings(min_keep_recent=4)
    manager = TokenManager(settings)

    history = build_history_with_tools(user_turns=6)
    split = manager._find_safe_split(history)

    if split > 0:
        role = history[split]["role"]
        assert role in ("user", "assistant"), (
            f"Split landed on '{role}', expected user or assistant"
        )
        if role == "assistant":
            assert not history[split].get("tool_calls"), (
                "Split landed on assistant with tool_calls"
            )


# ─── Prepare Messages ───────────────────────────────────────────


async def test_prepare_messages_under_budget():
    """When under budget, messages pass through with compression only."""
    settings = make_settings(context_window=100_000)
    manager = TokenManager(settings)

    history = build_history(user_turns=3)

    with patch.object(
        TokenCounter, "count_messages", return_value=500
    ):
        messages, usage = await manager.prepare_messages("system prompt", history)

    assert not usage.history_summarized
    assert usage.prompt_tokens == 500
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "system prompt"


async def test_prepare_messages_triggers_summarization():
    """When over threshold, summarization is triggered."""
    settings = make_settings(
        context_window=1000,
        max_tokens=200,
        summarization_threshold=0.5,
    )
    manager = TokenManager(settings)

    history = build_history(user_turns=10)

    call_count = 0

    def mock_count(model, messages):
        nonlocal call_count
        call_count += 1
        # First call: over threshold. After summarization: under.
        return 500 if call_count == 1 else 100

    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content="Summary of conversation"))
    ]

    with (
        patch.object(TokenCounter, "count_messages", side_effect=mock_count),
        patch("litellm.acompletion", return_value=mock_response),
    ):
        messages, usage = await manager.prepare_messages("system prompt", history)

    assert usage.history_summarized


async def test_prepare_messages_fallback_on_summarization_failure():
    """If LLM summarization fails, fallback summary is used."""
    settings = make_settings(
        context_window=1000,
        max_tokens=200,
        summarization_threshold=0.5,
    )
    manager = TokenManager(settings)

    history = build_history(user_turns=10)

    call_count = 0

    def mock_count(model, messages):
        nonlocal call_count
        call_count += 1
        return 500 if call_count == 1 else 100

    with (
        patch.object(TokenCounter, "count_messages", side_effect=mock_count),
        patch("litellm.acompletion", side_effect=Exception("API error")),
    ):
        messages, usage = await manager.prepare_messages("system prompt", history)

    # Should still succeed with fallback
    assert usage.history_summarized
    # Fallback summary should mention message count
    summary_msgs = [
        m for m in messages
        if m.get("role") == "system" and "summarized" in m.get("content", "")
    ]
    assert len(summary_msgs) == 1


# ─── Format History for Summary ──────────────────────────────────


def test_format_history_truncates_long_tool_results():
    """Tool results over 500 chars are truncated in the summary input."""
    settings = make_settings()
    manager = TokenManager(settings)

    messages = [
        {"role": "tool", "content": "x" * 1000},
    ]

    formatted = manager._format_history_for_summary(messages)
    assert "(truncated)" in formatted
    assert len(formatted) < 1000


def test_format_history_includes_tool_call_names():
    """Assistant messages with tool_calls show the tool names."""
    settings = make_settings()
    manager = TokenManager(settings)

    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"function": {"name": "place_asset"}},
                {"function": {"name": "list_scene"}},
            ],
        },
    ]

    formatted = manager._format_history_for_summary(messages)
    assert "place_asset" in formatted
    assert "list_scene" in formatted


# ─── TokenUsage ──────────────────────────────────────────────────


def test_token_usage_dataclass():
    """TokenUsage holds the expected fields."""
    usage = TokenUsage(
        prompt_tokens=1500,
        context_budget=8000,
        history_compressed=True,
        history_summarized=False,
    )
    assert usage.prompt_tokens == 1500
    assert usage.context_budget == 8000
    assert usage.history_compressed is True
    assert usage.history_summarized is False


# ─── Token Budget ────────────────────────────────────────────────


def test_token_budget_calculation():
    """Token budget = context_window - max_tokens."""
    settings = make_settings(context_window=8000, max_tokens=1000)
    manager = TokenManager(settings)

    assert manager.token_budget == 7000


def test_token_budget_auto_detect():
    """When context_window is None, auto-detect from litellm."""
    settings = make_settings(context_window=None, max_tokens=1000)

    with patch.object(TokenCounter, "get_context_limit", return_value=128_000):
        manager = TokenManager(settings)

    assert manager.token_budget == 127_000
