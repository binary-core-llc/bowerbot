# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Live test: search Sketchfab for the mug, download it, build a scene."""

import asyncio
import logging

import pytest

pytestmark = pytest.mark.integration

logging.basicConfig(level=logging.INFO, format="  %(name)s: %(message)s")


async def test_sketchfab_mug():
    from bowerbot.agent import AgentRuntime
    from bowerbot.config import load_settings
    from bowerbot.skills.registry import SkillRegistry
    from bowerbot.state import SceneState

    settings = load_settings()

    state = SceneState.from_settings(settings)
    registry = SkillRegistry()
    registry.load_from_settings(settings)

    print(f"  Skills: {registry.enabled_skills}")
    print(f"  Tools: {[t['function']['name'] for t in registry.get_all_tools()]}")

    agent = AgentRuntime(settings=settings, state=state, skill_registry=registry)

    prompt = (
        "Search my Sketchfab account for a mug. "
        "Download it, create a USD stage called 'mug_scene', "
        "place the mug on a table surface at Y=0.75 centered in the room, "
        "then validate and package as .usdz."
    )

    print(f"\n  Prompt: {prompt}\n")
    response = await agent.process(prompt)

    print("\n  === AGENT RESPONSE ===")
    for line in response.split("\n"):
        print(f"  {line}")
    print("  ======================")


if __name__ == "__main__":
    asyncio.run(test_sketchfab_mug())
