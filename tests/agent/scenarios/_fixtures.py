# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Reusable scene-setup helpers for scenario ``setup`` callables."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdPhysics


def _stage_path(project_dir: Path) -> Path:
    return project_dir / "scene.usda"


def setup_two_cubes_in_scene(project_dir: Path) -> None:
    """Author /Scene/Cube_Anchor and /Scene/Cube_Bob as raw Cubes."""
    scene_path = _stage_path(project_dir)
    stage = Usd.Stage.Open(str(scene_path))
    UsdGeom.Cube.Define(stage, "/Scene/Cube_Anchor").AddTranslateOp().Set(
        (0.0, 5.0, 0.0),
    )
    UsdGeom.Cube.Define(stage, "/Scene/Cube_Bob").AddTranslateOp().Set(
        (0.0, 3.0, 0.0),
    )
    stage.Save()


def setup_scene_with_ground_and_box(project_dir: Path) -> None:
    """Author a flat Plane mesh + a Cube above it for falling-body scenarios."""
    scene_path = _stage_path(project_dir)
    stage = Usd.Stage.Open(str(scene_path))
    plane = UsdGeom.Mesh.Define(stage, "/Scene/Ground")
    plane.CreatePointsAttr([
        (-5.0, 0.0, -5.0), (5.0, 0.0, -5.0),
        (5.0, 0.0, 5.0), (-5.0, 0.0, 5.0),
    ])
    plane.CreateFaceVertexCountsAttr([4])
    plane.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    UsdGeom.Cube.Define(stage, "/Scene/Box").AddTranslateOp().Set(
        (0.0, 3.0, 0.0),
    )
    stage.Save()


def setup_scene_with_three_rigid_bodies(project_dir: Path) -> None:
    """Author three Xforms with PhysicsRigidBodyAPI for iteration scenarios.

    Each body has a Mesh child (not a Cube) so MeshCollisionAPI with
    convex approximations is applicable on the geometry.
    """
    scene_path = _stage_path(project_dir)
    stage = Usd.Stage.Open(str(scene_path))
    for i, x in enumerate((-2.0, 0.0, 2.0)):
        prim = stage.DefinePrim(f"/Scene/Box_{i + 1:02d}", "Xform")
        UsdGeom.Xformable(prim).AddTranslateOp().Set((x, 1.0, 0.0))
        UsdPhysics.RigidBodyAPI.Apply(prim)
        mesh = UsdGeom.Mesh.Define(stage, f"/Scene/Box_{i + 1:02d}/Shape")
        mesh.CreatePointsAttr([
            (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5),
            (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
            (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5),
            (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
        ])
        mesh.CreateFaceVertexCountsAttr([4, 4, 4, 4, 4, 4])
        mesh.CreateFaceVertexIndicesAttr([
            0, 1, 2, 3,  4, 7, 6, 5,
            0, 4, 5, 1,  1, 5, 6, 2,
            2, 6, 7, 3,  3, 7, 4, 0,
        ])
    stage.Save()


def setup_scene_with_two_xforms(project_dir: Path) -> None:
    """Two named scene-only Xforms — used for invalid-target refusal tests."""
    scene_path = _stage_path(project_dir)
    stage = Usd.Stage.Open(str(scene_path))
    stage.DefinePrim("/Scene/EmptyParent", "Xform")
    stage.DefinePrim("/Scene/AnotherEmpty", "Xform")
    stage.Save()


def setup_scene_with_one_cube(project_dir: Path) -> None:
    """A single Cube at /Scene/Block — used for short authoring scenarios."""
    scene_path = _stage_path(project_dir)
    stage = Usd.Stage.Open(str(scene_path))
    UsdGeom.Cube.Define(stage, "/Scene/Block").AddTranslateOp().Set(
        (0.0, 1.0, 0.0),
    )
    stage.Save()


def get_prim_paths_with_api(
    stage: Usd.Stage, api_name: str,
) -> list[str]:
    """Helper for assertions: every prim path that carries *api_name*."""
    out: list[str] = []
    for prim in stage.Traverse():
        if api_name in prim.GetAppliedSchemas():
            out.append(str(prim.GetPath()))
    return out


def get_typed_prim_paths(stage: Usd.Stage, type_name: str) -> list[str]:
    """Helper for assertions: every prim path with the given typeName."""
    out: list[str] = []
    for prim in stage.Traverse():
        if str(prim.GetTypeName()) == type_name:
            out.append(str(prim.GetPath()))
    return out


_ = Sdf  # silence unused-import warning in case helpers expand
