# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Transforms — reading and writing xform ops, world ↔ local, and positions inside assets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from pxr import Gf, Usd, UsdGeom

from bowerbot.schemas import PositionDefaults, PositionMode, SceneNamespace
from bowerbot.schemas.surface import FloatArray
from bowerbot.schemas.transforms import PartialVec3, Vec3
from bowerbot.utils.core.asset_folder import find_root_file, get_geometry_bounds, get_mpu
from bowerbot.utils.core.metrics import asset_conform, axis_index


def extract_position(prim: Usd.Prim) -> dict[str, float] | None:
    """Return a prim's world-space position in scene units (what ``list_scene`` reports)."""
    if not UsdGeom.Xformable(prim):
        return None
    x, y, z = (round(v, 4) for v in world_position(prim))
    return {"x": x, "y": y, "z": z}


def read_translate_rotate(prim: Usd.Prim) -> tuple[Vec3, Vec3]:
    """Return the ``(translate, rotateXYZ)`` op values on *prim*; missing ops read as 0."""
    translate: Vec3 = (0.0, 0.0, 0.0)
    rotate: Vec3 = (0.0, 0.0, 0.0)
    for op in UsdGeom.Xformable(prim).GetOrderedXformOps():
        value = op.Get()
        if value is None:
            continue
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            translate = (float(value[0]), float(value[1]), float(value[2]))
        elif op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            rotate = (float(value[0]), float(value[1]), float(value[2]))
    return translate, rotate


def world_position(prim: Usd.Prim) -> Vec3:
    """Return *prim*'s world-space origin."""
    t = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(
        Usd.TimeCode.Default(),
    ).ExtractTranslation()
    return float(t[0]), float(t[1]), float(t[2])


def set_transform(
    stage: Usd.Stage,
    prim_path: str,
    translate: tuple[float, float, float],
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> None:
    """Update translate/rotate on an existing prim in place."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)

    xformable = UsdGeom.Xformable(prim)
    tx, ty, tz = translate
    rx, ry, rz = rotate

    found_translate = False
    found_rotate = False
    for op in xformable.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            if op.GetOpName() == "xformOp:translate":
                op.Set(Gf.Vec3d(tx, ty, tz))
                found_translate = True
        elif op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            op.Set(Gf.Vec3f(rx, ry, rz))
            found_rotate = True

    if not found_translate:
        xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))
    if not found_rotate and any(v != 0.0 for v in (rx, ry, rz)):
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))


def update_translate_op(prim: Usd.Prim, value: Gf.Vec3d) -> None:
    """Set *prim*'s ``xformOp:translate``, adding it first in the op order when missing."""
    xformable = UsdGeom.Xformable(prim)
    ops = xformable.GetOrderedXformOps()
    for op in ops:
        if op.GetOpName() == "xformOp:translate":
            op.Set(value)
            return
    translate = xformable.AddTranslateOp()
    translate.Set(value)
    xformable.SetXformOpOrder([translate, *ops])


def update_rotate_op(prim: Usd.Prim, value: Gf.Vec3f) -> None:
    """Set *prim*'s rotateXYZ op, adding it right after the translate when missing."""
    xformable = UsdGeom.Xformable(prim)
    ops = xformable.GetOrderedXformOps()
    for op in ops:
        if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            op.Set(value)
            return
    rotate = xformable.AddRotateXYZOp()
    rotate.Set(value)
    at = next(
        (i + 1 for i, op in enumerate(ops) if op.GetOpName() == "xformOp:translate"), 0,
    )
    xformable.SetXformOpOrder([*ops[:at], rotate, *ops[at:]])


def top_parts(prim: Usd.Prim) -> list[Usd.Prim]:
    """The first transformable prims below *prim*, looking through scopes and other groupings.

    Inactive and unloaded children count too (they keep their place when turned
    back on), and so do the parts inside an instanced grouping.
    """
    parts: list[Usd.Prim] = []
    for child in prim.GetFilteredChildren(Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)):
        if child.IsA(UsdGeom.Xformable):
            parts.append(child)
        else:
            parts.extend(top_parts(child))
    return parts


