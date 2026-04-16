# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool dispatcher — aggregates tool definitions and routes calls.

Every module under :mod:`bowerbot.tools` exposes a ``TOOLS`` list
(:class:`~bowerbot.skills.base.Tool`) and a ``HANDLERS`` mapping
``name -> callable(state, params) -> ToolResult``. The dispatcher
collects them into a single registry so the agent can present one
tool list to the LLM and route calls to the matching handler.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools import (
    asset_tools,
    light_tools,
    material_tools,
    stage_tools,
    validation_tools,
)

ToolHandler = Callable[[SceneState, dict[str, Any]], ToolResult | Awaitable[ToolResult]]


def _collect_tools() -> list[Tool]:
    """Flatten every tool module's ``TOOLS`` list into one registry."""
    tools: list[Tool] = []
    tools.extend(stage_tools.TOOLS)
    tools.extend(asset_tools.TOOLS)
    tools.extend(light_tools.TOOLS)
    tools.extend(material_tools.TOOLS)
    tools.extend(validation_tools.TOOLS)
    return tools


def _collect_handlers() -> dict[str, ToolHandler]:
    """Flatten every tool module's ``HANDLERS`` dict into one registry."""
    handlers: dict[str, ToolHandler] = {}
    for module in (
        stage_tools, asset_tools, light_tools,
        material_tools, validation_tools,
    ):
        handlers.update(module.HANDLERS)
    return handlers


TOOLS: list[Tool] = _collect_tools()
HANDLERS: dict[str, ToolHandler] = _collect_handlers()


def get_tool_schemas() -> list[dict[str, Any]]:
    """Return all tool definitions in LLM function-calling schema form."""
    return [tool.to_llm_schema() for tool in TOOLS]


def get_tool_names() -> set[str]:
    """Return the set of tool names owned by the dispatcher."""
    return set(HANDLERS.keys())


async def execute(
    state: SceneState, tool_name: str, params: dict[str, Any],
) -> ToolResult:
    """Route a tool call by name to its registered handler."""
    handler = HANDLERS.get(tool_name)
    if handler is None:
        return ToolResult(
            success=False, error=f"Unknown tool: {tool_name}",
        )
    result = handler(state, params)
    if inspect.isawaitable(result):
        result = await result
    return result
