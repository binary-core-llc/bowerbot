# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Iteration tier: multi-turn conversations that build on prior state."""

from __future__ import annotations

from tests.agent.runner import AgentScenario, ScenarioContext
from tests.agent.scenarios._fixtures import (
    get_prim_paths_with_api,
    get_typed_prim_paths,
    setup_scene_with_ground_and_box,
    setup_scene_with_three_rigid_bodies,
)


def _assert_mass_authored(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    paths = get_prim_paths_with_api(stage, "PhysicsMassAPI")
    assert paths, (
        f"Expected PhysicsMassAPI to be applied after mass iteration. "
        f"Tool calls: {[tc.tool_name for tc in ctx.all_tool_calls]}"
    )


def _assert_kinematic_set_somewhere(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    found = False
    for prim in stage.Traverse():
        if "PhysicsRigidBodyAPI" not in prim.GetAppliedSchemas():
            continue
        attr = prim.GetAttribute("physics:kinematicEnabled")
        if attr and attr.Get() is True:
            found = True
            break
    assert found, (
        "Expected at least one rigid body to have "
        "physics:kinematicEnabled=true after 'make it kinematic'."
    )


def _assert_multiple_bodies_have_collision(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    coll = get_prim_paths_with_api(stage, "PhysicsCollisionAPI")
    assert len(coll) >= 2, (
        f"Expected collision authored on 2+ prims after 'do the same '"
        f"for the other boxes'. Got: {coll}"
    )


def _assert_physics_scene_present(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    scenes = get_typed_prim_paths(stage, "PhysicsScene")
    assert scenes, "Expected a UsdPhysics.Scene to be present."


iteration_make_it_heavier = AgentScenario(
    name="iteration_make_it_heavier",
    description="Apply physics, then change mass on follow-up turn.",
    tier="iteration",
    setup=setup_scene_with_ground_and_box,
    prompts=[
        "Make the box a rigid body that falls under gravity.",
        "Now make it much heavier — like 50 kilograms.",
    ],
    assertions=[_assert_physics_scene_present, _assert_mass_authored],
)


iteration_change_to_kinematic = AgentScenario(
    name="iteration_change_to_kinematic",
    description="Toggle a dynamic body to kinematic on follow-up.",
    tier="iteration",
    setup=setup_scene_with_ground_and_box,
    prompts=[
        "Make the box a dynamic rigid body.",
        "Actually, switch it to kinematic — I want to animate it manually "
        "instead of letting the solver drive it.",
    ],
    assertions=[_assert_kinematic_set_somewhere],
)


iteration_do_same_for_others = AgentScenario(
    name="iteration_do_same_for_others",
    description="Generalise an applied operation across siblings.",
    tier="iteration",
    setup=setup_scene_with_three_rigid_bodies,
    prompts=[
        "Add convex-hull collision to Box_01.",
        "Now do the same for the other two boxes.",
    ],
    assertions=[_assert_multiple_bodies_have_collision],
)


ALL = [
    iteration_make_it_heavier,
    iteration_change_to_kinematic,
    iteration_do_same_for_others,
]
