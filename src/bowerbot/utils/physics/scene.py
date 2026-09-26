# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics scene — the PhysicsScene prim, its scope and gravity."""

from __future__ import annotations

import logging
from typing import Any

from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

from bowerbot.schemas import PhysicsDefaults, PhysicsNamespace, SceneNamespace
from bowerbot.utils.core.integrity import remove_scene_prim
from bowerbot.utils.core.metrics import axis_index
from bowerbot.utils.core.values import from_float32
from bowerbot.utils.physics.predicates import is_physics_scene

logger = logging.getLogger(__name__)


def ensure_physics_scope(stage: Usd.Stage) -> str:
    """Create ``/Scene/Physics`` as a Scope if missing; return its path."""
    scope_path = SceneNamespace.PHYSICS
    if not stage.GetPrimAtPath(scope_path).IsValid():
        stage.DefinePrim(scope_path, "Scope")
    return scope_path


def ensure_physics_scene(stage: Usd.Stage) -> str:
    """The scene's physics scene: the one already there, or a new default one.

    An existing scene is returned untouched, so authoring physics never resets
    the gravity the user set, whatever the scene is named.
    """
    existing = physics_scene_paths(stage)
    if existing:
        return existing[0]
    return author_physics_scene(stage, PhysicsNamespace.DEFAULT_SCENE_NAME)


def author_physics_scene(
    stage: Usd.Stage,
    name: str,
    gravity_magnitude: float | None = None,
    gravity_direction: tuple[float, float, float] | None = None,
) -> str:
    """Define or update the physics scene *name*, authoring only the gravity values given.

    A new scene gets the default for any value not given; an existing scene
    keeps what it has for those.
    """
    scene_path = f"{ensure_physics_scope(stage)}/{name}"
    is_new = not is_physics_scene(stage.GetPrimAtPath(scene_path))
    scene = UsdPhysics.Scene.Define(stage, scene_path)
    if is_new:
        default_magnitude, default_direction = default_gravity(stage)
        if gravity_magnitude is None:
            gravity_magnitude = default_magnitude
        if gravity_direction is None:
            gravity_direction = default_direction
    if gravity_magnitude is not None:
        scene.CreateGravityMagnitudeAttr(gravity_magnitude)
    if gravity_direction is not None:
        scene.CreateGravityDirectionAttr(Gf.Vec3f(*gravity_direction))
    stage.Save()
    logger.info("Authored PhysicsScene at %s", scene_path)
    return scene_path


def default_gravity(stage: Usd.Stage) -> tuple[float, tuple[float, float, float]]:
    """Earth gravity in stage units, pointing down the stage's up axis."""
    meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
    down = [0.0, 0.0, 0.0]
    down[axis_index(UsdGeom.GetStageUpAxis(stage))] = -1.0
    return PhysicsDefaults.EARTH_GRAVITY / meters_per_unit, (down[0], down[1], down[2])


def scene_gravity(stage: Usd.Stage, scene_path: str) -> tuple[float, tuple[float, float, float]]:
    """The gravity *scene_path* simulates with: its authored values, else the defaults."""
    scene = UsdPhysics.Scene(stage.GetPrimAtPath(scene_path))
    magnitude, direction = default_gravity(stage)
    # UsdPhysics fallbacks: -inf magnitude means Earth gravity, a zero direction
    # means down the up axis, which is what default_gravity returns.
    authored_magnitude = scene.GetGravityMagnitudeAttr().Get()
    if authored_magnitude is not None and authored_magnitude != float("-inf"):
        magnitude = from_float32(authored_magnitude)
    authored_direction = scene.GetGravityDirectionAttr().Get()
    if authored_direction is not None and any(authored_direction):
        x, y, z = authored_direction
        direction = (from_float32(x), from_float32(y), from_float32(z))
    return magnitude, direction


def physics_scene_paths(stage: Usd.Stage) -> list[str]:
    """Every ``UsdPhysics.Scene`` prim under ``/Scene/Physics``, in namespace order."""
    scope = stage.GetPrimAtPath(SceneNamespace.PHYSICS)
    if not scope.IsValid():
        return []
    return [str(prim.GetPath()) for prim in Usd.PrimRange(scope) if is_physics_scene(prim)]


def list_physics_scenes(stage: Usd.Stage) -> list[dict[str, Any]]:
    """Every ``UsdPhysics.Scene`` under ``/Scene/Physics`` with the gravity it simulates with."""
    scenes = []
    for path in physics_scene_paths(stage):
        magnitude, direction = scene_gravity(stage, path)
        scenes.append({
            "prim_path": path,
            "name": Sdf.Path(path).name,
            "gravity_magnitude": magnitude,
            "gravity_direction": list(direction),
        })
    return scenes


def remove_physics_scene(stage: Usd.Stage, name: str) -> dict[str, Any] | None:
    """Remove a ``UsdPhysics.Scene`` prim by name and the rel targets naming it.

    Returns the dropped-targets report (``simulationOwner`` rels that
    pointed at the scene), or ``None`` if no physics scene has that name.
    """
    path = f"{SceneNamespace.PHYSICS}/{name}"
    if not is_physics_scene(stage.GetPrimAtPath(path)):
        return None
    return remove_scene_prim(stage, path)


def format_physics_scene_prim(prim: Usd.Prim) -> dict[str, Any]:
    """Format a ``UsdPhysics.Scene`` for ``list_prims``."""
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "physics_scene",
        "type": str(prim.GetTypeName()),
    }