def asset_world_inverse(stage: Usd.Stage, prim_path: str) -> Gf.Matrix4d | None:
    """World -> the frame of the asset a placement references (asset units and axes).

    *prim_path* is a placement wrapper or its ``asset`` child. The ``asset``
    child's world transform includes the placement, the unit scale and the
    up-axis correction, so points land in the asset's own coordinates.
    """
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return None
    frame = prim
    if prim.GetName() != SceneNamespace.ASSET_CHILD:
        child = prim.GetChild(SceneNamespace.ASSET_CHILD)
        frame = child if child and child.IsValid() else prim
    return UsdGeom.XformCache().GetLocalToWorldTransform(frame).GetInverse()


def resolve_position_in_asset(
    stage: Usd.Stage,
    asset_prim_path: str,
    asset_dir: Path,
    mode: PositionMode,
    given: PartialVec3,
    *,
    current_local: Vec3 | None = None,
    current_world: Vec3 | None = None,
) -> Vec3:
    """Where a position asked for in the scene lands in the asset, in asset-local meters.

    ``absolute``: world coordinates in scene units, converted through the
    placement. ``bounds_offset``: meters from the asset's bounds along the
    scene's axes (as the asset is conformed to the scene): from the top (up
    value >= 0) or the bottom (< 0) along the up axis, from the center along the
    other two; an omitted up value sits just above the top. Omitted axes keep
    *current_world* / *current_local* when given (an update); otherwise they
    read as 0 (and the up value as above the top).
    """
    asset_mpu = get_mpu(asset_dir)
    if mode is PositionMode.ABSOLUTE:
        base = current_world or (0.0, 0.0, 0.0)
        world = Gf.Vec3d(*(b if g is None else g for g, b in zip(given, base, strict=True)))
        world_to_asset = asset_world_inverse(stage, asset_prim_path)
        local = world_to_asset.Transform(world) if world_to_asset is not None else world
        return local[0] * asset_mpu, local[1] * asset_mpu, local[2] * asset_mpu

    bounds = get_geometry_bounds(asset_dir)
    correction = scene_correction(stage, asset_dir)
    target = _bounds_offset_target(
        bounds, given, up=axis_index(UsdGeom.GetStageUpAxis(stage)), correction=correction,
    )
    if current_local is None:
        return target
    x, y, z = (
        t if named else cur
        for named, t, cur in zip(
            _asset_axes(given, correction), target, current_local, strict=True,
        )
    )
    return x, y, z


def scene_correction(stage: Usd.Stage, asset_dir: Path) -> float | None:
    """The up-axis turn (degrees about X) conforming *asset_dir*'s asset to *stage*, or None."""
    root_file = find_root_file(asset_dir)
    return asset_conform(stage, str(root_file))[1] if root_file is not None else None


def _bounds_offset_target(
    bounds: dict[str, dict[str, float]] | None,
    given: PartialVec3,
    *,
    up: int,
    correction: float | None,
) -> Vec3:
    """Asset-local meters for offsets from the bounds, given along the scene's axes."""
    offsets = [0.0 if g is None else g for g in given]
    if bounds is None:
        x, y, z = _to_asset_axes(Gf.Vec3d(*offsets), correction)
        return x, y, z
    to_scene = _correction_rotation(correction)
    corners = [
        to_scene.TransformDir(Gf.Vec3d(
            bounds["max" if i & 1 else "min"]["x"],
            bounds["max" if i & 2 else "min"]["y"],
            bounds["max" if i & 4 else "min"]["z"],
        ))
        for i in range(8)
    ]
    low = [min(c[axis] for c in corners) for axis in range(3)]
    high = [max(c[axis] for c in corners) for axis in range(3)]
    target = [(low[axis] + high[axis]) / 2 + offsets[axis] for axis in range(3)]
    if given[up] is None:
        target[up] = high[up] + PositionDefaults.ABOVE_BOUNDS_METERS
    elif offsets[up] >= 0:
        target[up] = high[up] + offsets[up]
    else:
        target[up] = low[up] + offsets[up]
    x, y, z = _to_asset_axes(Gf.Vec3d(*target), correction)
    return x, y, z


