# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Live test: search Sketchfab for the mug, download it, build a scene."""

import asyncio
import logging

import pytest

pytestmark = pytest.mark.integration

logging.basicConfig(level=logging.INFO, format="  %(name)s: %(message)s")


async def test_sketchfab_mug():
    from bowerbot import agent
    from bowerbot import config
    from bowerbot import scene_state
    from bowerbot import skills

    settings = config.load_settings()

    state = scene_state.SceneState.from_settings(settings)
    registry = skills.SkillRegistry()
    registry.load_from_settings(settings)

    print(f"  Skills: {registry.enabled_skills}")
    print(f"  Tools: {[t['function']['name'] for t in registry.get_all_tools()]}")

    runtime = agent.AgentRuntime(settings=settings, state=state, skill_registry=registry)

    prompt = (
        "Search my Sketchfab account for a mug. "
        "Download it, create a USD stage called 'mug_scene', "
        "place the mug on a table surface at Y=0.75 centered in the room, "
        "then validate and package as .usdz."
    )

    print(f"\n  Prompt: {prompt}\n")
    response = await runtime.process(prompt)

    print("\n  === AGENT RESPONSE ===")
    for line in response.split("\n"):
        print(f"  {line}")
    print("  ======================")


if __name__ == "__main__":
    asyncio.run(test_sketchfab_mug())
