# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Discovery tier: prompts that should drive inspection tools, not authoring."""

from __future__ import annotations

from tests.agent.runner import AgentScenario, ScenarioContext
from tests.agent.scenarios._fixtures import (
    setup_scene_with_three_rigid_bodies,
    setup_two_cubes_in_scene,
)


def _called_any(ctx: ScenarioContext, *tool_names: str) -> bool:
    """Convenience: did the agent call at least one of these inspection tools?"""
    called = {tc.tool_name for tc in ctx.all_tool_calls}
    return any(name in called for name in tool_names)


def _assert_used_inspection_tool(ctx: ScenarioContext) -> None:
    assert _called_any(
        ctx,
        "list_scene", "list_prim_children", "list_prim_attributes",
        "get_physics_summary", "list_joints", "list_collision_groups",
    ), f"Expected at least one inspection tool. Got: {[tc.tool_name for tc in ctx.all_tool_calls]}"


def _assert_no_authoring_tools(ctx: ScenarioContext) -> None:
    forbidden = {
        "place_asset", "create_light", "create_material",
        "apply_physics_api", "create_joint", "setup_physics_scene",
        "set_prim_attribute",
    }
    called = {tc.tool_name for tc in ctx.all_tool_calls}
    overlap = forbidden & called
    assert not overlap, (
        f"Discovery scenarios must not author. Authoring tools called: "
        f"{overlap}"
    )


discovery_what_is_in_scene = AgentScenario(
    name="discovery_what_is_in_scene",
    description="Ask 'what's in my scene' on a populated scene; expect inspection only.",
    tier="discovery",
    setup=setup_two_cubes_in_scene,
    prompts=["what's in my scene?"],
    assertions=[_assert_used_inspection_tool, _assert_no_authoring_tools],
)


discovery_what_physics_setup = AgentScenario(
    name="discovery_what_physics_setup",
    description="Ask about existing physics on a scene with rigid bodies authored.",
    tier="discovery",
    setup=setup_scene_with_three_rigid_bodies,
    prompts=["is there any physics set up here? what's already on the boxes?"],
    assertions=[_assert_used_inspection_tool, _assert_no_authoring_tools],
)


discovery_show_me_assets = AgentScenario(
    name="discovery_show_me_assets",
    description="Ask the agent to enumerate the library; should browse not author.",
    tier="discovery",
    prompts=["what assets do I have available to me?"],
    assertions=[_assert_no_authoring_tools],
)


ALL = [
    discovery_what_is_in_scene,
    discovery_what_physics_setup,
    discovery_show_me_assets,
]
