# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics diagnostic checks: each registered check passes and fails on cue."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdPhysics

from bowerbot.config import SceneDefaults
from bowerbot.services import diagnose_service
from bowerbot.state import SceneState
from bowerbot.utils import stage_utils


def _scene_with_two_boxes(tmp_path: Path) -> SceneState:
    scene_path = tmp_path / "scene.usda"
    stage = Usd.Stage.CreateNew(str(scene_path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim("/Scene", "Xform")
    stage.SetDefaultPrim(root)
    for name, x in (("Cube_Anchor", -1.5), ("Cube_Bob", 1.5)):
        prim = stage.DefinePrim(f"/Scene/{name}", "Xform")
        UsdGeom.Xformable(prim).AddTranslateOp().Set((x, 1.0, 0.0))
        cube = UsdGeom.Cube.Define(stage, f"/Scene/{name}/Shape")
        cube.CreateSizeAttr(1.0)
    stage.Save()
    del stage
    state = SceneState(scene_defaults=SceneDefaults())
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)
    state.object_count = 2
    return state


def _finding_ids(report: dict) -> list[str]:
    return [f["check_id"] for f in report["findings"]]


def test_physics_scene_required_when_rigid_body_present(tmp_path: Path) -> None:
    state = _scene_with_two_boxes(tmp_path)
    UsdPhysics.RigidBodyAPI.Apply(
        state.stage.GetPrimAtPath("/Scene/Cube_Anchor"),
    )
    state.stage.Save()

    report = diagnose_service.diagnose(state, {})

    assert "physics:has_physics_scene" in _finding_ids(report)


def test_physics_scene_check_passes_when_scene_exists(tmp_path: Path) -> None:
    state = _scene_with_two_boxes(tmp_path)
    UsdPhysics.RigidBodyAPI.Apply(
        state.stage.GetPrimAtPath("/Scene/Cube_Anchor"),
    )
    state.stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(state.stage, "/Scene/Physics/PhysicsScene")
    state.stage.Save()

    report = diagnose_service.diagnose(state, {})

    assert "physics:has_physics_scene" not in _finding_ids(report)


def test_joint_without_bodies_flagged(tmp_path: Path) -> None:
    state = _scene_with_two_boxes(tmp_path)
    state.stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(state.stage, "/Scene/Physics/PhysicsScene")
    UsdPhysics.FixedJoint.Define(state.stage, "/Scene/Physics/Empty")
    state.stage.Save()

    report = diagnose_service.diagnose(state, {"focus": "/Scene/Physics/Empty"})

    assert "physics:joint_has_body" in _finding_ids(report)


def test_joint_without_rigid_body_flagged(tmp_path: Path) -> None:
    state = _scene_with_two_boxes(tmp_path)
    state.stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(state.stage, "/Scene/Physics/PhysicsScene")
    joint = UsdPhysics.FixedJoint.Define(state.stage, "/Scene/Physics/J")
    joint.CreateBody0Rel().SetTargets([Sdf.Path("/Scene/Cube_Anchor")])
    joint.CreateBody1Rel().SetTargets([Sdf.Path("/Scene/Cube_Bob")])
    state.stage.Save()

    report = diagnose_service.diagnose(state, {"focus": "/Scene/Physics/J"})

    assert "physics:joint_reaches_rigid_body" in _finding_ids(report)


def test_joint_with_only_kinematic_bodies_flagged(tmp_path: Path) -> None:
    state = _scene_with_two_boxes(tmp_path)
    state.stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(state.stage, "/Scene/Physics/PhysicsScene")
    for name in ("Cube_Anchor", "Cube_Bob"):
        prim = state.stage.GetPrimAtPath(f"/Scene/{name}")
        UsdPhysics.RigidBodyAPI.Apply(prim)
        prim.GetAttribute("physics:kinematicEnabled").Set(True) if (
            prim.GetAttribute("physics:kinematicEnabled")
        ) else UsdPhysics.RigidBodyAPI(prim).CreateKinematicEnabledAttr(True)
    joint = UsdPhysics.FixedJoint.Define(state.stage, "/Scene/Physics/J")
    joint.CreateBody0Rel().SetTargets([Sdf.Path("/Scene/Cube_Anchor")])
    joint.CreateBody1Rel().SetTargets([Sdf.Path("/Scene/Cube_Bob")])
    state.stage.Save()

    report = diagnose_service.diagnose(state, {"focus": "/Scene/Physics/J"})

    assert "physics:joint_has_dynamic_body" in _finding_ids(report)


def test_joint_axis_bogus_value_flagged(tmp_path: Path) -> None:
    state = _scene_with_two_boxes(tmp_path)
    state.stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(state.stage, "/Scene/Physics/PhysicsScene")
    UsdPhysics.RigidBodyAPI.Apply(state.stage.GetPrimAtPath("/Scene/Cube_Bob"))
    joint = UsdPhysics.RevoluteJoint.Define(state.stage, "/Scene/Physics/J")
    joint.CreateBody0Rel().SetTargets([Sdf.Path("/Scene/Cube_Anchor")])
    joint.CreateBody1Rel().SetTargets([Sdf.Path("/Scene/Cube_Bob")])
    joint.CreateAxisAttr("BAD")
    state.stage.Save()

    report = diagnose_service.diagnose(state, {"focus": "/Scene/Physics/J"})

    assert "physics:joint_axis_valid" in _finding_ids(report)


def test_joint_local_pos_outside_bounds_flagged(tmp_path: Path) -> None:
    state = _scene_with_two_boxes(tmp_path)
    state.stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(state.stage, "/Scene/Physics/PhysicsScene")
    UsdPhysics.RigidBodyAPI.Apply(state.stage.GetPrimAtPath("/Scene/Cube_Bob"))
    joint = UsdPhysics.RevoluteJoint.Define(state.stage, "/Scene/Physics/J")
    joint.CreateBody0Rel().SetTargets([Sdf.Path("/Scene/Cube_Anchor")])
    joint.CreateBody1Rel().SetTargets([Sdf.Path("/Scene/Cube_Bob")])
    joint.CreateAxisAttr("Z")
    joint.CreateLocalPos0Attr((0.0, -100.0, 0.0))
    joint.CreateLocalPos1Attr((0.0, 100.0, 0.0))
    state.stage.Save()

    report = diagnose_service.diagnose(state, {"focus": "/Scene/Physics/J"})

    assert "physics:joint_local_pos_within_bounds" in _finding_ids(report)


def test_dynamic_body_with_zero_mass_flagged(tmp_path: Path) -> None:
    state = _scene_with_two_boxes(tmp_path)
    state.stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(state.stage, "/Scene/Physics/PhysicsScene")
    prim = state.stage.GetPrimAtPath("/Scene/Cube_Bob")
    UsdPhysics.RigidBodyAPI.Apply(prim)
    mass_api = UsdPhysics.MassAPI.Apply(prim)
    mass_api.CreateMassAttr(0.0)
    state.stage.Save()

    report = diagnose_service.diagnose(state, {"focus": "/Scene/Cube_Bob"})

    assert "physics:dynamic_body_has_nonzero_mass" in _finding_ids(report)


def test_articulation_root_nesting_flagged(tmp_path: Path) -> None:
    state = _scene_with_two_boxes(tmp_path)
    state.stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(state.stage, "/Scene/Physics/PhysicsScene")
    UsdPhysics.ArticulationRootAPI.Apply(state.stage.GetPrimAtPath("/Scene"))
    inner = state.stage.GetPrimAtPath("/Scene/Cube_Bob")
    UsdPhysics.ArticulationRootAPI.Apply(inner)
    state.stage.Save()

    report = diagnose_service.diagnose(state, {"focus": "/Scene/Cube_Bob"})

    assert "physics:articulation_root_not_nested" in _finding_ids(report)


def test_focus_on_default_prim_is_scene_wide(tmp_path: Path) -> None:
    state = _scene_with_two_boxes(tmp_path)
    state.stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(state.stage, "/Scene/Physics/PhysicsScene")
    UsdPhysics.RigidBodyAPI.Apply(state.stage.GetPrimAtPath("/Scene/Cube_Bob"))
    joint = UsdPhysics.RevoluteJoint.Define(state.stage, "/Scene/Physics/J")
    joint.CreateBody0Rel().SetTargets([Sdf.Path("/Scene/Cube_Anchor")])
    joint.CreateBody1Rel().SetTargets([Sdf.Path("/Scene/Cube_Bob")])
    joint.CreateAxisAttr("Z")
    joint.CreateLocalPos0Attr((0.0, -100.0, 0.0))
    joint.CreateLocalPos1Attr((0.0, 100.0, 0.0))
    state.stage.Save()

    report = diagnose_service.diagnose(state, {"focus": "/Scene"})

    assert "physics:joint_local_pos_within_bounds" in _finding_ids(report)
    assert report["focus"] is None


def test_healthy_pendulum_produces_no_findings(tmp_path: Path) -> None:
    state = _scene_with_two_boxes(tmp_path)
    state.stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(state.stage, "/Scene/Physics/PhysicsScene")

    anchor = state.stage.GetPrimAtPath("/Scene/Cube_Anchor")
    UsdPhysics.RigidBodyAPI.Apply(anchor)
    anchor.GetAttribute("physics:kinematicEnabled").Set(True) if (
        anchor.GetAttribute("physics:kinematicEnabled")
    ) else UsdPhysics.RigidBodyAPI(anchor).CreateKinematicEnabledAttr(True)

    UsdPhysics.RigidBodyAPI.Apply(state.stage.GetPrimAtPath("/Scene/Cube_Bob"))

    joint = UsdPhysics.RevoluteJoint.Define(state.stage, "/Scene/Physics/J")
    joint.CreateBody0Rel().SetTargets([Sdf.Path("/Scene/Cube_Anchor")])
    joint.CreateBody1Rel().SetTargets([Sdf.Path("/Scene/Cube_Bob")])
    joint.CreateAxisAttr("Z")
    joint.CreateLocalPos0Attr((0.5, 0.0, 0.0))
    joint.CreateLocalPos1Attr((-0.5, 0.0, 0.0))
    state.stage.Save()

    report = diagnose_service.diagnose(state, {})

    assert report["findings"] == []
