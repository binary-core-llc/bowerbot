# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the agent loop with Anthropic."""

import asyncio
import os
import tempfile
from pathlib import Path


async def test_agent_anthropic():
    from pxr import Usd, UsdGeom
    from bowerbot.agent import AgentRuntime
    from bowerbot.config import Settings, LLMSettings, SkillConfig
    from bowerbot.scene_builder import SceneBuilder
    from bowerbot.skills.registry import SkillRegistry

    # Create test assets
    tmp = tempfile.mkdtemp()
    asset_dir = Path(tmp)
    for name in ["display_table", "wooden_chair"]:
        path = asset_dir / f"{name}.usda"
        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        root = stage.DefinePrim(f"/{name}", "Xform")
        stage.SetDefaultPrim(root)
        stage.Save()

    settings = Settings(
        llm=LLMSettings(
            model="anthropic/claude-sonnet-4-20250514",
            temperature=0.1,
            max_tokens=1024,
        ),
        skills={
            "local": SkillConfig(enabled=True, config={"paths": [str(asset_dir)]}),
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

    response = await agent.process("Find me a table in my local assets.")

    assert "table" in response.lower(), f"Response doesn't mention table: {response}"

    print(f"  Response: {response[:200]}...")
    print("✅ test_agent_anthropic PASSED")


if __name__ == "__main__":
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⏭️  Skipping — no ANTHROPIC_API_KEY")
    else:
        asyncio.run(test_agent_anthropic())
        print("\n🎉 Anthropic agent test passed!")
