# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Camera utils — author and aim scene-level UsdGeom Camera prims."""

from __future__ import annotations

from typing import Any

from pxr import Gf, Usd, UsdGeom

from bowerbot.schemas import CameraParams, CameraSchemaInfo, CameraTuning
from bowerbot.schemas.transforms import Vec3
from bowerbot.utils.core.attributes import set_prim_attribute
from bowerbot.utils.core.metrics import axis_index, up_vector
from bowerbot.utils.core.schema_registry import schema_properties
from bowerbot.utils.core.transforms import extract_position


def list_camera_properties() -> CameraSchemaInfo:
    """Live schema-registry view of every attribute the Camera prim declares."""
    prim_def = Usd.SchemaRegistry().FindConcretePrimDefinition("Camera")
    if prim_def is None:
        raise ValueError(
            "USD schema registry does not know Camera. "
            "USD build is missing UsdGeom.",
        )
    names = [str(n) for n in UsdGeom.Camera.GetSchemaAttributeNames(False)]
    return CameraSchemaInfo(properties=schema_properties(prim_def, names))


def look_at_rotation(eye: Vec3, target: Vec3, up_axis: str) -> Vec3:
    """Return rotateXYZ degrees aiming a camera's -Z axis from *eye* at *target*."""
    eye_v, target_v = Gf.Vec3d(*eye), Gf.Vec3d(*target)
    if (target_v - eye_v).GetLength() == 0:
        raise ValueError("look_at target must differ from the camera position.")
    forward = (target_v - eye_v).GetNormalized()
    up = Gf.Vec3d(*up_vector(axis_index(up_axis)))
    if abs(Gf.Dot(forward, up)) > CameraTuning.UP_ALIGNED_DOT:
        up = Gf.Vec3d(*up_vector(axis_index("Y" if up_axis == "Z" else "Z")))
    view = Gf.Matrix4d().SetLookAt(eye_v, target_v, up)
    rz, ry, rx = view.GetInverse().ExtractRotation().Decompose(
        Gf.Vec3d.ZAxis(), Gf.Vec3d.YAxis(), Gf.Vec3d.XAxis(),
    )
    return (rx, ry, rz)


def create_camera(stage: Usd.Stage, prim_path: str, camera: CameraParams) -> None:
    """Create a UsdGeom Camera prim in *stage* at *prim_path*."""
    refuse_unknown_camera_attributes(camera.attributes)
    prim = UsdGeom.Camera.Define(stage, prim_path).GetPrim()
    write_camera_attributes(stage, prim_path, camera.attributes)

    xformable = UsdGeom.Xformable(prim)
    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(Gf.Vec3d(*camera.translate))
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(*camera.rotate))


def update_camera(
    stage: Usd.Stage,
    prim_path: str,
    *,
    translate: Vec3 | None = None,
    rotate: Vec3 | None = None,
) -> None:
    """Update a camera's translate / rotateXYZ ops."""
    prim = require_camera(stage, prim_path)
    ops = {
        op.GetOpName(): op
        for op in UsdGeom.Xformable(prim).GetOrderedXformOps()
    }
    if translate is not None:
        _set_op(ops, "xformOp:translate", Gf.Vec3d(*translate), prim_path)
    if rotate is not None:
        _set_op(ops, "xformOp:rotateXYZ", Gf.Vec3f(*rotate), prim_path)


def _set_op(
    ops: dict[str, UsdGeom.XformOp], op_name: str, value: object, prim_path: str,
) -> None:
    """Set one authored xform op, refusing layouts create_camera did not author."""
    op = ops.get(op_name)
    if op is None:
        raise ValueError(
            f"{prim_path} has no {op_name} op; adjust its xform ops with "
            f"set_prim_attribute instead.",
        )
    op.Set(value)


def require_camera(stage: Usd.Stage, prim_path: str) -> Usd.Prim:
    """Return the Camera prim at *prim_path* or raise."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")
    if not prim.IsA(UsdGeom.Camera):
        raise ValueError(f"{prim_path} is not a Camera prim.")
    return prim


def camera_translate(prim: Usd.Prim) -> Vec3:
    """Return the camera's local translation."""
    t = UsdGeom.Xformable(prim).GetLocalTransformation().ExtractTranslation()
    return (t[0], t[1], t[2])


def write_camera_attributes(
    stage: Usd.Stage, prim_path: str, attributes: dict[str, Any],
) -> None:
    """Author Camera schema attributes by exact name."""
    for name, value in attributes.items():
        prim = stage.GetPrimAtPath(prim_path)
        attr = prim.GetAttribute(name)
        set_prim_attribute(
            stage, prim_path, name, value, expected_type=attr.GetTypeName(),
        )


def refuse_unknown_camera_attributes(attributes: dict[str, Any]) -> None:
    """Raise if any attribute name is not declared by the Camera schema."""
    valid = {str(n) for n in UsdGeom.Camera.GetSchemaAttributeNames(False)}
    unknown = sorted(name for name in attributes if name not in valid)
    if unknown:
        raise ValueError(
            f"Unknown Camera attribute(s) {unknown}. "
            f"Call list_camera_properties for the valid names.",
        )


def format_camera_prim(prim: Usd.Prim) -> dict[str, Any]:
    """Format a Camera prim for ``list_prims``."""
    camera = UsdGeom.Camera(prim)
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "camera",
        "type": str(prim.GetTypeName()),
        "projection": str(camera.GetProjectionAttr().Get()),
        "focal_length": float(camera.GetFocalLengthAttr().Get()),
        "position": extract_position(prim),
    }
