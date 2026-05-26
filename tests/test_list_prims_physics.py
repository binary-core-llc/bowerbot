# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""list_prims surfaces physics infrastructure (scene, joints, collision groups)."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdPhysics

from bowerbot.utils import stage_utils


def _scene_with_pendulum(tmp_path: Path) -> Usd.Stage:
    scene_path = tmp_path / "scene.usda"
    stage = Usd.Stage.CreateNew(str(scene_path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim("/Scene", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, "/Scene/Cube_Anchor").AddTranslateOp().Set(
        (0.0, 5.0, 0.0),
    )
    UsdGeom.Cube.Define(stage, "/Scene/Cube_Bob").AddTranslateOp().Set(
        (0.0, 3.0, 0.0),
    )
    stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(stage, "/Scene/Physics/PhysicsScene")
    joint = UsdPhysics.RevoluteJoint.Define(
        stage, "/Scene/Physics/Bob_to_Anchor_Revolute",
    )
    joint.CreateBody0Rel().SetTargets([Sdf.Path("/Scene/Cube_Anchor")])
    joint.CreateBody1Rel().SetTargets([Sdf.Path("/Scene/Cube_Bob")])
    joint.CreateAxisAttr("Z")
    stage.Save()
    return stage


def _by_kind(results: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for entry in results:
        out.setdefault(entry["kind"], []).append(entry)
    return out


def test_list_prims_surfaces_physics_scene(tmp_path: Path) -> None:
    stage = _scene_with_pendulum(tmp_path)

    results = stage_utils.list_prims(stage)

    grouped = _by_kind(results)
    assert "physics_scene" in grouped
    assert grouped["physics_scene"][0]["prim_path"] == "/Scene/Physics/PhysicsScene"


def test_list_prims_surfaces_joints_with_body_rels(tmp_path: Path) -> None:
    stage = _scene_with_pendulum(tmp_path)

    results = stage_utils.list_prims(stage)

    grouped = _by_kind(results)
    assert "joint" in grouped
    joint = grouped["joint"][0]
    assert joint["prim_path"] == "/Scene/Physics/Bob_to_Anchor_Revolute"
    assert joint["type"] == "PhysicsRevoluteJoint"
    assert joint["body0"] == "/Scene/Cube_Anchor"
    assert joint["body1"] == "/Scene/Cube_Bob"


def test_list_prims_surfaces_collision_groups(tmp_path: Path) -> None:
    stage = _scene_with_pendulum(tmp_path)
    group = UsdPhysics.CollisionGroup.Define(
        stage, "/Scene/Physics/Movables",
    )
    group.GetCollidersCollectionAPI().CreateIncludesRel().SetTargets(
        [Sdf.Path("/Scene/Cube_Bob")],
    )
    stage.Save()

    results = stage_utils.list_prims(stage)

    grouped = _by_kind(results)
    assert "collision_group" in grouped
    cg = grouped["collision_group"][0]
    assert cg["prim_path"] == "/Scene/Physics/Movables"
    assert cg["name"] == "Movables"


def test_list_prims_complete_pendulum_inventory(tmp_path: Path) -> None:
    """The full picture: 2 geometry cubes + 1 physics_scene + 1 joint."""
    stage = _scene_with_pendulum(tmp_path)

    results = stage_utils.list_prims(stage)

    grouped = _by_kind(results)
    assert {e["prim_path"] for e in grouped["geometry"]} == {
        "/Scene/Cube_Anchor", "/Scene/Cube_Bob",
    }
    assert len(grouped["physics_scene"]) == 1
    assert len(grouped["joint"]) == 1


def test_list_prims_every_entry_has_kind(tmp_path: Path) -> None:
    stage = _scene_with_pendulum(tmp_path)

    results = stage_utils.list_prims(stage)

    assert results
    for entry in results:
        assert "kind" in entry, entry
