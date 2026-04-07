# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""AgentRuntime — the 'Architect' layer.

Handles LLM interaction with the 3D-native system prompt.
Runs a tool-calling loop: LLM decides what to do, we execute it,
feed results back, repeat until the LLM gives a final answer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import litellm

from bowerbot.config import Settings
from bowerbot.prompts import load_prompt
from bowerbot.scene_builder import SceneBuilder
from bowerbot.skills.base import ToolResult
from bowerbot.skills.registry import SkillRegistry
from bowerbot.token_manager import TokenManager

logger = logging.getLogger(__name__)

MAX_VALIDATION_RETRIES = 2


@dataclass
class AgentRuntime:
    """Manages LLM interaction with tool-calling loops for scene assembly."""

    settings: Settings
    scene_builder: SceneBuilder
    skill_registry: SkillRegistry
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    _system_prompt: str = field(default="", init=False)
    _tools: list[dict[str, Any]] = field(default_factory=list, init=False)
    _token_manager: TokenManager = field(init=False)
    _scene_tool_names: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        """Build the system prompt and cache the tool list."""
        self._system_prompt = self._build_system_prompt()
        self._tools = self.scene_builder.get_tools() + self.skill_registry.get_all_tools()
        self._token_manager = TokenManager(self.settings.llm)
        self._scene_tool_names = self.scene_builder.get_tool_names()

        logger.info(
            "System prompt: %d chars, %d tools from scene builder + %d skill(s)",
            len(self._system_prompt),
            len(self._tools),
            self.skill_registry.skill_count,
        )

    def _build_system_prompt(self) -> str:
        """Assemble the system prompt from core, scene building, and skill sections."""
        sections = [
            load_prompt("core"),
            f"# Scene Building\n\n{load_prompt('scene_building')}",
        ]

        skill_prompts = self.skill_registry.get_skill_prompts()
        if skill_prompts:
            sections.append(
                f"# Extension Skills\n\n{skill_prompts}"
            )

        return "\n\n---\n\n".join(sections)

    async def process(self, user_message: str) -> str:
        """Process a user message through the full tool-calling loop."""
        self.conversation_history.append({"role": "user", "content": user_message})
        validation_retries = 0

        for round_num in range(self.settings.llm.max_tool_rounds):
            logger.info("Agent loop round %s", round_num + 1)

            messages, usage = await self._token_manager.prepare_messages(
                self._system_prompt, self.conversation_history,
            )

            kwargs: dict[str, Any] = {
                "model": self.settings.llm.model,
                "messages": messages,
                "max_tokens": self.settings.llm.max_tokens,
                "temperature": self.settings.llm.temperature,
                "num_retries": self.settings.llm.num_retries,
                "timeout": self.settings.llm.request_timeout,
            }

            api_key = self.settings.get_api_key()
            if api_key:
                kwargs["api_key"] = api_key

            if self._tools:
                kwargs["tools"] = self._tools

            response = await litellm.acompletion(**kwargs)
            choice = response.choices[0]
            message = choice.message

            if message.tool_calls:
                logger.info("LLM requested %s tool call(s)", len(message.tool_calls))

                self.conversation_history.append(message.model_dump())

                for tool_call in message.tool_calls:
                    func_name = tool_call.function.name
                    func_args = json.loads(tool_call.function.arguments)

                    logger.info("Executing tool: %s(%s)", func_name, func_args)

                    result = await self._dispatch_tool(func_name, func_args)

                    self.conversation_history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            result.data if result.success else {"error": result.error}
                        ),
                    })

                if self._nudge_on_validation_errors(
                    message.tool_calls, validation_retries,
                ):
                    validation_retries += 1

                continue

            content = message.content or ""
            self.conversation_history.append({"role": "assistant", "content": content})
            return content

        return "Reached maximum tool-calling rounds. Please try a simpler request."

    async def _dispatch_tool(
        self, func_name: str, func_args: dict[str, Any],
    ) -> ToolResult:
        """Route a tool call to scene builder or skill registry."""
        if func_name in self._scene_tool_names:
            return await self.scene_builder.execute_tool(func_name, func_args)
        return await self.skill_registry.execute_tool(func_name, func_args)

    def _nudge_on_validation_errors(
        self,
        tool_calls: list,
        retries: int,
    ) -> bool:
        """If validate_scene returned errors, nudge the LLM to fix them.

        Returns ``True`` if a nudge was added to the conversation.
        """
        for tool_call in tool_calls:
            if tool_call.function.name != "validate_scene":
                continue

            for msg in reversed(self.conversation_history):
                if msg.get("tool_call_id") == tool_call.id:
                    try:
                        content = json.loads(msg["content"])
                    except (json.JSONDecodeError, TypeError):
                        break

                    if (
                        not content.get("is_valid", True)
                        and retries < MAX_VALIDATION_RETRIES
                    ):
                        self.conversation_history.append({
                            "role": "user",
                            "content": (
                                "The scene has validation errors. "
                                "Please fix the issues listed above, "
                                "then call validate_scene again."
                            ),
                        })
                        logger.info(
                            "Validation retry nudge (%d/%d)",
                            retries + 1, MAX_VALIDATION_RETRIES,
                        )
                        return True
                    break

        return False

    def reset(self) -> None:
        """Clear conversation history for a new session."""
        self.conversation_history.clear()
