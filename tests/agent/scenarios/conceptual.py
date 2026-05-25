# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Conceptual-question tier: agent is asked to explain, not act.

State assertions are minimal — the value is in the artifact transcript.
The only objective check is that the agent did not author anything (the
user asked a question; mutating the stage would be wrong).
"""

from __future__ import annotations

from tests.agent.runner import AgentScenario, ScenarioContext

_AUTHORING_TOOLS = frozenset({
    "place_asset", "create_light", "create_material",
    "apply_physics_api", "remove_physics_api", "create_joint",
    "setup_physics_scene", "create_or_update_collision_group",
    "set_prim_attribute", "save_snapshot",
    "create_or_update_material_variant",
})


def _assert_no_authoring(ctx: ScenarioContext) -> None:
    called = {tc.tool_name for tc in ctx.all_tool_calls}
    overlap = _AUTHORING_TOOLS & called
    assert not overlap, (
        f"A conceptual question should not author anything. The agent "
        f"called: {overlap}"
    )


conceptual_approximation_types = AgentScenario(
    name="conceptual_approximation_types",
    description="Ask the agent to explain convex hull vs convex decomposition.",
    tier="conceptual",
    prompts=[
        "Can you explain the difference between convex hull and convex "
        "decomposition collision approximations? When would I use one "
        "over the other?",
    ],
    assertions=[_assert_no_authoring],
)


conceptual_rigid_vs_static = AgentScenario(
    name="conceptual_rigid_vs_static",
    description="Ask whether to use a rigid body or static collider for a floor.",
    tier="conceptual",
    prompts=[
        "I'm setting up a scene with a floor and some props on top. The "
        "floor shouldn't move, but the props should fall onto it. "
        "Should the floor have a rigid body or just collision? Walk me "
        "through it.",
    ],
    assertions=[_assert_no_authoring],
)


ALL = [
    conceptual_approximation_types,
    conceptual_rigid_vs_static,
]
