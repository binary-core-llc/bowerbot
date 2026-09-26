# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Transforms — reading and writing xform ops, world ↔ local, and positions inside assets."""

from __future__ import annotations

import numpy as np
from pxr import Gf, Usd, UsdGeom

from bowerbot.schemas import PositionDefaults, PositionMode, SceneNamespace
from bowerbot.schemas.surface import FloatArray


def extract_position(prim: Usd.Prim) -> dict[str, float] | None:
    """Return the translate component of a prim's local transform."""
    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        return None
    t = xformable.GetLocalTransformation().ExtractTranslation()
    return {"x": round(t[0], 2), "y": round(t[1], 2), "z": round(t[2], 2)}


def read_translate_and_rotate_y(prim: Usd.Prim) -> tuple[float, float, float, float]:
    """Return ``(tx, ty, tz, ry)`` resolved on ``prim``; missing ops read as 0."""
    xformable = UsdGeom.Xformable(prim)
    tx = ty = tz = ry = 0.0
    for op in xformable.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            value = op.Get()
            if value is not None:
                tx, ty, tz = float(value[0]), float(value[1]), float(value[2])
        elif op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            value = op.Get()
            if value is not None:
                ry = float(value[1])
    return tx, ty, tz, ry


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
    """Update the first translate xform op on *prim*."""
    xformable = UsdGeom.Xformable(prim)
    for op in xformable.GetOrderedXformOps():
        if op.GetOpName() == "xformOp:translate":
            op.Set(value)
            return


def update_rotate_op(prim: Usd.Prim, value: Gf.Vec3f) -> None:
    """Update the first rotateXYZ xform op on *prim*."""
    xformable = UsdGeom.Xformable(prim)
    for op in xformable.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            op.Set(value)
            return


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
