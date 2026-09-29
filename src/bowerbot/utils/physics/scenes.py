# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics scenes under ``/Scene/Physics`` and their gravity."""

from __future__ import annotations

import logging
from typing import Any

from pxr import Gf
from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdPhysics

from bowerbot import constants

logger = logging.getLogger(__name__)


def ensure_scope(stage: Usd.Stage) -> str:
    """Create ``/Scene/Physics`` as a Scope if missing; return its path."""
    scope_path = constants.SceneNamespace.PHYSICS
    if not stage.GetPrimAtPath(scope_path).IsValid():
        stage.DefinePrim(scope_path, "Scope")
    return scope_path


def list_all(stage: Usd.Stage) -> list[dict[str, Any]]:
    """Return every ``UsdPhysics.Scene`` prim under ``/Scene/Physics``."""
    scope = stage.GetPrimAtPath(constants.SceneNamespace.PHYSICS)
    if not scope or not scope.IsValid():
        return []
    return [
        {
            "prim_path": str(p.GetPath()),
            "name": p.GetName(),
            "gravity_magnitude": (
                p.GetAttribute("physics:gravityMagnitude").Get()
            ),
            "gravity_direction": (
                list(p.GetAttribute("physics:gravityDirection").Get() or [])
            ),
        }
        for p in Usd.PrimRange(scope)
        if p.IsA(UsdPhysics.Scene)
    ]


def remove(stage: Usd.Stage, name: str) -> bool:
    """Remove a ``UsdPhysics.Scene`` prim by name; return True if removed."""
    path = f"{constants.SceneNamespace.PHYSICS}/{name}"
    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid() or not prim.IsA(UsdPhysics.Scene):
        return False
    stage.RemovePrim(Sdf.Path(path))
    stage.Save()
    return True


def resolve_gravity(
    stage: Usd.Stage,
    gravity_magnitude: float | None,
    gravity_direction: tuple[float, float, float] | None,
) -> tuple[float, tuple[float, float, float]]:
    """Resolve gravity to authored values; defaults to Earth gravity (stage units) along -Y."""
    if gravity_magnitude is None:
        mpu = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
        gravity_magnitude = 9.81 / mpu
    if gravity_direction is None:
        gravity_direction = (0.0, -1.0, 0.0)
    return float(gravity_magnitude), gravity_direction


def ensure(
    stage: Usd.Stage,
    name: str = "PhysicsScene",
    gravity_magnitude: float | None = None,
    gravity_direction: tuple[float, float, float] | None = None,
) -> str:
    """Create the physics scope and a ``UsdPhysics.Scene`` child prim."""
    scope_path = ensure_scope(stage)
    scene_path = f"{scope_path}/{name}"
    scene_prim = UsdPhysics.Scene.Define(stage, scene_path)

    gravity_magnitude, gravity_direction = resolve_gravity(
        stage, gravity_magnitude, gravity_direction,
    )
    scene_prim.CreateGravityDirectionAttr(Gf.Vec3f(*gravity_direction))
    scene_prim.CreateGravityMagnitudeAttr(gravity_magnitude)

    stage.Save()
    logger.info(
        "Set up PhysicsScene at %s (gravity magnitude %s)",
        scene_path, gravity_magnitude,
    )
    return scene_path
