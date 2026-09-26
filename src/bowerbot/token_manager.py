# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Token management — context window optimization for long sessions.

Keeps conversations within model context limits by:
1. Compressing old tool results (lightweight, always runs)
2. Summarizing older history when approaching the token budget
   (heavier, only when needed)

Follows OpenClaw-style sliding-window compaction: old messages get
summarized, recent messages stay verbatim, scene state is always
re-queryable via tools.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import litellm

from bowerbot.config import LLMSettings
from bowerbot.prompts import load_prompt

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Tracks token budget and compression state for observability."""

    prompt_tokens: int
    context_budget: int
    history_compressed: bool
    history_summarized: bool


class TokenCounter:
    """Wraps litellm's per-model token counting."""

    @staticmethod
    def count_messages(model: str, messages: list[dict[str, Any]]) -> int:
        """Count tokens for a message list using the model's tokenizer."""
        try:
            count: int = litellm.token_counter(model=model, messages=messages)
            return count
        except Exception:
            total_chars = sum(
                len(json.dumps(m.get("content", ""))) for m in messages
            )
            return total_chars // 4

    @staticmethod
    def get_context_limit(model: str) -> int:
        """Return the context window size for a model, or 128k when litellm doesn't know it."""
        try:
            limit = litellm.get_model_info(model).get("max_input_tokens")
        except Exception:
            limit = None
        return limit or 128_000


