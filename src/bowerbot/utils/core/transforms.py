# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Transforms — reading and writing xform ops, world ↔ local, and positions inside assets."""

from __future__ import annotations

import numpy as np
from pxr import Gf, Usd, UsdGeom

from bowerbot.schemas import PositionDefaults, PositionMode, SceneNamespace
from bowerbot.schemas.surface import FloatArray
from bowerbot.schemas.transforms import PartialVec3, Vec3


def extract_position(prim: Usd.Prim) -> dict[str, float] | None:
    """Return the translate component of a prim's local transform."""
    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        return None
    t = xformable.GetLocalTransformation().ExtractTranslation()
    return {"x": round(t[0], 2), "y": round(t[1], 2), "z": round(t[2], 2)}


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


def read_translate_and_rotate_y(prim: Usd.Prim) -> tuple[float, float, float, float]:
    """Return ``(tx, ty, tz, ry)`` resolved on ``prim``; missing ops read as 0."""
    (tx, ty, tz), (_, ry, _) = read_translate_rotate(prim)
    return tx, ty, tz, ry


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


def get_container_world_inverse(
    stage: Usd.Stage, container_prim_path: str,
) -> Gf.Matrix4d | None:
    """Return the inverse world transform of a container's wrapper Xform."""
    prim = stage.GetPrimAtPath(container_prim_path)
    if not prim or not prim.IsValid():
        return None

    wrapper = prim
    if prim.GetName() == SceneNamespace.ASSET_CHILD:
        parent = prim.GetParent()
        if parent and parent.IsValid():
            wrapper = parent

    xform_cache = UsdGeom.XformCache()
    return xform_cache.GetLocalToWorldTransform(wrapper).GetInverse()


def world_to_local_point(
    stage: Usd.Stage,
    container_prim_path: str,
    x: float, y: float, z: float,
) -> tuple[float, float, float] | None:
    """Convert a world-space point into a container's local frame."""
    inv = get_container_world_inverse(stage, container_prim_path)
    if inv is None:
        return None
    local = inv.Transform(Gf.Vec3d(x, y, z))
    return float(local[0]), float(local[1]), float(local[2])


def resolve_asset_position(
    mode: PositionMode,
    bounds: dict[str, dict[str, float]] | None,
    tx: float,
    ty: float,
    tz: float,
    *,
    has_explicit_y: bool,
    world_to_local_mat: Gf.Matrix4d | None = None,
    asset_mpu: float = 1.0,
) -> tuple[float, float, float]:
    """Resolve a translate value into asset-local meters.

    For ``ABSOLUTE`` mode with a *world_to_local_mat*, world-space input
    is converted to the asset's internal frame. For ``BOUNDS_OFFSET``
    mode, *bounds* is used to position relative to the bbox surfaces.
    """
    if mode is PositionMode.ABSOLUTE:
        if world_to_local_mat is None:
            return tx, ty, tz
        internal = world_to_local_mat.Transform(Gf.Vec3d(tx, ty, tz))
        return (
            internal[0] * asset_mpu,
            internal[1] * asset_mpu,
            internal[2] * asset_mpu,
        )

    if bounds is None:
        return tx, ty, tz

    return _apply_bounds_offsets(bounds, tx, ty, tz, has_explicit_y=has_explicit_y)


def resolve_asset_position_update(
    mode: PositionMode,
    bounds: dict[str, dict[str, float]] | None,
    given: PartialVec3,
    *,
    current_local: Vec3,
    current_world: Vec3,
    world_to_local_mat: Gf.Matrix4d | None,
    asset_mpu: float = 1.0,
) -> Vec3:
    """Resolve a new position for something already inside an asset; omitted axes stay put.

    ``absolute`` fills the omitted axes from the current world position before
    converting, since a rotated placement mixes axes. ``bounds_offset`` works
    per axis, so an omitted axis keeps its asset-local value (*current_local*).
    """
    if mode is PositionMode.ABSOLUTE:
        wx, wy, wz = (
            cur if g is None else g for g, cur in zip(given, current_world, strict=True)
        )
        return resolve_asset_position(
            mode, bounds, wx, wy, wz,
            has_explicit_y=True, world_to_local_mat=world_to_local_mat, asset_mpu=asset_mpu,
        )
    ox, oy, oz = (0.0 if g is None else g for g in given)
    resolved = resolve_asset_position(
        mode, bounds, ox, oy, oz,
        has_explicit_y=given[1] is not None,
        world_to_local_mat=world_to_local_mat, asset_mpu=asset_mpu,
    )
    x, y, z = (
        cur if g is None else r
        for g, r, cur in zip(given, resolved, current_local, strict=True)
    )
    return x, y, z


def _apply_bounds_offsets(
    bounds: dict[str, dict[str, float]],
    tx: float,
    ty: float,
    tz: float,
    *,
    has_explicit_y: bool,
) -> tuple[float, float, float]:
    """Convert offset-from-bounds values to absolute asset-local positions."""
    tx = bounds["center"]["x"] + tx
    tz = bounds["center"]["z"] + tz

    if has_explicit_y:
        if ty >= 0:
            ty = bounds["max"]["y"] + ty
        else:
            ty = bounds["min"]["y"] + ty
    else:
        ty = bounds["max"]["y"] + PositionDefaults.ABOVE_BOUNDS_METERS

    return tx, ty, tz


def gf_matrix_to_numpy(matrix: Gf.Matrix4d) -> FloatArray:
    """A Gf.Matrix4d as a (4, 4) float64 array (row-vector convention)."""
    return np.array(matrix, dtype=np.float64)
