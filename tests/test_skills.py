# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the skills layer wiring (registry + ToolResult routing + context)."""

import asyncio
import tempfile
from pathlib import Path

from bowerbot.config import Settings, SkillConfig
from bowerbot.skills import (
    Skill,
    SkillCategory,
    SkillConfigError,
    SkillContext,
    SkillRegistry,
    Tool,
    ToolResult,
)
from bowerbot.state import SceneState


class _StubSkill(Skill):
    """Minimal Skill implementation used to exercise the registry."""

    name = "stub"
    category = SkillCategory.ASSET_PROVIDER

    def get_tools(self) -> list[Tool]:
        return [Tool(name="ping", description="Returns pong.", parameters={})]

    async def execute(
        self, tool_name: str, params: dict, ctx: SkillContext,
    ) -> ToolResult:
        if tool_name == "ping":
            return ToolResult(success=True, data="pong")
        return ToolResult(success=False, error=f"Unknown tool: {tool_name}")

    def validate_config(self) -> None:
        return


class _ExternalSkill(Skill):
    """Stand-in for a third-party skill installed via entry points."""

    name = "external_provider"
    category = SkillCategory.ASSET_PROVIDER

    def get_tools(self) -> list[Tool]:
        return [Tool(name="ping", description="Returns pong.", parameters={})]

    async def execute(
        self, tool_name: str, params: dict, ctx: SkillContext,
    ) -> ToolResult:
        return ToolResult(success=True, data="pong")

    def validate_config(self) -> None:
        return


class _MisnamedExternalSkill(Skill):
    """Skill whose name attribute does not match its entry point name."""

    name = "actual_name"
    category = SkillCategory.ASSET_PROVIDER

    def get_tools(self) -> list[Tool]:
        return [Tool(name="ping", description="Returns pong.", parameters={})]

    async def execute(
        self, tool_name: str, params: dict, ctx: SkillContext,
    ) -> ToolResult:
        return ToolResult(success=True, data="pong")

    def validate_config(self) -> None:
        return


class _MisconfiguredSkill(Skill):
    """Skill whose validate_config always raises SkillConfigError."""

    name = "broken"
    category = SkillCategory.ASSET_PROVIDER

    def __init__(self, **_: object) -> None:
        return

    def get_tools(self) -> list[Tool]:
        return []

    async def execute(
        self, tool_name: str, params: dict, ctx: SkillContext,
    ) -> ToolResult:
        return ToolResult(success=True)

    def validate_config(self) -> None:
        raise SkillConfigError("missing token")


class _ContextEcho(Skill):
    """Skill that echoes the SkillContext it receives, for assertion."""

    name = "echo"
    category = SkillCategory.ASSET_PROVIDER
    cache_subdir = "cache/echo"

    def get_tools(self) -> list[Tool]:
        return [Tool(name="ctx", description="Echoes context.", parameters={})]

    async def execute(
        self, tool_name: str, params: dict, ctx: SkillContext,
    ) -> ToolResult:
        return ToolResult(
            success=True,
            data={
                "library_dir": str(ctx.library_dir),
                "cache_dir": str(ctx.cache_dir) if ctx.cache_dir else None,
                "project_dir": str(ctx.project_dir) if ctx.project_dir else None,
                "scene_path": str(ctx.scene_path) if ctx.scene_path else None,
            },
        )

    def validate_config(self) -> None:
        return


def test_registry_routes_tool_to_qualified_skill():
    """SkillRegistry namespaces tools as ``<skill>__<tool>`` and routes correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        registry = SkillRegistry()
        registry._library_dir = Path(tmp)
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
    settings = Settings(skills={"sketchfab": SkillConfig(enabled=False)})
    registry = SkillRegistry()
    registry.load_from_settings(settings)
    assert registry.skill_count == 0
    assert registry.get_all_tools() == []


def test_skill_context_carries_library_and_cache_dirs():
    """SkillContext exposes library_dir and the skill's cache_dir."""
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        registry = SkillRegistry()
        registry._library_dir = library
        registry.register(_ContextEcho())

        result = asyncio.run(registry.execute_tool("echo__ctx", {}))
        assert result.success
        assert result.data["library_dir"] == str(library)
        assert result.data["cache_dir"] == str(library / "cache" / "echo")
        assert (library / "cache" / "echo").exists()
        assert result.data["project_dir"] is None
        assert result.data["scene_path"] is None


