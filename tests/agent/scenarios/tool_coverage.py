# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-coverage tier: scenarios that exercise tool families not hit elsewhere.

Each scenario here is responsible for at least one tool category we
have not already exercised via the discovery / vague / goal / iteration
suites: materials, variants, validation, snapshots, scene-level
collision groups, joints + articulation root, light linking.
"""

from __future__ import annotations

from tests.agent.runner import AgentScenario, ScenarioContext
from tests.agent.scenarios._fixtures import (
    get_typed_prim_paths,
    setup_scene_with_ground_and_box,
    setup_scene_with_three_rigid_bodies,
)


def _called(ctx: ScenarioContext, tool_name: str) -> bool:
    return any(tc.tool_name == tool_name for tc in ctx.all_tool_calls)


def _assert_validate_scene_invoked(ctx: ScenarioContext) -> None:
    assert _called(ctx, "validate_scene"), (
        f"Expected validate_scene to be called. Tool calls: "
        f"{[tc.tool_name for tc in ctx.all_tool_calls]}"
    )


def _assert_snapshot_invoked(ctx: ScenarioContext) -> None:
    assert _called(ctx, "save_scene_snapshot"), (
        f"Expected save_scene_snapshot to be called. Tool calls: "
        f"{[tc.tool_name for tc in ctx.all_tool_calls]}"
    )


def _assert_collision_group_created(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    groups = get_typed_prim_paths(stage, "PhysicsCollisionGroup")
    assert groups, (
        f"Expected at least one PhysicsCollisionGroup. Tool calls: "
        f"{[tc.tool_name for tc in ctx.all_tool_calls]}"
    )


def _assert_articulation_root_applied(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    found = any(
        "PhysicsArticulationRootAPI" in p.GetAppliedSchemas()
        for p in stage.Traverse()
    )
    assert found, (
        f"Expected PhysicsArticulationRootAPI on some prim. Tool calls: "
        f"{[tc.tool_name for tc in ctx.all_tool_calls]}"
    )


coverage_validate_scene = AgentScenario(
    name="coverage_validate_scene",
    description="Ask the agent to verify the scene is OK; expect validate_scene.",
    tier="tool_coverage",
    setup=setup_scene_with_ground_and_box,
    prompts=[
        "Can you check whether my scene is well-formed? "
        "Are there any issues I should fix before exporting?",
    ],
    assertions=[_assert_validate_scene_invoked],
)


coverage_snapshot_scene = AgentScenario(
    name="coverage_snapshot_scene",
    description="Ask to save a snapshot for safekeeping.",
    tier="tool_coverage",
    setup=setup_scene_with_ground_and_box,
    prompts=[
        "Save a checkpoint of the current scene state called "
        "'before_physics' so I can come back to it.",
    ],
    assertions=[_assert_snapshot_invoked],
)


coverage_collision_groups = AgentScenario(
    name="coverage_collision_groups",
    description="Players don't collide with each other; create the group + filter.",
    tier="tool_coverage",
    setup=setup_scene_with_three_rigid_bodies,
    prompts=[
        "I have three boxes. Put them all in a collision group called "
        "'Players' so they collide with the floor but not with each "
        "other. Set up the filter accordingly.",
    ],
    assertions=[_assert_collision_group_created],
)


coverage_articulation_root = AgentScenario(
    name="coverage_articulation_root",
    description="Author an articulation root on a chain of bodies.",
    tier="tool_coverage",
    setup=setup_scene_with_three_rigid_bodies,
    prompts=[
        "These three boxes are going to form an articulated chain. Mark "
        "the chain as one articulation so the solver treats them as a "
        "single jointed system instead of independent bodies.",
    ],
    assertions=[_assert_articulation_root_applied],
)


ALL = [
    coverage_validate_scene,
    coverage_snapshot_scene,
    coverage_collision_groups,
    coverage_articulation_root,
]