class TokenManager:
    """Manages conversation context to stay within model token limits.

    Called by AgentRuntime before each LLM call. Applies two
    optimizations in order:

    1. Tool result compression — old tool outputs are replaced with
       compact placeholders. The LLM can always re-call the tool.
    2. History summarization — when token count exceeds the threshold,
       older messages are summarized via a short LLM call.
    """

    def __init__(self, llm_settings: LLMSettings) -> None:
        self._settings = llm_settings
        self._model = llm_settings.model
        self._counter = TokenCounter()

        context_limit = (
            llm_settings.context_window
            if llm_settings.context_window is not None
            else self._counter.get_context_limit(self._model)
        )

        self._token_budget = context_limit - llm_settings.max_tokens

        logger.info(
            f"TokenManager: model={self._model}, "
            f"context={context_limit}, "
            f"budget={self._token_budget}, "
            f"threshold={llm_settings.summarization_threshold}"
        )

    @property
    def token_budget(self) -> int:
        """Available tokens for system prompt + conversation history."""
        return self._token_budget

    async def prepare_messages(
        self,
        system_prompt: str,
        history: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], TokenUsage]:
        """Build the message list, compressing/summarizing if needed.

        Returns the final messages list and a TokenUsage snapshot.
        """
        compressed = False
        summarized = False

        # Step 1: Compress old tool results (always, lightweight)
        working_history = self._compress_tool_results(history)

        # Build candidate messages
        messages = [
            {"role": "system", "content": system_prompt},
            *working_history,
        ]

        # Count current token usage
        prompt_tokens = self._counter.count_messages(self._model, messages)
        trigger_point = int(
            self._token_budget * self._settings.summarization_threshold
        )

        if (
            prompt_tokens > trigger_point
            and len(working_history) > self._settings.min_keep_recent
        ):
            logger.info(
                f"Token usage {prompt_tokens}/{self._token_budget} "
                f"exceeds threshold "
                f"({self._settings.summarization_threshold:.0%}). "
                f"Summarizing history."
            )
            working_history = await self._summarize_history(working_history)
            messages = [
                {"role": "system", "content": system_prompt},
                *working_history,
            ]
            prompt_tokens = self._counter.count_messages(self._model, messages)
            summarized = True

        if working_history is not history:
            compressed = True

        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            context_budget=self._token_budget,
            history_compressed=compressed,
            history_summarized=summarized,
        )

        logger.info(
            f"Prepared messages: {prompt_tokens} tokens "
            f"({prompt_tokens * 100 // self._token_budget}% of budget), "
            f"compressed={compressed}, summarized={summarized}"
        )

        return messages, usage

    def _compress_tool_results(
        self, history: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Replace old tool results with compact placeholders.

        Tool results from list_scene, search_assets, list_my_models,
        and search_my_models older than the configured age threshold
        are compressed. The LLM can always re-call the tool.
        """
        user_turn_count = 0
        turn_ages: dict[int, int] = {}

        for i in range(len(history) - 1, -1, -1):
            if history[i].get("role") == "user":
                user_turn_count += 1
            turn_ages[i] = user_turn_count

        result = []
        for i, msg in enumerate(history):
            if (
                msg.get("role") == "tool"
                and turn_ages.get(i, 0)
                > self._settings.tool_result_age_threshold
            ):
                content = msg.get("content", "")
                compressed_content = self._compress_single_result(content)
                if compressed_content != content:
                    result.append({**msg, "content": compressed_content})
                    continue

            result.append(msg)

        return result

    def _compress_single_result(self, content: str) -> str:
        """Compress a single tool result if it's a known heavy format."""
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return content

        # Compress list_scene results (list of objects with bounds)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            first = data[0]
            if "prim_path" in first and "bounds" in first:
                count = len(data)
                names = [
                    obj.get("prim_path", "").split("/")[-1]
                    for obj in data
                ]
                return json.dumps({
                    "summary": f"{count} object(s) in scene",
                    "objects": names,
                    "note": "Call list_scene for current details.",
                })

        # Compress search results (list with uid/name)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            first = data[0]
            if "uid" in first and "name" in first:
                count = len(data)
                names = [item.get("name", "") for item in data]
                return json.dumps({
                    "summary": f"{count} model(s) found",
                    "names": names,
                    "note": "Search again for full details.",
                })

        return content

    async def _summarize_history(
        self,
        history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Summarize older messages, keeping recent ones verbatim.

        Splits history into old (summarized) and recent (kept).
        The split point respects tool_call/tool_result pairs.
        """
        split = self._find_safe_split(history)

        if split <= 0:
            return history

        old_messages = history[:split]
        recent_messages = history[split:]

        summary_messages = [
            {"role": "system", "content": load_prompt("summary")},
            {
                "role": "user",
                "content": self._format_history_for_summary(old_messages),
            },
        ]

        try:
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": summary_messages,
                "max_tokens": self._settings.summary_max_tokens,
                "temperature": 0.0,
            }
            if self._settings.api_key:
                kwargs["api_key"] = self._settings.api_key

            response = await litellm.acompletion(**kwargs)
            summary_text = response.choices[0].message.content or ""
        except Exception as e:
            logger.warning(
                f"Summarization failed, falling back to truncation: {e}"
            )
            summary_text = self._fallback_summary(old_messages)

        summary_message = {
            "role": "system",
            "content": (
                f"## Session Context (summarized)\n\n{summary_text}"
            ),
        }

        return [summary_message, *recent_messages]

    def _find_safe_split(self, history: list[dict[str, Any]]) -> int:
        """Find a split point that doesn't break tool_call/result pairs.

        Walks backward to find a user or plain assistant message,
        keeping at least min_keep_recent messages in the recent portion.
        """
        min_keep = self._settings.min_keep_recent

        if len(history) <= min_keep:
            return 0

        candidate = len(history) - min_keep

        while candidate > 0:
            msg = history[candidate]
            role = msg.get("role", "")

            if role == "user":
                return candidate

            if role == "assistant" and not msg.get("tool_calls"):
                return candidate

            candidate -= 1

        return 0

    def _format_history_for_summary(
        self, messages: list[dict[str, Any]]
    ) -> str:
        """Format old messages into readable text for the summarizer."""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if role == "tool":
                if len(content) > 500:
                    content = content[:500] + "... (truncated)"
                lines.append(f"[Tool Result]: {content}")
            elif role == "assistant":
                if msg.get("tool_calls"):
                    tool_names = [
                        tc.get("function", {}).get("name", "?")
                        for tc in msg.get("tool_calls", [])
                    ]
                    lines.append(
                        f"[Assistant called tools]: {', '.join(tool_names)}"
                    )
                else:
                    lines.append(f"[Assistant]: {content}")
            elif role == "user":
                lines.append(f"[User]: {content}")

        return "\n".join(lines)

    def _fallback_summary(self, messages: list[dict[str, Any]]) -> str:
        """Generate a basic summary without an LLM call."""
        user_messages = [
            m.get("content", "")
            for m in messages
            if m.get("role") == "user"
        ]
        return (
            f"Previous conversation covered {len(messages)} messages. "
            f"User requests included: {'; '.join(user_messages[:5])}"
        )
