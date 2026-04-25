# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the skills layer wiring (registry + ToolResult routing)."""

import asyncio

from bowerbot.config import Settings, SkillConfig
from bowerbot.skills.base import Skill, SkillCategory, Tool, ToolResult
from bowerbot.skills.registry import SkillRegistry


class _StubSkill(Skill):
    """Minimal Skill implementation used to exercise the registry."""

    name = "stub"
    category = SkillCategory.ASSET_PROVIDER

    def get_tools(self) -> list[Tool]:
        return [Tool(name="ping", description="Returns pong.", parameters={})]

    async def execute(self, tool_name: str, params: dict) -> ToolResult:
        if tool_name == "ping":
            return ToolResult(success=True, data="pong")
        return ToolResult(success=False, error=f"Unknown tool: {tool_name}")

    def validate_config(self) -> bool:
        return True


def test_registry_routes_tool_to_qualified_skill():
    """SkillRegistry namespaces tools as ``<skill>__<tool>`` and routes correctly."""
    registry = SkillRegistry()
    registry.register(_StubSkill())

    tools = registry.get_all_tools()
    assert any(t["function"]["name"] == "stub__ping" for t in tools)

    result = asyncio.run(registry.execute_tool("stub__ping", {}))
    assert result.success
    assert result.data == "pong"


def test_registry_rejects_unknown_skill():
    """Calls to unknown qualified names return a clear error."""
    registry = SkillRegistry()
    result = asyncio.run(registry.execute_tool("ghost__ping", {}))
    assert not result.success
    assert "Skill not found" in result.error


def test_registry_loads_no_skills_when_disabled():
    """A registry with all skills disabled exposes no tools."""
    settings = Settings(
        skills={"sketchfab": SkillConfig(enabled=False)},
    )
    registry = SkillRegistry()
    registry.load_from_settings(settings)
    assert registry.skill_count == 0
    assert registry.get_all_tools() == []
