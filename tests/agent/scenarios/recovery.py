# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Recovery tier: user changes their mind or asks to undo a recent change."""

from __future__ import annotations

from tests.agent.runner import AgentScenario, ScenarioContext
from tests.agent.scenarios._fixtures import (
    get_prim_paths_with_api,
    setup_scene_with_ground_and_box,
    setup_scene_with_one_cube,
)


def _assert_no_rigid_body_remaining(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    paths = get_prim_paths_with_api(stage, "PhysicsRigidBodyAPI")
    assert not paths, (
        f"After 'remove the rigid body' the scene should have no "
        f"PhysicsRigidBodyAPI. Found: {paths}"
    )


recovery_remove_rigid_body = AgentScenario(
    name="recovery_remove_rigid_body",
    description="Apply a rigid body, then ask the agent to take it off.",
    tier="recovery",
    setup=setup_scene_with_one_cube,
    prompts=[
        "Make /Scene/Block a rigid body with collision so it falls.",
        "Actually never mind, take the rigid body off — I just want it "
        "as a static collider.",
    ],
    assertions=[_assert_no_rigid_body_remaining],
)


recovery_change_target = AgentScenario(
    name="recovery_change_target",
    description="Author on the wrong prim, then correct course.",
    tier="recovery",
    setup=setup_scene_with_ground_and_box,
    prompts=[
        "Make the ground a rigid body.",
        "Wait, that's wrong. The ground should be static; it's the box "
        "that should be a rigid body. Can you fix that?",
    ],
    assertions=[],
)


ALL = [
    recovery_remove_rigid_body,
    recovery_change_target,
]
