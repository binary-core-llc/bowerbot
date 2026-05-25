# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Goal-oriented physics scenarios: 'make it fall', 'set up a pendulum', etc."""

from __future__ import annotations

from pxr import UsdPhysics

from tests.agent.runner import AgentScenario, ScenarioContext
from tests.agent.scenarios._fixtures import (
    get_prim_paths_with_api,
    get_typed_prim_paths,
    setup_scene_with_ground_and_box,
    setup_two_cubes_in_scene,
)


def _assert_physics_scene_present(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None, "Scene stage not open"
    scenes = get_typed_prim_paths(stage, "PhysicsScene")
    assert scenes, (
        f"Expected a UsdPhysics.Scene; none found. Tool calls: "
        f"{[tc.tool_name for tc in ctx.all_tool_calls]}"
    )


def _assert_rigid_body_authored(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None, "Scene stage not open"
    paths = get_prim_paths_with_api(stage, "PhysicsRigidBodyAPI")
    assert paths, (
        f"Expected at least one PhysicsRigidBodyAPI to be applied. "
        f"Tool calls: {[tc.tool_name for tc in ctx.all_tool_calls]}"
    )


def _assert_collision_authored(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    paths = get_prim_paths_with_api(stage, "PhysicsCollisionAPI")
    assert paths, (
        f"Expected at least one PhysicsCollisionAPI to be applied. "
        f"Tool calls: {[tc.tool_name for tc in ctx.all_tool_calls]}"
    )


def _assert_revolute_joint_present(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    joints = get_typed_prim_paths(stage, "PhysicsRevoluteJoint")
    assert joints, (
        f"Expected a PhysicsRevoluteJoint; none found. Tool calls: "
        f"{[tc.tool_name for tc in ctx.all_tool_calls]}"
    )


def _assert_uses_convex_approximation(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    bad: list[str] = []
    for prim in stage.Traverse():
        if "PhysicsMeshCollisionAPI" not in prim.GetAppliedSchemas():
            continue
        if not prim.IsA(UsdPhysics.MeshCollisionAPI):
            continue
        approx_attr = prim.GetAttribute("physics:approximation")
        if not approx_attr:
            continue
        approx = approx_attr.Get()
        if approx == "none":
            ancestor = prim
            while ancestor and str(ancestor.GetPath()) != "/":
                if "PhysicsRigidBodyAPI" in ancestor.GetAppliedSchemas():
                    bad.append(str(prim.GetPath()))
                    break
                ancestor = ancestor.GetParent()
    assert not bad, (
        f"Dynamic body meshes must use a convex approximation, not 'none'. "
        f"Offenders: {bad}"
    )


goal_falling_box = AgentScenario(
    name="goal_falling_box",
    description="Vague goal: make a box fall and land on the ground.",
    tier="goal",
    setup=setup_scene_with_ground_and_box,
    prompts=[
        "I want the box to fall down and land on the ground when I press "
        "play in Omniverse. Set everything up so that works.",
    ],
    assertions=[
        _assert_physics_scene_present,
        _assert_rigid_body_authored,
        _assert_collision_authored,
        _assert_uses_convex_approximation,
    ],
)


goal_pendulum_from_scratch = AgentScenario(
    name="goal_pendulum_from_scratch",
    description="Two cubes -> pendulum: hinge joint + dynamic bob + kinematic anchor.",
    tier="goal",
    setup=setup_two_cubes_in_scene,
    prompts=[
        "I have two cubes in my scene called Cube_Anchor and Cube_Bob. "
        "I want them to act like a pendulum: the anchor stays still and "
        "the bob swings beneath it. Set this up for me.",
    ],
    assertions=[
        _assert_physics_scene_present,
        _assert_rigid_body_authored,
        _assert_revolute_joint_present,
    ],
)


goal_render_ready_no_physics = AgentScenario(
    name="goal_render_ready_no_physics",
    description="User wants a static render-ready scene; physics should NOT be authored.",
    tier="goal",
    setup=setup_scene_with_ground_and_box,
    prompts=[
        "I'm putting together a still render with this box on the ground. "
        "Add some lighting so it looks nice. No physics needed, this is "
        "just for a frame.",
    ],
    assertions=[],  # state assertions deferred; transcript artifact reveals quality
)


ALL = [
    goal_falling_box,
    goal_pendulum_from_scratch,
    goal_render_ready_no_physics,
]
