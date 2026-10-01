# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""xformOps: read and write translate and rotate, bake transforms into geometry, rotation math."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from pxr import Gf
from pxr import Usd
from pxr import UsdGeom

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import usd

# ── Reading transforms ──


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


def extract_position(prim: Usd.Prim) -> dict[str, float] | None:
    """Return the translate component of a prim's local transform."""
    if not UsdGeom.Xformable(prim):
        return None
    x, y, z = local_translation(prim)
    return {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2)}


def local_translation(prim: Usd.Prim) -> schemas.Vec3:
    """Return a prim's local translation."""
    t = UsdGeom.Xformable(prim).GetLocalTransformation().ExtractTranslation()
    return (t[0], t[1], t[2])


def world_matrix(prim: Usd.Prim) -> Gf.Matrix4d:
    """Return a prim's local-to-world matrix."""
    return UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())


def world_translation(prim: Usd.Prim) -> schemas.Vec3:
    """Return where a prim's origin is in the world."""
    t = world_matrix(prim).ExtractTranslation()
    return (t[0], t[1], t[2])

# ── Writing transforms ──


def add_xform_op(
    xformable: UsdGeom.Xformable, attribute_name: str,
) -> UsdGeom.XformOp | None:
    """Return the xform op for *attribute_name*, adding to xformOpOrder if missing."""
    suffix = attribute_name[len("xformOp:"):]
    base, _, namespace = suffix.partition(":")
    spec = constants.TransformUsd.XFORM_OPS.get(base)
    if spec is None:
        return None
    op_type, value_type = spec
    current_order = xformable.GetXformOpOrderAttr().Get() or ()
    if attribute_name in current_order:
        attr = xformable.GetPrim().CreateAttribute(
            attribute_name, value_type, custom=False,
        )
        return UsdGeom.XformOp(attr)
    return xformable.AddXformOp(op_type, opSuffix=namespace or "")


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

# ── Baking a transform into geometry ──


def bake_root_transforms(geometry_file: Path) -> bool:
    """Bake the root prim's local transform into descendant geometry."""
    stage = Usd.Stage.Open(str(geometry_file))
    if stage is None:
        return False

    root_prim = stage.GetDefaultPrim()
    if not root_prim or not root_prim.IsValid():
        return False

    xformable = UsdGeom.Xformable(root_prim)
    if not xformable:
        return False

    matrix = xformable.GetLocalTransformation()
    if _matrix_is_identity(matrix):
        return False

    normal_matrix = matrix.GetInverse().GetTranspose()

    for prim in Usd.PrimRange(root_prim):
        pb = UsdGeom.PointBased(prim)
        if not pb:
            continue
        _bake_into_point_based(pb, matrix, normal_matrix)

    xformable.ClearXformOpOrder()
    for prop_name in list(root_prim.GetPropertyNames()):
        if prop_name.startswith("xformOp:") or prop_name == "xformOpOrder":
            root_prim.RemoveProperty(prop_name)

    stage.Save()
    return True


def root_transform_is_identity(geometry_file: Path) -> bool:
    """Return True if the file's defaultPrim has identity local transform."""
    stage = Usd.Stage.Open(str(geometry_file))
    if stage is None:
        return True
    prim = stage.GetDefaultPrim()
    if not prim or not prim.IsValid():
        return True
    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        return True
    return _matrix_is_identity(xformable.GetLocalTransformation())

# ── Rotation math ──


def quat_axis_angle(axis: schemas.FloatArray, angle: schemas.FloatArray) -> schemas.FloatArray:
    """Quaternions ``(w, x, y, z)`` rotating *angle* radians about unit *axis*."""
    axis = np.broadcast_to(axis, (angle.shape[0], 3))
    half = angle / 2.0
    return np.column_stack([np.cos(half), axis * np.sin(half)[:, None]])


def quat_mul(a: schemas.FloatArray, b: schemas.FloatArray) -> schemas.FloatArray:
    """Hamilton product ``a * b`` (apply *b* first, then *a*)."""
    w1, x1, y1, z1 = a.T
    w2, x2, y2, z2 = b.T
    return np.column_stack([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ])


def quat_rotate(q: schemas.FloatArray, v: schemas.FloatArray) -> schemas.FloatArray:
    """Rotate vectors *v* (n, 3) by quaternions *q* (n, 4)."""
    w = q[:, :1]
    u = q[:, 1:]
    t = 2.0 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


def quat_between(src: schemas.FloatArray, dst: schemas.FloatArray) -> schemas.FloatArray:
    """Shortest-arc quaternions turning unit *src* (3,) onto each unit *dst*."""
    d = dst @ src
    axis = np.cross(np.broadcast_to(src, dst.shape), dst)
    q = np.column_stack([1.0 + d, axis])
    opposite = d < -1.0 + 1e-9
    if opposite.any():
        perp = np.cross(src, [1.0, 0.0, 0.0])
        if np.linalg.norm(perp) < 1e-6:
            perp = np.cross(src, [0.0, 0.0, 1.0])
        perp /= np.linalg.norm(perp)
        q[opposite] = np.concatenate([[0.0], perp])
    return q / np.linalg.norm(q, axis=1)[:, None]


