# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Collider shapes: a basic shape under a part that only physics sees, in the scene or ``phy.usda``.

USD has no setting that makes a mesh collide as a cylinder: a collider is
always a geometry prim with ``PhysicsCollisionAPI``. A collider shape is that
prim: a Cube, Sphere, Capsule or Cylinder, sized in project units, with
purpose ``guide`` so renderers skip it and the asset's box does not count it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdPhysics

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import physics
from bowerbot.utils import usd

logger = logging.getLogger(__name__)

# ── Adding a shape ──


def add_in_scene(
    stage: Usd.Stage, parent_path: str, params: schemas.PhysicsColliderShapeParams,
) -> dict[str, Any]:
    """Add a collider shape under *parent_path*, written in ``scene.usda``."""
    refuse_bad_sizes(params)
    parent = _require_parent(stage, parent_path, params.name)
    prim_path = f"{parent_path}/{params.name}"
    known = physics.rules.errors(stage)
    _author(stage, prim_path, params, usd.transforms.world_scale(parent))
    physics.rules.refuse_new_errors(stage, known, f"Adding the collider {prim_path}")
    stage.Save()
    logger.info("Added %s collider %s scene-level", params.shape.value, prim_path)
    return {"prim_path": prim_path, "shape": params.shape.value, "scope": "scene"}


def add_in_asset(
    asset_dir: Path,
    parent_path: str,
    params: schemas.PhysicsColliderShapeParams,
    *,
    scene_stage: Usd.Stage,
    scene_parent_path: str,
) -> dict[str, Any]:
    """Add a collider shape under *parent_path* of the asset, written in its ``phy.usda``.

    *scene_parent_path* is the same part in *scene_stage*: its size in the
    scene turns the project-unit sizes into the asset's own. Refused when the
    scene would then have a physics error it does not have now.
    """
    refuse_bad_sizes(params)
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        raise ValueError(f"No root file in asset {asset_dir.name}")
    composed = Usd.Stage.Open(str(root_file))
    _require_parent(composed, parent_path, params.name)
    del composed

    scale = usd.transforms.world_scale(scene_stage.GetPrimAtPath(scene_parent_path))
    prim_path = f"{parent_path}/{params.name}"
    doing = f"Adding the collider {prim_path} in asset {asset_dir.name}"
    with physics.layer.edit(asset_dir, scene_stage, doing) as stage:
        _author(stage, prim_path, params, scale)
    logger.info(
        "Added %s collider %s in %s/phy.usda", params.shape.value, prim_path, asset_dir.name,
    )
    return {"prim_path": prim_path, "shape": params.shape.value, "scope": "asset"}


def shape_from_params(params: dict[str, Any]) -> schemas.PhysicsColliderShapeParams:
    """The collider shape a tool call asks for, from its flat parameters."""
    sides = [params.get(name) for name in ("size_x", "size_y", "size_z")]
    if any(side is not None for side in sides) and None in sides:
        raise ValueError("A box size needs size_x, size_y and size_z together.")
    return schemas.PhysicsColliderShapeParams(
        shape=schemas.PhysicsColliderShape(params["shape"]),
        name=params["name"],
        radius=params.get("radius"),
        height=params.get("height"),
        axis=params.get("axis"),
        size=None if sides[0] is None else usd.values.vec3(sides),
        translate=usd.values.vec3(
            [params.get(name) or 0.0 for name in ("translate_x", "translate_y", "translate_z")],
        ),
    )


def refuse_bad_sizes(params: schemas.PhysicsColliderShapeParams) -> None:
    """Refuse a shape whose sizes are missing, not positive, or not the ones it takes."""
    usd.naming.require_prim_name(params.name, "Collider name")
    shape = params.shape.value
    takes = constants.PhysicsRules.COLLIDER_SIZES[params.shape]
    given = {
        name: value for name, value in (
            ("radius", params.radius), ("height", params.height),
            ("axis", params.axis), ("size", params.size),
        ) if value is not None
    }
    missing = [name for name in takes if name not in given]
    extra = sorted(set(given) - set(takes))
    if missing or extra:
        raise ValueError(
            f"A {shape} collider takes {', '.join(takes)}"
            + (f"; missing: {', '.join(missing)}" if missing else "")
            + (f"; not used by a {shape}: {', '.join(extra)}" if extra else "")
            + ".",
        )
    lengths = {
        "radius": params.radius, "height": params.height,
        **dict(zip(("size_x", "size_y", "size_z"), params.size or (), strict=False)),
    }
    not_positive = [f"{name}={value:g}" for name, value in lengths.items()
                    if value is not None and value <= 0]
    if not_positive:
        raise ValueError(f"Collider sizes must be above zero; got {', '.join(not_positive)}.")
    if params.axis is not None and params.axis not in constants.PhysicsRules.COLLIDER_AXES:
        raise ValueError(
            f"axis takes one of {list(constants.PhysicsRules.COLLIDER_AXES)}; got {params.axis!r}.",
        )

# ── Removing a shape ──


def remove_from_scene(stage: Usd.Stage, prim_path: str) -> bool:
    """Remove a collider shape written in ``scene.usda``; False when it is not there."""
    return _remove(stage.GetRootLayer(), prim_path)


