# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Vague-intent tier: prompts without enough specificity to act on directly.

Goal of these scenarios is mostly UX-quality (does the agent ask
clarifying questions or pick reasonable defaults rather than hallucinate
state). State assertions are minimal; the artifact transcripts are the
primary value. Run with --capture=tee-sys to read the agent's responses
inline.
"""

from __future__ import annotations

from tests.agent.runner import AgentScenario, ScenarioContext
from tests.agent.scenarios._fixtures import (
    setup_scene_with_ground_and_box,
    setup_scene_with_one_cube,
)


def _assert_inspection_before_authoring(ctx: ScenarioContext) -> None:
    """If anything was authored, at least one inspection tool ran first."""
    authoring = {
        "place_asset", "create_light", "create_material",
        "apply_physics_api", "create_joint", "setup_physics_scene",
        "create_or_update_collision_group", "set_prim_attribute",
        "create_or_update_material_variant",
    }
    inspection = {
        "list_scene", "list_prim_children", "list_prim_attributes",
        "get_physics_summary", "list_joints", "list_collision_groups",
    }
    call_order = [tc.tool_name for tc in ctx.all_tool_calls]
    if not any(name in authoring for name in call_order):
        return
    first_auth = next(i for i, n in enumerate(call_order) if n in authoring)
    earlier = set(call_order[:first_auth])
    assert earlier & inspection, (
        "Agent authored without inspecting first. Calls (in order): "
        f"{call_order}"
    )


vague_add_lighting = AgentScenario(
    name="vague_add_lighting",
    description="'Add some lighting'; tests whether the agent inspects first.",
    tier="vague",
    setup=setup_scene_with_ground_and_box,
    prompts=["add some lighting to this scene"],
    assertions=[_assert_inspection_before_authoring],
)


vague_make_it_realistic = AgentScenario(
    name="vague_make_it_realistic",
    description="'Make it look realistic' is intentionally underspecified.",
    tier="vague",
    setup=setup_scene_with_one_cube,
    prompts=[
        "I have a cube and I want my scene to look more realistic. What "
        "would you suggest? Should I add materials, lights, physics?",
    ],
    assertions=[],
)


vague_set_up_physics = AgentScenario(
    name="vague_set_up_physics",
    description="'Set up the physics' on a populated scene.",
    tier="vague",
    suites=("smoke", "full"),
    setup=setup_scene_with_ground_and_box,
    prompts=[
        "Set up the physics in this scene. I don't know exactly what I "
        "need yet, but I want to be able to simulate things.",
    ],
    assertions=[_assert_inspection_before_authoring],
)


ALL = [
    vague_add_lighting,
    vague_make_it_realistic,
    vague_set_up_physics,
]
