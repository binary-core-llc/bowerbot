# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""End-to-end test: prompt -> LLM -> search -> assemble -> validate -> .usdz"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

logging.basicConfig(level=logging.INFO, format="  %(name)s: %(message)s")


async def test_full_scene_build():
    """Natural language prompt produces a .usdz file."""
    from pxr import Usd
    from pxr import UsdGeom

    from bowerbot import agent
    from bowerbot import config
    from bowerbot import project_folder
    from bowerbot import scene_state
    from bowerbot import skills
    from bowerbot.utils import authoring

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

    settings = config.Settings(
        llm=config.LLMSettings(
            model="gpt-4o",
            temperature=0.1,
            max_tokens=4096,
        ),
        assets_dir=str(asset_dir),
        projects_dir=str(tmp_path / "projects"),
        skills={
            "local": config.SkillConfig(enabled=True),
        },
    )

    project = project_folder.Project.create(Path(settings.projects_dir), "e2e_test")

    state = scene_state.SceneState()
    state.project = project
    state.stage_path = project.scene_path
    if project.scene_path.exists():
        state.stage = authoring.stage.open_stage(project.scene_path)

    registry = skills.SkillRegistry()
    registry.load_from_settings(settings)

    print(f"  Skills: {registry.enabled_skills}")

    runtime = agent.AgentRuntime(
        settings=settings,
        state=state,
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
    response = await runtime.process(prompt)

    print("\n  === AGENT RESPONSE ===")
    for line in response.split("\n"):
        print(f"  {line}")
    print("  ======================\n")

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

    tool_calls = [m for m in runtime.conversation_history if m.get("role") == "tool"]
    assert len(tool_calls) > 0, "Agent never called any tools"
    print(f"  Tool results received: {len(tool_calls)}")

    print("\nEND-TO-END TEST PASSED!")


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("Skipping — no OPENAI_API_KEY")
    else:
        asyncio.run(test_full_scene_build())
