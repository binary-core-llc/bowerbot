# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the agent loop with Anthropic."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


async def test_agent_anthropic():
    from pxr import Usd
    from pxr import UsdGeom

    from bowerbot import agent
    from bowerbot import config
    from bowerbot import scene_state
    from bowerbot import skills

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

    settings = config.Settings(
        llm=config.LLMSettings(
            model="anthropic/claude-sonnet-4-6",
            temperature=0.1,
            max_tokens=1024,
        ),
        skills={
            "local": config.SkillConfig(enabled=True, config={"paths": [str(asset_dir)]}),
        },
    )

    state = scene_state.SceneState()
    registry = skills.SkillRegistry()
    registry.load_from_settings(settings)
    runtime = agent.AgentRuntime(
        settings=settings,
        state=state,
        skill_registry=registry,
    )

    response = await runtime.process("Find me a table in my local assets.")

    assert "table" in response.lower(), f"Response doesn't mention table: {response}"

    print(f"  Response: {response[:200]}...")
    print("✅ test_agent_anthropic PASSED")


if __name__ == "__main__":
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⏭️  Skipping — no ANTHROPIC_API_KEY")
    else:
        asyncio.run(test_agent_anthropic())
        print("\n🎉 Anthropic agent test passed!")
