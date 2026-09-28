# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Unified tool routing across core tools and extension skills.

Both runtimes (the agent loop and the MCP server) present one combined
tool list to their client and route each call here. Core tools go to the
dispatcher; skill tools (``skill__tool``) go to the skill registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bowerbot import dispatcher
from bowerbot import scene_state
from bowerbot import skills

if TYPE_CHECKING:
    from bowerbot import skills


def combined_tool_schemas(skill_registry: skills.SkillRegistry) -> list[dict[str, Any]]:
    """Every tool the client can call: core tools plus enabled skills."""
    return dispatcher.get_tool_schemas() + skill_registry.get_all_tools()


async def route(
    state: scene_state.SceneState,
    skill_registry: skills.SkillRegistry,
    tool_name: str,
    params: dict[str, Any],
) -> skills.ToolResult:
    """Route a tool call to the core dispatcher or a skill."""
    if tool_name in dispatcher.get_tool_names():
        return await dispatcher.execute(state, tool_name, params)
    return await skill_registry.execute_tool(tool_name, params, state)