def quat_conj(q: schemas.FloatArray) -> schemas.FloatArray:
    """Inverse of unit quaternions ``(w, x, y, z)``."""
    return q * np.array([1.0, -1.0, -1.0, -1.0], dtype=np.float64)


def quat_heading(q: schemas.FloatArray, up: int) -> schemas.FloatArray:
    """The turn about up alone that keeps each rotation's heading (tilt removed)."""
    axes = usd.metrics.horizontal_axes(up)
    up_vec = usd.metrics.up_vector(up)
    angle = np.zeros(q.shape[0])
    todo = np.ones(q.shape[0], dtype=bool)
    for axis in axes:
        ref = np.zeros(3)
        ref[axis] = 1.0
        f = quat_rotate(q[todo], np.tile(ref, (int(todo.sum()), 1)))
        f[:, up] = 0.0
        # A vertical reference axis has no heading; try the other one.
        clear = np.linalg.norm(f, axis=1) > 1e-6
        rows = np.flatnonzero(todo)[clear]
        angle[rows] = np.arctan2(np.cross(ref, f[clear]) @ up_vec, f[clear] @ ref)
        todo[rows] = False
    return quat_axis_angle(up_vec, angle)


def quat_to_rotate_xyz(q: schemas.FloatArray) -> list[tuple[float, float, float]]:
    """Convert ``(w, x, y, z)`` quaternions to xformOp:rotateXYZ degrees."""
    out: list[tuple[float, float, float]] = []
    for w, x, y, z in q.tolist():
        rotation = Gf.Rotation(Gf.Quatd(w, Gf.Vec3d(x, y, z)))
        rz, ry, rx = rotation.Decompose(Gf.Vec3d.ZAxis(), Gf.Vec3d.YAxis(), Gf.Vec3d.XAxis())
        out.append(_smallest_rotate_xyz(rx, ry, rz))
    return out


def rotate_xyz_rotation(value: Any) -> Gf.Rotation:
    """Gf.Rotation equal to an xformOp:rotateXYZ value (X applied first)."""
    rx, ry, rz = (float(v) for v in (value or (0.0, 0.0, 0.0)))
    return (
        Gf.Rotation(Gf.Vec3d.XAxis(), rx)
        * Gf.Rotation(Gf.Vec3d.YAxis(), ry)
        * Gf.Rotation(Gf.Vec3d.ZAxis(), rz)
    )


def gf_matrix_to_numpy(matrix: Gf.Matrix4d) -> schemas.FloatArray:
    """A Gf.Matrix4d as a (4, 4) float64 array (row-vector convention)."""
    return np.array(matrix, dtype=np.float64)


def transform_points(points: schemas.FloatArray, matrix: schemas.FloatArray) -> schemas.FloatArray:
    """Apply a (4, 4) row-vector matrix to an (n, 3) array of points."""
    return points @ matrix[:3, :3] + matrix[3, :3]


def matrix_rotation_quat(matrix: Gf.Matrix4d) -> schemas.FloatArray:
    """The rotation of *matrix* as a ``(w, x, y, z)`` quaternion, scale and shear removed."""
    rotation = matrix.RemoveScaleShear().ExtractRotationQuat()
    return np.array([rotation.GetReal(), *rotation.GetImaginary()])

# ── Helpers ──


def _matrix_is_identity(matrix: Gf.Matrix4d, epsilon: float = 1e-5) -> bool:
    """Return True if *matrix* is the identity matrix within *epsilon*."""
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            if abs(matrix[i, j] - expected) > epsilon:
                return False
    return True


def _bake_into_point_based(
    pb: UsdGeom.PointBased,
    matrix: Gf.Matrix4d,
    normal_matrix: Gf.Matrix4d,
) -> None:
    """Apply *matrix* to a PointBased prim's points / normals / extent."""
    points_attr = pb.GetPointsAttr()
    points = points_attr.Get()
    if points is None or len(points) == 0:
        return

    new_points = [matrix.Transform(p) for p in points]
    points_attr.Set(new_points)

    normals_attr = pb.GetNormalsAttr()
    normals = normals_attr.Get()
    if normals is not None and len(normals) > 0:
        new_normals = [
            normal_matrix.TransformDir(n).GetNormalized() for n in normals
        ]
        normals_attr.Set(new_normals)

    extent_attr = pb.GetExtentAttr()
    if extent_attr.HasAuthoredValue():
        xs = [p[0] for p in new_points]
        ys = [p[1] for p in new_points]
        zs = [p[2] for p in new_points]
        extent_attr.Set([
            Gf.Vec3f(min(xs), min(ys), min(zs)),
            Gf.Vec3f(max(xs), max(ys), max(zs)),
        ])


def _smallest_rotate_xyz(rx: float, ry: float, rz: float) -> tuple[float, float, float]:
    """Smaller of the two equivalent rotateXYZ triples, so a yaw stays (0, yaw, 0)."""
    def wrap(angle: float) -> float:
        wrapped = (angle + 180.0) % 360.0 - 180.0
        return 0.0 if abs(wrapped) < 1e-6 else round(wrapped, 4)

    first = (wrap(rx), wrap(ry), wrap(rz))
    second = (wrap(rx + 180.0), wrap(180.0 - ry), wrap(rz + 180.0))
    return min(first, second, key=lambda angles: sum(abs(a) for a in angles))
