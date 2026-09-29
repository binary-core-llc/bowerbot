# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Creating and updating scene cameras, and writing their Camera attributes."""

from __future__ import annotations

from pxr import Gf
from pxr import Usd
from pxr import UsdGeom

from bowerbot import schemas
from bowerbot.utils import usd


def create(stage: Usd.Stage, prim_path: str, camera: schemas.CameraParams) -> None:
    """Create a UsdGeom Camera prim in *stage* at *prim_path*."""
    refuse_unknown_attributes(camera.attributes)
    prim = UsdGeom.Camera.Define(stage, prim_path).GetPrim()
    write_attributes(stage, prim_path, camera.attributes)

    xformable = UsdGeom.Xformable(prim)
    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(Gf.Vec3d(*camera.translate))
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(*camera.rotate))


def update(
    stage: Usd.Stage,
    prim_path: str,
    *,
    translate: schemas.Vec3 | None = None,
    rotate: schemas.Vec3 | None = None,
) -> None:
    """Update a camera's translate / rotateXYZ ops."""
    prim = require(stage, prim_path)
    ops = {
        op.GetOpName(): op
        for op in UsdGeom.Xformable(prim).GetOrderedXformOps()
    }
    if translate is not None:
        _set_op(ops, "xformOp:translate", Gf.Vec3d(*translate), prim_path)
    if rotate is not None:
        _set_op(ops, "xformOp:rotateXYZ", Gf.Vec3f(*rotate), prim_path)


def require(stage: Usd.Stage, prim_path: str) -> Usd.Prim:
    """Return the Camera prim at *prim_path* or raise."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")
    if not prim.IsA(UsdGeom.Camera):
        raise ValueError(f"{prim_path} is not a Camera prim.")
    return prim


def write_attributes(
    stage: Usd.Stage, prim_path: str, attributes: dict,
) -> None:
    """Author Camera schema attributes by exact name."""
    for name, value in attributes.items():
        prim = stage.GetPrimAtPath(prim_path)
        attr = prim.GetAttribute(name)
        usd.attributes.set_prim_attribute(
            stage, prim_path, name, value, expected_type=attr.GetTypeName(),
        )


def refuse_unknown_attributes(attributes: dict) -> None:
    """Raise if any attribute name is not declared by the Camera schema."""
    valid = {str(n) for n in UsdGeom.Camera.GetSchemaAttributeNames(False)}
    unknown = sorted(name for name in attributes if name not in valid)
    if unknown:
        raise ValueError(
            f"Unknown Camera attribute(s) {unknown}. "
            f"Call list_camera_properties for the valid names.",
        )


# ── Helpers ──


def _set_op(
    ops: dict, op_name: str, value: object, prim_path: str,
) -> None:
    """Set one authored xform op, refusing layouts create_camera did not author."""
    op = ops.get(op_name)
    if op is None:
        raise ValueError(
            f"{prim_path} has no {op_name} op; adjust its xform ops with "
            f"set_prim_attribute instead.",
        )
    op.Set(value)
