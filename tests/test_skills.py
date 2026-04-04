# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the Skills layer: Local skill discovers and searches assets."""

import asyncio
import tempfile
from pathlib import Path

from bowerbot.skills.local import LocalSkill
from bowerbot.skills.registry import SkillRegistry
from bowerbot.config import Settings, SkillConfig


def create_test_assets(directory: Path) -> None:
    """Create a few dummy USD files to search through."""
    from pxr import Usd, UsdGeom, Kind

    for name in ["display_table", "wooden_chair", "pendant_light", "shelf_unit"]:
        path = directory / f"{name}.usda"
        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        root = stage.DefinePrim(f"/{name}", "Xform")
        stage.SetDefaultPrim(root)
        # Add a simple cube as placeholder geometry
        cube = UsdGeom.Cube.Define(stage, f"/{name}/Mesh")
        cube.GetSizeAttr().Set(1.0)
        stage.Save()


def test_local_skill_search():
    """Test 1: LocalSkill finds assets by keyword."""
    with tempfile.TemporaryDirectory() as tmp:
        asset_dir = Path(tmp)
        create_test_assets(asset_dir)

        skill = LocalSkill(paths=[str(asset_dir)])
        assert skill.validate_config() is True

        # Search for "table"
        result = asyncio.run(skill.execute("search_assets", {"query": "table"}))
        assert result.success, f"Search failed: {result.error}"
        assert len(result.data) == 1, f"Expected 1 result, got {len(result.data)}"
        assert result.data[0]["name"] == "display_table"

        # Search for "chair"
        result = asyncio.run(skill.execute("search_assets", {"query": "chair"}))
        assert result.success
        assert len(result.data) == 1
        assert result.data[0]["name"] == "wooden_chair"

        # Search for something that doesn't exist
        result = asyncio.run(skill.execute("search_assets", {"query": "sofa"}))
        assert result.success
        assert len(result.data) == 0

        print("✅ test_local_skill_search PASSED")


def test_local_skill_list_all():
    """Test 2: LocalSkill lists all available assets."""
    with tempfile.TemporaryDirectory() as tmp:
        asset_dir = Path(tmp)
        create_test_assets(asset_dir)

        skill = LocalSkill(paths=[str(asset_dir)])
        result = asyncio.run(skill.execute("list_assets", {}))

        assert result.success
        assert len(result.data) == 4, f"Expected 4 assets, got {len(result.data)}"

        names = sorted([a["name"] for a in result.data])
        assert names == ["display_table", "pendant_light", "shelf_unit", "wooden_chair"]

        print("✅ test_local_skill_list_all PASSED")
        print(f"   Found: {names}")


def test_skill_registry():
    """Test 3: SkillRegistry loads skills from settings and exposes tools."""
    with tempfile.TemporaryDirectory() as tmp:
        asset_dir = Path(tmp)
        create_test_assets(asset_dir)

        settings = Settings(
            skills={
                "local": SkillConfig(
                    enabled=True,
                    config={"paths": [str(asset_dir)]},
                ),
                "sketchfab": SkillConfig(
                    enabled=False,  # Disabled — no token
                    config={"token": ""},
                ),
            }
        )

        registry = SkillRegistry()
        registry.load_from_settings(settings)

        # Only local should be loaded (sketchfab disabled, assembly moved to SceneBuilder)
        assert registry.skill_count == 1, f"Expected 1 skill, got {registry.skill_count}"
        assert "local" in registry.enabled_skills

        # Check tools are exposed with skill prefix
        tools = registry.get_all_tools()
        tool_names = [t["function"]["name"] for t in tools]
        assert "local__search_assets" in tool_names
        assert "local__list_assets" in tool_names

        print("✅ test_skill_registry PASSED")
        print(f"   Enabled: {registry.enabled_skills}")
        print(f"   Tools: {tool_names}")


def test_registry_execute_tool():
    """Test 4: SkillRegistry routes tool calls to the right skill."""
    with tempfile.TemporaryDirectory() as tmp:
        asset_dir = Path(tmp)
        create_test_assets(asset_dir)

        settings = Settings(
            skills={
                "local": SkillConfig(
                    enabled=True,
                    config={"paths": [str(asset_dir)]},
                ),
            }
        )

        registry = SkillRegistry()
        registry.load_from_settings(settings)

        # Execute through registry using qualified name
        result = asyncio.run(
            registry.execute_tool("local__search_assets", {"query": "light"})
        )
        assert result.success
        assert len(result.data) == 1
        assert result.data[0]["name"] == "pendant_light"

        # Try a non-existent skill
        result = asyncio.run(
            registry.execute_tool("fake__search", {"query": "test"})
        )
        assert not result.success
        assert "Skill not found" in result.error

        print("✅ test_registry_execute_tool PASSED")


if __name__ == "__main__":
    test_local_skill_search()
    test_local_skill_list_all()
    test_skill_registry()
    test_registry_execute_tool()
    print("\n🎉 All skills tests passed!")
