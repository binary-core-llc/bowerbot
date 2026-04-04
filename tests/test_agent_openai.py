# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the full agent loop: user prompt → LLM → tool calls → response."""

import asyncio
import os
import logging

# Show what the agent is doing
logging.basicConfig(level=logging.INFO, format="  %(name)s: %(message)s")


async def test_agent_with_local_assets():
    """Full integration: agent searches local assets via tool-calling loop."""
    import tempfile
    from pathlib import Path

    from pxr import Usd, UsdGeom

    from bowerbot.agent import AgentRuntime
    from bowerbot.config import Settings, LLMSettings, SkillConfig
    from bowerbot.scene_builder import SceneBuilder
    from bowerbot.skills.registry import SkillRegistry

    # 1. Create test assets on disk
    tmp = tempfile.mkdtemp()
    asset_dir = Path(tmp)

    for name in ["display_table", "wooden_chair", "pendant_light", "shelf_unit", "counter"]:
        path = asset_dir / f"{name}.usda"
        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        root = stage.DefinePrim(f"/{name}", "Xform")
        stage.SetDefaultPrim(root)
        cube = UsdGeom.Cube.Define(stage, f"/{name}/Mesh")
        cube.GetSizeAttr().Set(1.0)
        stage.Save()

    print(f"  Created 5 test assets in {asset_dir}")

    # 2. Configure agent
    settings = Settings(
        llm=LLMSettings(
            model="gpt-4o",
            temperature=0.1,
            max_tokens=1024,
        ),
        skills={
            "local": SkillConfig(
                enabled=True,
                config={"paths": [str(asset_dir)]},
            ),
        },
    )

    builder = SceneBuilder(scene_defaults=settings.scene_defaults)
    registry = SkillRegistry()
    registry.load_from_settings(settings)

    agent = AgentRuntime(
        settings=settings,
        scene_builder=builder,
        skill_registry=registry,
    )

    print(f"  Skills loaded: {registry.enabled_skills}")
    print(f"  Tools available: {[t['function']['name'] for t in registry.get_all_tools()]}")

    # 3. Run the agent
    print("\n  Sending prompt to agent...")
    response = await agent.process(
        "Search for a table and a chair in my local assets."
    )

    print(f"\n  Agent response:\n  ---")
    for line in response.split("\n"):
        print(f"  {line}")
    print(f"  ---")

    # 4. Verify the agent actually used tools and found assets
    # Check conversation history for tool calls
    tool_calls_made = [
        msg for msg in agent.conversation_history
        if msg.get("role") == "tool"
    ]
    assert len(tool_calls_made) > 0, "Agent never called any tools!"

    # Check that response mentions our assets
    response_lower = response.lower()
    assert "table" in response_lower, "Response doesn't mention table"
    assert "chair" in response_lower, "Response doesn't mention chair"

    print(f"\n  Tool calls made: {len(tool_calls_made)}")
    print("✅ test_agent_with_local_assets PASSED")


async def main():
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("⏭️  Skipping — no OPENAI_API_KEY in .env")
        return

    await test_agent_with_local_assets()
    print("\n🎉 Agent integration test passed!")


if __name__ == "__main__":
    asyncio.run(main())