def test_skill_context_carries_project_and_scene_when_state_provided():
    """SkillContext picks up project_dir and scene_path from SceneState."""
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp) / "library"
        library.mkdir()
        project_dir = Path(tmp) / "project"
        project_dir.mkdir()
        scene_path = project_dir / "scene.usda"
        scene_path.write_text("#usda 1.0\n")

        class _FakeProject:
            path = project_dir
            assets_dir = project_dir / "assets"

        state = SceneState(library_dir=library)
        state.project = _FakeProject()
        state.stage_path = scene_path

        registry = SkillRegistry()
        registry._library_dir = library
        registry.register(_ContextEcho())

        result = asyncio.run(registry.execute_tool("echo__ctx", {}, state))
        assert result.success
        assert result.data["project_dir"] == str(project_dir)
        assert result.data["scene_path"] == str(scene_path)


def test_registry_discovers_external_skill_via_entry_points(monkeypatch):
    """A skill installed as a separate pip package is discovered by entry points.

    Simulates the third-party install path by injecting a fake entry
    point into ``importlib.metadata.entry_points``. Proves the registry
    finds the skill, instantiates it with config, and routes a tool
    through it without any in-tree code.
    """
    from importlib.metadata import EntryPoint

    from bowerbot.skills import registry as registry_mod

    fake_ep = EntryPoint(
        name="external_provider",
        value="tests.test_skills:_ExternalSkill",
        group="bowerbot.skills",
    )

    def _fake_entry_points(*, group: str) -> tuple[EntryPoint, ...]:
        if group == "bowerbot.skills":
            return (fake_ep,)
        return ()

    monkeypatch.setattr(registry_mod, "entry_points", _fake_entry_points)

    settings = Settings(skills={"external_provider": SkillConfig(enabled=True)})
    registry = SkillRegistry()
    registry.load_from_settings(settings)

    assert registry.skill_count == 1
    assert "external_provider__ping" in {
        t["function"]["name"] for t in registry.get_all_tools()
    }

    result = asyncio.run(registry.execute_tool("external_provider__ping", {}))
    assert result.success
    assert result.data == "pong"


def test_registry_skips_skill_when_entry_point_name_mismatches(monkeypatch, caplog):
    """A skill whose ``name`` differs from its entry-point name is skipped."""
    import logging
    from importlib.metadata import EntryPoint

    from bowerbot.skills import registry as registry_mod

    fake_ep = EntryPoint(
        name="declared_name",
        value="tests.test_skills:_MisnamedExternalSkill",
        group="bowerbot.skills",
    )
    monkeypatch.setattr(
        registry_mod, "entry_points",
        lambda *, group: (fake_ep,) if group == "bowerbot.skills" else (),
    )

    settings = Settings(skills={"declared_name": SkillConfig(enabled=True)})
    registry = SkillRegistry()
    with caplog.at_level(logging.ERROR, logger="bowerbot.skills.registry"):
        registry.load_from_settings(settings)

    assert registry.skill_count == 0
    assert any(
        "name mismatch" in r.message.lower() for r in caplog.records
    )


def test_registry_skips_skill_when_validate_config_raises(monkeypatch, caplog):
    """A skill whose ``validate_config`` raises is skipped with a clear log."""
    import logging
    from importlib.metadata import EntryPoint

    from bowerbot.skills import registry as registry_mod

    fake_ep = EntryPoint(
        name="broken",
        value="tests.test_skills:_MisconfiguredSkill",
        group="bowerbot.skills",
    )
    monkeypatch.setattr(
        registry_mod, "entry_points",
        lambda *, group: (fake_ep,) if group == "bowerbot.skills" else (),
    )

    settings = Settings(skills={"broken": SkillConfig(enabled=True)})
    registry = SkillRegistry()
    with caplog.at_level(logging.WARNING, logger="bowerbot.skills.registry"):
        registry.load_from_settings(settings)

    assert registry.skill_count == 0
    assert any("missing token" in r.message for r in caplog.records)