def remove_from_asset(asset_dir: Path, prim_path: str) -> bool:
    """Remove a collider shape written in the asset's ``phy.usda``; False when it is not there."""
    phy_path = physics.layer.file_path(asset_dir)
    if not phy_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    return layer is not None and _remove(layer, prim_path)


def refuse_other_prim(stage: Usd.Stage, prim_path: str) -> None:
    """Refuse removing a prim that exists but is not a collider shape BowerBot added."""
    prim = stage.GetPrimAtPath(prim_path)
    if prim and prim.IsValid():
        raise ValueError(
            f"{prim_path} is a {prim.GetTypeName() or 'prim'} that was not added with "
            "add_collider_shape, so it is not removed here. To stop a mesh from "
            "colliding use remove_physics_api with PhysicsCollisionAPI.",
        )

# ── Helpers ──


def _require_parent(stage: Usd.Stage, parent_path: str, name: str) -> Usd.Prim:
    """The part a shape goes under: it must exist, be a group, and have no child *name*."""
    parent = stage.GetPrimAtPath(parent_path)
    if not parent or not parent.IsValid():
        raise ValueError(f"Prim not found: {parent_path}")
    if parent.IsA(UsdGeom.Gprim) or not parent.IsA(UsdGeom.Xformable):
        raise ValueError(
            f"{parent_path} is a {parent.GetTypeName() or 'typeless prim'}: a collider shape "
            "goes under a part that groups geometry (an Xform), so it moves with that part. "
            "Name the prim above the mesh.",
        )
    if parent.GetChild(name).IsValid():
        raise ValueError(
            f"The name '{name}' is taken: {parent_path}/{name} already exists. "
            "Remove it first with remove_collider_shape, or use another name.",
        )
    return parent


def _author(
    stage: Usd.Stage,
    prim_path: str,
    params: schemas.PhysicsColliderShapeParams,
    scale: schemas.Vec3,
) -> None:
    """Write the shape at the stage's edit target; *scale* is how its parent is sized in the world.

    Sizes come in project units, measured in the world, so each is divided by
    the parent's scale along the axis it runs on.
    """
    shape_class = constants.PhysicsUsd.COLLIDER_SHAPES[params.shape]
    spec = Sdf.CreatePrimInLayer(stage.GetEditTarget().GetLayer(), prim_path)
    spec.specifier = Sdf.SpecifierDef
    spec.typeName = Usd.SchemaRegistry().GetConcreteSchemaTypeName(shape_class)
    prim = stage.GetPrimAtPath(prim_path)
    gprim = shape_class(prim)

    box_scale: schemas.Vec3 | None = None
    if params.shape == schemas.PhysicsColliderShape.BOX:
        size = usd.values.vec3(params.size)
        gprim.CreateSizeAttr(1.0)
        box_scale = (size[0] / scale[0], size[1] / scale[1], size[2] / scale[2])
    elif params.shape == schemas.PhysicsColliderShape.SPHERE:
        radius = usd.values.coerce_number(params.radius, "radius")
        gprim.CreateRadiusAttr(radius / (sum(scale) / 3.0))
    else:
        radius = usd.values.coerce_number(params.radius, "radius")
        height = usd.values.coerce_number(params.height, "height")
        along = constants.PhysicsRules.COLLIDER_AXES.index(str(params.axis))
        across = [value for index, value in enumerate(scale) if index != along]
        gprim.CreateAxisAttr(params.axis)
        gprim.CreateHeightAttr(height / scale[along])
        gprim.CreateRadiusAttr(radius / (sum(across) / 2.0))

    offset = (
        params.translate[0] / scale[0],
        params.translate[1] / scale[1],
        params.translate[2] / scale[2],
    )
    if box_scale is not None or any(offset):
        usd.transforms.set_xform(
            prim, translate=offset if any(offset) else None, scale=box_scale,
        )
    gprim.CreateExtentAttr(
        UsdGeom.Boundable.ComputeExtentFromPlugins(gprim, Usd.TimeCode.Default()),
    )
    gprim.CreatePurposeAttr(UsdGeom.Tokens.guide)
    UsdPhysics.CollisionAPI.Apply(prim)


def _remove(layer: Sdf.Layer, prim_path: str) -> bool:
    """Delete a collider shape's spec from *layer* and the empty overs it leaves."""
    spec = layer.GetPrimAtPath(prim_path)
    if spec is None or not _is_collider_shape(spec):
        return False
    edit = Sdf.BatchNamespaceEdit()
    edit.Add(Sdf.Path(prim_path), Sdf.Path.emptyPath)
    if not layer.Apply(edit):
        return False
    usd.namespace.prune_empty_overrides(layer, str(Sdf.Path(prim_path).GetParentPath()))
    layer.Save()
    return True


def _is_collider_shape(spec: Sdf.PrimSpec) -> bool:
    """Whether *spec* defines a collider shape: one of the shape types, tagged to collide."""
    registry = Usd.SchemaRegistry()
    shape_types = {
        registry.GetConcreteSchemaTypeName(shape_class)
        for shape_class in constants.PhysicsUsd.COLLIDER_SHAPES.values()
    }
    return (
        spec.specifier == Sdf.SpecifierDef
        and spec.typeName in shape_types
        and schemas.PhysicsApiName.COLLISION.value in physics.apis.read_api_schemas(spec)
    )
