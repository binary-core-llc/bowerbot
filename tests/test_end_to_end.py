# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""End-to-end test: prompt -> LLM -> search -> assemble -> validate -> .usdz"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="  %(name)s: %(message)s")


async def test_full_scene_build():
    """Natural language prompt produces a .usdz file."""
    from pxr import Usd, UsdGeom

    from bowerbot.agent import AgentRuntime
    from bowerbot.config import LLMSettings, SceneDefaults, Settings, SkillConfig
    from bowerbot.project import Project
    from bowerbot.scene_builder import SceneBuilder
    from bowerbot.skills.registry import SkillRegistry

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()

    for name in ["display_table", "wooden_chair", "pendant_light", "shelf_unit"]:
        path = asset_dir / f"{name}.usda"
        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        root = stage.DefinePrim(f"/{name}", "Xform")
        stage.SetDefaultPrim(root)
        cube = UsdGeom.Cube.Define(stage, f"/{name}/Mesh")
        cube.GetSizeAttr().Set(1.0)
        stage.Save()

    print(f"  Created 4 test assets in {asset_dir}")

    settings = Settings(
        llm=LLMSettings(
            model="gpt-4o",
            temperature=0.1,
            max_tokens=4096,
        ),
        scene_defaults=SceneDefaults(
            meters_per_unit=1.0,
            up_axis="Y",
            default_room_bounds=(10.0, 3.0, 8.0),
        ),
        assets_dir=str(asset_dir),
        projects_dir=str(tmp_path / "projects"),
        skills={
            "local": SkillConfig(enabled=True),
        },
    )

    project = Project.create(Path(settings.projects_dir), "e2e_test")

    builder = SceneBuilder(scene_defaults=settings.scene_defaults)
    builder.set_project(project)
    registry = SkillRegistry()
    registry.load_from_settings(settings)

    print(f"  Skills: {registry.enabled_skills}")

    agent = AgentRuntime(
        settings=settings,
        scene_builder=builder,
        skill_registry=registry,
    )

    prompt = (
        "Build a small retail store scene. "
        "Search my local assets for a table and a chair. "
        "Create a USD stage called 'retail_store'. "
        "Place 2 tables in a row with 3 meters spacing, centered in the room, on the floor. "
        "Place 1 chair next to each table. "
        "Then validate the scene and package it as .usdz."
    )

    print(f"\n  Prompt: {prompt}\n")
    response = await agent.process(prompt)

    print(f"\n  === AGENT RESPONSE ===")
    for line in response.split("\n"):
        print(f"  {line}")
    print(f"  ======================\n")

    usdz_files = list(project.path.rglob("*.usdz"))
    assert len(usdz_files) > 0, f"No .usdz files found in {project.path}"

    usdz_path = usdz_files[0]
    assert usdz_path.stat().st_size > 0, "USDZ file is empty"
    print(f"  USDZ created: {usdz_path.name} ({usdz_path.stat().st_size} bytes)")

    assert project.scene_path.exists(), "Scene file not created"
    stage = Usd.Stage.Open(str(project.scene_path))
    default_prim = stage.GetDefaultPrim()
    assert default_prim.IsValid(), "No defaultPrim"
    print(f"  defaultPrim: {default_prim.GetPath()}")

    tool_calls = [m for m in agent.conversation_history if m.get("role") == "tool"]
    assert len(tool_calls) > 0, "Agent never called any tools"
    print(f"  Tool results received: {len(tool_calls)}")

    print("\nEND-TO-END TEST PASSED!")


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("Skipping — no OPENAI_API_KEY")
    else:
        asyncio.run(test_full_scene_build())