def _correction_rotation(correction: float | None) -> Gf.Rotation:
    """The up-axis correction (a rotation about X) as a Gf.Rotation."""
    return Gf.Rotation(Gf.Vec3d.XAxis(), correction or 0.0)


def _to_asset_axes(scene_vec: Gf.Vec3d, correction: float | None) -> Vec3:
    """A vector along the conformed (scene) axes, in the asset's own axes."""
    v = _correction_rotation(correction).GetInverse().TransformDir(scene_vec)
    return float(v[0]), float(v[1]), float(v[2])


def _asset_axes(given: PartialVec3, correction: float | None) -> tuple[bool, bool, bool]:
    """Which asset-local axes the scene axes named in *given* map onto."""
    named = _to_asset_axes(Gf.Vec3d(*(0.0 if g is None else 1.0 for g in given)), correction)
    x, y, z = (abs(v) > 0.5 for v in named)
    return x, y, z


def asset_axes_rotation(rotate: Vec3, correction: float | None) -> Vec3:
    """A nested placement's rotateXYZ given in scene axes, in its container's axes.

    The nested asset carries its own conform, so unrotated it already stands
    upright; the rotation is re-expressed in the container's axes (conformed
    by *correction*). For a light, which has no conform, use
    :func:`orientation_in_asset`.
    """
    if not correction:
        return rotate
    c = _correction_rotation(correction)
    return rotation_to_rotate_xyz(c * rotate_xyz_rotation(rotate) * c.GetInverse())


def scene_axes_rotation(rotate: Vec3, correction: float | None) -> Vec3:
    """The inverse of :func:`asset_axes_rotation`: an asset-axes rotateXYZ in scene axes."""
    if not correction:
        return rotate
    c = _correction_rotation(correction)
    return rotation_to_rotate_xyz(c.GetInverse() * rotate_xyz_rotation(rotate) * c)


def orientation_in_asset(rotate: Vec3, correction: float | None) -> Vec3:
    """An asset light's rotateXYZ given in scene axes, authored in its asset's axes.

    A light has no conform of its own, so the asset's up-axis turn
    (*correction*) is undone: the light faces where a scene light with the
    same rotation would.
    """
    if not correction:
        return rotate
    return rotation_to_rotate_xyz(
        rotate_xyz_rotation(rotate) * _correction_rotation(correction).GetInverse(),
    )


def orientation_in_scene(rotate: Vec3, correction: float | None) -> Vec3:
    """The inverse of :func:`orientation_in_asset`: an asset light's rotateXYZ in scene axes."""
    if not correction:
        return rotate
    return rotation_to_rotate_xyz(rotate_xyz_rotation(rotate) * _correction_rotation(correction))


def rotate_xyz_rotation(value: Any) -> Gf.Rotation:
    """Gf.Rotation equal to an xformOp:rotateXYZ value (X applied first)."""
    rx, ry, rz = (float(v) for v in (value or (0.0, 0.0, 0.0)))
    return (
        Gf.Rotation(Gf.Vec3d.XAxis(), rx)
        * Gf.Rotation(Gf.Vec3d.YAxis(), ry)
        * Gf.Rotation(Gf.Vec3d.ZAxis(), rz)
    )


def rotation_to_rotate_xyz(rotation: Gf.Rotation) -> Vec3:
    """The smaller of the two rotateXYZ triples equal to *rotation*, so a yaw stays (0, yaw, 0)."""
    rz, ry, rx = rotation.Decompose(Gf.Vec3d.ZAxis(), Gf.Vec3d.YAxis(), Gf.Vec3d.XAxis())

    def wrap(angle: float) -> float:
        wrapped = (angle + 180.0) % 360.0 - 180.0
        return 0.0 if abs(wrapped) < 1e-6 else round(wrapped, 4)

    first = (wrap(rx), wrap(ry), wrap(rz))
    second = (wrap(rx + 180.0), wrap(180.0 - ry), wrap(rz + 180.0))
    return min(first, second, key=lambda angles: sum(abs(a) for a in angles))


def gf_matrix_to_numpy(matrix: Gf.Matrix4d) -> FloatArray:
    """A Gf.Matrix4d as a (4, 4) float64 array (row-vector convention)."""
    return np.array(matrix, dtype=np.float64)
