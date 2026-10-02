# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics scenes under ``/Scene/Physics`` and their gravity."""

from __future__ import annotations

import logging
from typing import Any

from pxr import Gf
from pxr import Sdf
from pxr import Usd
from pxr import UsdPhysics

from bowerbot import constants
from bowerbot.utils import usd

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
            "gravity_magnitude": _rounded(p.GetAttribute("physics:gravityMagnitude").Get() or 0.0),
            "gravity_direction": [
                _rounded(v) for v in p.GetAttribute("physics:gravityDirection").Get() or []
            ],
        }
        for p in Usd.PrimRange(scope)
        if usd.prim_types.is_physics_scene(p)
    ]


def remove(stage: Usd.Stage, name: str) -> bool:
    """Remove a ``UsdPhysics.Scene`` prim by name; return True if removed."""
    path = f"{constants.SceneNamespace.PHYSICS}/{name}"
    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid() or not usd.prim_types.is_physics_scene(prim):
        return False
    stage.RemovePrim(Sdf.Path(path))
    stage.Save()
    return True


def resolve_gravity(
    gravity_magnitude: float | None,
    gravity_direction: tuple[float, float, float] | None,
    *,
    project_mpu: float,
    project_up_axis: str,
) -> tuple[float, tuple[float, float, float]]:
    """Resolve gravity to authored values; defaults to Earth gravity (project units), downward."""
    if gravity_magnitude is None:
        gravity_magnitude = 9.81 / project_mpu
    if gravity_direction is None:
        gravity_direction = (0.0, 0.0, -1.0) if project_up_axis == "Z" else (0.0, -1.0, 0.0)
    return float(gravity_magnitude), gravity_direction


def setup(
    stage: Usd.Stage,
    name: str = "PhysicsScene",
    gravity_magnitude: float | None = None,
    gravity_direction: tuple[float, float, float] | None = None,
    *,
    project_mpu: float,
    project_up_axis: str,
) -> tuple[str, float, tuple[float, float, float]]:
    """Create or update a physics scene; return its path and the gravity it has now.

    A gravity value left out keeps what the scene already has. A new scene
    gets Earth gravity in project units, pointing down.
    """
    scope_path = ensure_scope(stage)
    scene_path = f"{scope_path}/{name}"
    existing = stage.GetPrimAtPath(scene_path)
    is_new = not (existing.IsValid() and usd.prim_types.is_physics_scene(existing))
    scene = UsdPhysics.Scene.Define(stage, scene_path)

    default_magnitude, default_direction = resolve_gravity(
        None, None, project_mpu=project_mpu, project_up_axis=project_up_axis,
    )
    if gravity_magnitude is not None or is_new:
        scene.CreateGravityMagnitudeAttr(
            default_magnitude if gravity_magnitude is None else float(gravity_magnitude),
        )
    if gravity_direction is not None or is_new:
        scene.CreateGravityDirectionAttr(Gf.Vec3f(*(gravity_direction or default_direction)))

    stage.Save()
    held = scene.GetGravityDirectionAttr().Get()
    magnitude = _rounded(scene.GetGravityMagnitudeAttr().Get())
    direction = (_rounded(held[0]), _rounded(held[1]), _rounded(held[2]))
    logger.info("Set up PhysicsScene at %s (gravity magnitude %s)", scene_path, magnitude)
    return scene_path, magnitude, direction


def ensure_default(stage: Usd.Stage, *, project_mpu: float, project_up_axis: str) -> None:
    """Make sure the scene has a physics scene; one that is already there is left as it is."""
    if list_all(stage):
        return
    setup(stage, project_mpu=project_mpu, project_up_axis=project_up_axis)


# ── Helpers ──


def _rounded(value: float) -> float:
    """A stored single-precision value without its float noise (1.62, not 1.620000005)."""
    return round(float(value), 6)
