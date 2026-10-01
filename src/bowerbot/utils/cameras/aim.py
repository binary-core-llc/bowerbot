# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Aiming a camera: the rotation that points it at a target."""

from __future__ import annotations

from pxr import Gf

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import usd


def look_at_rotation(eye: schemas.Vec3, target: schemas.Vec3, up_axis: str) -> schemas.Vec3:
    """Return rotateXYZ degrees aiming a camera's -Z axis from *eye* at *target*."""
    eye_v, target_v = Gf.Vec3d(*eye), Gf.Vec3d(*target)
    if (target_v - eye_v).GetLength() == 0:
        raise ValueError("look_at target must differ from the camera position.")
    forward = (target_v - eye_v).GetNormalized()
    up = _axis_vector(up_axis)
    if abs(Gf.Dot(forward, up)) > constants.CameraTuning.UP_ALIGNED_DOT:
        up = _axis_vector("Y" if up_axis == "Z" else "Z")
    view = Gf.Matrix4d().SetLookAt(eye_v, target_v, up)
    rz, ry, rx = view.GetInverse().ExtractRotation().Decompose(
        Gf.Vec3d.ZAxis(), Gf.Vec3d.YAxis(), Gf.Vec3d.XAxis(),
    )
    return (rx, ry, rz)


def _axis_vector(up_axis: str) -> Gf.Vec3d:
    """The world unit vector along the axis named *up_axis*."""
    return Gf.Vec3d(*usd.metrics.up_vector(usd.metrics.axis_index(up_axis)).tolist())
