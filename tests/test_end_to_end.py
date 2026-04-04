# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""End-to-end test: prompt → LLM → search → assemble → validate → .usdz"""

import asyncio
import os
import tempfile
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="  %(name)s: %(message)s")


async def test_full_scene_build():
    """The big one: natural language prompt produces a .usdz file."""
    from pxr import Usd, UsdGeom

    from bowerbot.agent import AgentRuntime
    from bowerbot.config import Settings, LLMSettings, SkillConfig, SceneDefaults
    from bowerbot.scene_builder import SceneBuilder
    from bowerbot.skills.registry import SkillRegistry

    # 1. Set up temp workspace
    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # 2. Create test assets the LLM can find
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

    # 3. Configure everything
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
        skills={
            "local": SkillConfig(
                enabled=True,
                config={"paths": [str(asset_dir)]},
            ),
        },
        output_dir=output_dir,
    )

    builder = SceneBuilder(scene_defaults=settings.scene_defaults)
    registry = SkillRegistry()
    registry.load_from_settings(settings)

    print(f"  Skills: {registry.enabled_skills}")
    print(f"  Tools: {[t['function']['name'] for t in registry.get_all_tools()]}")

    agent = AgentRuntime(
        settings=settings,
        scene_builder=builder,
        skill_registry=registry,
    )

    # 4. Send the prompt
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

    # 5. Verify results
    # Check that a .usdz was created
    usdz_files = list(output_dir.rglob("*.usdz"))
    assert len(usdz_files) > 0, f"No .usdz files found in {output_dir}"

    usdz_path = usdz_files[0]
    assert usdz_path.stat().st_size > 0, "USDZ file is empty"
    print(f"  ✅ USDZ created: {usdz_path.name} ({usdz_path.stat().st_size} bytes)")

    # Check the .usda source too
    usda_files = list(output_dir.rglob("*.usda"))
    if usda_files:
        stage = Usd.Stage.Open(str(usda_files[0]))
        prim_count = len(list(stage.Traverse()))
        print(f"  ✅ Stage has {prim_count} prims")

        # Verify structure
        default_prim = stage.GetDefaultPrim()
        assert default_prim.IsValid(), "No defaultPrim"
        print(f"  ✅ defaultPrim: {default_prim.GetPath()}")

    # Check tool usage in conversation history
    tool_calls = [m for m in agent.conversation_history if m.get("role") == "tool"]
    tool_names_called = set()
    for m in agent.conversation_history:
        if isinstance(m, dict) and m.get("role") == "assistant":
            continue
        # Look for tool_calls in assistant messages (stored as dicts)
        if hasattr(m, "get") and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                if isinstance(tc, dict):
                    tool_names_called.add(tc["function"]["name"])
                else:
                    tool_names_called.add(tc.function.name)

    print(f"  ✅ Tool results received: {len(tool_calls)}")
    print(f"  ✅ Tools called: {tool_names_called}")

    print("\n🎉 END-TO-END TEST PASSED!")


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("⏭️  Skipping — no OPENAI_API_KEY in .env")
    else:
        asyncio.run(test_full_scene_build())
