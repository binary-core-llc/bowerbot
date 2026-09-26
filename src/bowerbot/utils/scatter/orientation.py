# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter orientation — quaternions, headings, and alignment to the surface."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pxr import Gf

from bowerbot.schemas import ScatterAlign
from bowerbot.schemas.surface import FloatArray
from bowerbot.utils.core.metrics import horizontal_axes, up_vector


def quat_axis_angle(axis: FloatArray, angle: FloatArray) -> FloatArray:
    """Quaternions ``(w, x, y, z)`` rotating *angle* radians about unit *axis*."""
    axis = np.broadcast_to(axis, (angle.shape[0], 3))
    half = angle / 2.0
    return np.column_stack([np.cos(half), axis * np.sin(half)[:, None]])


def quat_mul(a: FloatArray, b: FloatArray) -> FloatArray:
    """Hamilton product ``a * b`` (apply *b* first, then *a*)."""
    w1, x1, y1, z1 = a.T
    w2, x2, y2, z2 = b.T
    return np.column_stack([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ])


def quat_rotate(q: FloatArray, v: FloatArray) -> FloatArray:
    """Rotate vectors *v* (n, 3) by quaternions *q* (n, 4)."""
    w = q[:, :1]
    u = q[:, 1:]
    t = 2.0 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


def quat_between(src: FloatArray, dst: FloatArray) -> FloatArray:
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


def quat_conj(q: FloatArray) -> FloatArray:
    """Inverse of unit quaternions ``(w, x, y, z)``."""
    return q * np.array([1.0, -1.0, -1.0, -1.0], dtype=np.float64)


def quat_heading(q: FloatArray, up: int) -> FloatArray:
    """The turn about up alone that keeps each rotation's heading (tilt removed)."""
    axes = horizontal_axes(up)
    up_vec = up_vector(up)
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


def random_headings(
    rng: np.random.Generator, n: int, up: int, *, random_yaw: bool,
) -> FloatArray:
    """Yaw-only rotations about up: uniformly random, or none."""
    yaw = rng.random(n) * 2.0 * math.pi if random_yaw else np.zeros(n)
    return quat_axis_angle(up_vector(up), yaw)


def surface_orientations(
    rng: np.random.Generator,
    headings: FloatArray,
    normals: FloatArray,
    up: int,
    *,
    align: ScatterAlign,
    tilt_jitter_degrees: float,
) -> FloatArray:
    """*headings*, optional random tilt, then (optionally) align to normals."""
    n = int(normals.shape[0])
    up_vec = up_vector(up)
    q = headings
    if tilt_jitter_degrees > 0:
        axes = horizontal_axes(up)
        phi = rng.random(n) * 2.0 * math.pi
        axis = np.zeros((n, 3))
        axis[:, axes[0]] = np.cos(phi)
        axis[:, axes[1]] = np.sin(phi)
        tilt = rng.random(n) * math.radians(tilt_jitter_degrees)
        q = quat_mul(quat_axis_angle(axis, tilt), q)
    if align is ScatterAlign.SURFACE:
        q = quat_mul(quat_between(up_vec, normals), q)
    return q


def quat_to_rotate_xyz(q: FloatArray) -> list[tuple[float, float, float]]:
    """Convert ``(w, x, y, z)`` quaternions to xformOp:rotateXYZ degrees."""
    out: list[tuple[float, float, float]] = []
    for w, x, y, z in q.tolist():
        rotation = Gf.Rotation(Gf.Quatd(w, Gf.Vec3d(x, y, z)))
        rz, ry, rx = rotation.Decompose(Gf.Vec3d.ZAxis(), Gf.Vec3d.YAxis(), Gf.Vec3d.XAxis())
        out.append(_smallest_rotate_xyz(rx, ry, rz))
    return out


def _smallest_rotate_xyz(rx: float, ry: float, rz: float) -> tuple[float, float, float]:
    """Smaller of the two equivalent rotateXYZ triples, so a yaw stays (0, yaw, 0)."""
    def wrap(angle: float) -> float:
        wrapped = (angle + 180.0) % 360.0 - 180.0
        return 0.0 if abs(wrapped) < 1e-6 else round(wrapped, 4)

    first = (wrap(rx), wrap(ry), wrap(rz))
    second = (wrap(rx + 180.0), wrap(180.0 - ry), wrap(rz + 180.0))
    return min(first, second, key=lambda angles: sum(abs(a) for a in angles))


def rotate_xyz_rotation(value: Any) -> Gf.Rotation:
    """Gf.Rotation equal to an xformOp:rotateXYZ value (X applied first)."""
    rx, ry, rz = (float(v) for v in (value or (0.0, 0.0, 0.0)))
    return (
        Gf.Rotation(Gf.Vec3d.XAxis(), rx)
        * Gf.Rotation(Gf.Vec3d.YAxis(), ry)
        * Gf.Rotation(Gf.Vec3d.ZAxis(), rz)
    )
