# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Diagnostic scenarios: broken setups; agent must call diagnose to find evidence."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdPhysics

from tests.agent.runner import AgentScenario, ScenarioContext


def _stage_path(project_dir: Path) -> Path:
    return project_dir / "scene.usda"


def _setup_broken_pendulum(project_dir: Path) -> None:
    """Two-cube pendulum with localPos values far outside the bodies' bounds."""
    stage = Usd.Stage.Open(str(_stage_path(project_dir)))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    for name, y in (("Cube_Anchor", 5.0), ("Cube_Bob", 3.0)):
        prim = stage.DefinePrim(f"/Scene/{name}", "Xform")
        UsdGeom.Xformable(prim).AddTranslateOp().Set((0.0, y, 0.0))
        UsdGeom.Cube.Define(stage, f"/Scene/{name}/Shape").CreateSizeAttr(1.0)

    stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(stage, "/Scene/Physics/PhysicsScene")

    anchor = stage.GetPrimAtPath("/Scene/Cube_Anchor")
    UsdPhysics.RigidBodyAPI.Apply(anchor)
    UsdPhysics.RigidBodyAPI(anchor).CreateKinematicEnabledAttr(True)
    UsdPhysics.RigidBodyAPI.Apply(stage.GetPrimAtPath("/Scene/Cube_Bob"))

    joint = UsdPhysics.RevoluteJoint.Define(
        stage, "/Scene/Physics/Bob_to_Anchor_Revolute",
    )
    joint.CreateBody0Rel().SetTargets([Sdf.Path("/Scene/Cube_Anchor")])
    joint.CreateBody1Rel().SetTargets([Sdf.Path("/Scene/Cube_Bob")])
    joint.CreateAxisAttr("Z")
    joint.CreateLocalPos0Attr((0.0, -100.0, 0.0))
    joint.CreateLocalPos1Attr((0.0, 100.0, 0.0))
    stage.Save()


def _assert_diagnose_called(ctx: ScenarioContext) -> None:
    called = {tc.tool_name for tc in ctx.all_tool_calls}
    assert "diagnose" in called, (
        f"Agent should have called diagnose; called instead: "
        f"{sorted(called)}"
    )


def _assert_localpos_surfaced(ctx: ScenarioContext) -> None:
    for tc in ctx.tool_calls_for("diagnose"):
        if not tc.success or tc.data is None:
            continue
        for finding in tc.data.get("findings", []):
            if finding.get("check_id") == "physics:joint_local_pos_within_bounds":
                return
    raise AssertionError(
        "Expected diagnose to surface physics:joint_local_pos_within_bounds "
        f"finding; tool calls: {[tc.tool_name for tc in ctx.all_tool_calls]}"
    )


broken_pendulum_diagnosis = AgentScenario(
    name="diagnose_broken_pendulum",
    description="Pendulum with bad localPos; agent should diagnose, not speculate.",
    tier="diagnose",
    suites=("smoke", "full"),
    setup=_setup_broken_pendulum,
    prompts=[
        "the pendulum I built between /Scene/Cube_Anchor and /Scene/Cube_Bob "
        "is not swinging when I simulate. can you tell me why?",
    ],
    assertions=[_assert_diagnose_called, _assert_localpos_surfaced],
)


ALL = [
    broken_pendulum_diagnosis,
]
