# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter paths — polylines, circles and curves: stations, tangents and facing."""

from __future__ import annotations

import math

import numpy as np
from pxr import Usd, UsdGeom

from bowerbot.schemas import (
    ScatterPathFacing,
    ScatterPathParams,
    ScatterPathSide,
    ScatterPrototype,
    ScatterRules,
    ScatterTuning,
    SurfaceIndex,
)
from bowerbot.schemas.surface import FloatArray, IntArray
from bowerbot.utils import surface_utils
from bowerbot.utils.core.metrics import horizontal_axes, up_vector
from bowerbot.utils.core.transforms import gf_matrix_to_numpy


def build_path(
    stage: Usd.Stage, path: ScatterPathParams, up: int,
) -> tuple[FloatArray, bool, FloatArray]:
    """Return ``(points, closed, centre)`` for the requested path in world space."""
    if path.points is not None:
        points = np.asarray(path.points, dtype=np.float64)
        return points, path.closed, points.mean(axis=0)
    if path.circle is not None:
        circle = path.circle
        center = np.asarray(circle.center, dtype=np.float64)
        axes = list(horizontal_axes(up))
        angles = math.radians(circle.start_angle_degrees) + np.linspace(
            0.0, 2.0 * math.pi, ScatterTuning.PATH_SEGMENTS, endpoint=False,
        )
        points = np.repeat(center[None, :], ScatterTuning.PATH_SEGMENTS, axis=0)
        points[:, axes[0]] += circle.radius * np.cos(angles)
        points[:, axes[1]] += circle.radius * np.sin(angles)
        return points, True, center
    if path.curve_prim is None:
        msg = "a path needs points, a circle or a curve_prim."
        raise ValueError(msg)
    return _curve_points(stage, path.curve_prim)


def path_stations(
    points: FloatArray,
    closed: bool,
    up: int,
    *,
    count: int | None,
    spacing: float,
    start_offset: float,
) -> tuple[FloatArray, FloatArray, float]:
    """Arc-length stations along the path, with the chord half-step and path length."""
    length = plan_length(points, closed, up)
    if length <= 0:
        raise ValueError("the path has zero length in plan view.")
    if count is not None:
        if closed:
            stations = (start_offset + np.arange(count) * length / count) % length
            step = length / count
        elif count == 1:
            stations = np.array([min(start_offset, length) if start_offset else length / 2])
            step = length
        else:
            stations = np.linspace(min(start_offset, length), length, count)
            step = (length - min(start_offset, length)) / (count - 1) or length
    elif closed:
        n = max(1, int(round(length / spacing)))
        stations = (start_offset + np.arange(n) * length / n) % length
        step = length / n
    else:
        stations = np.arange(start_offset, length + 1e-9, spacing)
        step = spacing
    if stations.size > ScatterRules.MAX_INSTANCES:
        msg = f"the path would create {stations.size:,} stations; increase spacing."
        raise ValueError(msg)
    return stations, np.full(stations.size, step / 2.0), length


def sample_path(
    points: FloatArray, closed: bool, up: int, stations: FloatArray,
) -> FloatArray:
    """Interpolate 3D positions at plan arc-length *stations*."""
    pts = np.vstack([points, points[:1]]) if closed else points
    axes = list(horizontal_axes(up))
    seg = np.diff(pts[:, axes], axis=0)
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = cum[-1]
    s = np.mod(stations, total) if closed else np.clip(stations, 0.0, total)
    k = np.clip(np.searchsorted(cum, s, side="right") - 1, 0, seg_len.size - 1)
    t = np.where(seg_len[k] > 0, (s - cum[k]) / np.where(seg_len[k] > 0, seg_len[k], 1.0), 0.0)
    return pts[k] + t[:, None] * (pts[k + 1] - pts[k])


def path_tangents(
    points: FloatArray, closed: bool, up: int, stations: FloatArray, half: FloatArray,
) -> FloatArray:
    """Unit plan-view tangents from the chord across each station."""
    ahead = sample_path(points, closed, up, stations + half)
    behind = sample_path(points, closed, up, stations - half)
    chord = ahead - behind
    chord[:, up] = 0.0
    norm = np.linalg.norm(chord, axis=1)
    fallback = norm < 1e-12
    if fallback.any():
        chord[fallback] = _segment_direction(points, closed, up, stations[fallback])
        norm = np.linalg.norm(chord, axis=1)
    return chord / norm[:, None]


def prototype_length(proto: ScatterPrototype, up: int, facing: ScatterPathFacing) -> float:
    """Extent a prototype occupies along the path for automatic spacing."""
    side_axis, front_axis = _side_and_front_axes(up)
    extent = np.subtract(proto.bounds_max, proto.bounds_min)
    if facing is ScatterPathFacing.TANGENT:
        return float(max(extent[side_axis], extent[front_axis]))
    return float(extent[side_axis])


def facing_yaw(
    facing: ScatterPathFacing,
    *,
    rng: np.random.Generator,
    up: int,
    positions: FloatArray,
    tangents: FloatArray,
    side_sign: FloatArray,
    center: FloatArray,
    direction_degrees: float | None,
    prototypes: list[ScatterPrototype],
    proto_idx: IntArray,
) -> FloatArray:
    """Yaw turning each prototype's front (+Z in Y-up, -Y in Z-up) toward *facing*."""
    n = int(positions.shape[0])
    up_vec = up_vector(up)
    front = _front_vector(up)
    if facing is ScatterPathFacing.RANDOM:
        return rng.random(n) * 2.0 * math.pi
    if facing is ScatterPathFacing.TANGENT:
        side_axis, front_axis = _side_and_front_axes(up)
        long_is_side = np.array([
            np.subtract(p.bounds_max, p.bounds_min)[side_axis]
            >= np.subtract(p.bounds_max, p.bounds_min)[front_axis]
            for p in prototypes
        ])[proto_idx]
        side = np.zeros(3)
        side[side_axis] = 1.0
        ref = np.where(long_is_side[:, None], side, front)
        return _signed_angle(ref, tangents, up_vec)
    if facing is ScatterPathFacing.PATH:
        left = np.cross(up_vec, tangents)
        toward = -left * side_sign[:, None]
        toward = np.where((side_sign == 0)[:, None], tangents, toward)
        return _signed_angle(np.broadcast_to(front, toward.shape), toward, up_vec)
    if facing in (ScatterPathFacing.CENTER, ScatterPathFacing.OUTWARD):
        target = center[None, :] - positions
        target[:, up] = 0.0
        norm = np.linalg.norm(target, axis=1)
        target = np.where(norm[:, None] > 1e-12, target / np.maximum(norm, 1e-12)[:, None],
                          tangents)
        if facing is ScatterPathFacing.OUTWARD:
            target = -target
        return _signed_angle(np.broadcast_to(front, target.shape), target, up_vec)
    axes = list(horizontal_axes(up))
    theta = math.radians(direction_degrees or 0.0)
    fixed = np.zeros(3)
    fixed[axes[0]] = math.cos(theta)
    fixed[axes[1]] = math.sin(theta)
    return _signed_angle(front[None, :], fixed[None, :], up_vec).repeat(n)


def side_signs(sides: ScatterPathSide) -> list[int]:
    """Lateral offset signs (+1 left, -1 right, 0 on the line) for *sides*."""
    return {
        ScatterPathSide.CENTER: [0],
        ScatterPathSide.LEFT: [1],
        ScatterPathSide.RIGHT: [-1],
        ScatterPathSide.BOTH: [1, -1],
    }[sides]


def path_pitch(
    index: SurfaceIndex,
    points: FloatArray,
    closed: bool,
    up: int,
    stations: FloatArray,
    half: FloatArray,
    station_idx: IntArray,
    lateral: FloatArray,
) -> FloatArray:
    """Pitch (radians) of the surface along the path across each instance."""
    ahead = sample_path(points, closed, up, stations + half)[station_idx] + lateral
    behind = sample_path(points, closed, up, stations - half)[station_idx] + lateral
    hit_a, h_a, _ = surface_utils.surface_under(
        index, ahead, mode="nearest", reference=ahead[:, up].copy(),
    )
    hit_b, h_b, _ = surface_utils.surface_under(
        index, behind, mode="nearest", reference=behind[:, up].copy(),
    )
    axes = list(horizontal_axes(up))
    run = np.linalg.norm((ahead - behind)[:, axes], axis=1)
    rise = np.where(hit_a & hit_b, h_a - h_b, 0.0)
    return np.arctan2(rise, np.maximum(run, 1e-9))


def _curve_points(stage: Usd.Stage, prim_path: str) -> tuple[FloatArray, bool, FloatArray]:
    """World-space control points of the first curve on a BasisCurves prim."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid() or not prim.IsA(UsdGeom.BasisCurves):
        msg = f"curve_prim {prim_path} is not a BasisCurves prim."
        raise ValueError(msg)
    curves = UsdGeom.BasisCurves(prim)
    points = np.asarray(curves.GetPointsAttr().Get() or [], dtype=np.float64)
    counts = curves.GetCurveVertexCountsAttr().Get() or [len(points)]
    points = points[: int(counts[0])]
    if points.shape[0] < 2:
        msg = f"curve_prim {prim_path} has fewer than 2 points."
        raise ValueError(msg)
    world = gf_matrix_to_numpy(
        UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()),
    )
    points = points @ world[:3, :3] + world[3, :3]
    closed = curves.GetWrapAttr().Get() == UsdGeom.Tokens.periodic
    return points, closed, points.mean(axis=0)


def plan_length(points: FloatArray, closed: bool, up: int) -> float:
    pts = np.vstack([points, points[:1]]) if closed else points
    axes = list(horizontal_axes(up))
    seg = np.diff(pts[:, axes], axis=0)
    return float(np.hypot(seg[:, 0], seg[:, 1]).sum())


def _segment_direction(
    points: FloatArray, closed: bool, up: int, stations: FloatArray,
) -> FloatArray:
    """Direction of the path segment containing each station (tangent fallback)."""
    pts = np.vstack([points, points[:1]]) if closed else points
    axes = list(horizontal_axes(up))
    seg = np.diff(pts, axis=0)
    seg[:, up] = 0.0
    seg_len = np.hypot(*seg[:, axes].T)
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    s = np.mod(stations, cum[-1]) if closed else np.clip(stations, 0.0, cum[-1])
    k = np.clip(np.searchsorted(cum, s, side="right") - 1, 0, seg.shape[0] - 1)
    return seg[k]


def _side_and_front_axes(up: int) -> tuple[int, int]:
    """Prototype side axis (X) and front axis (Z for Y-up, Y for Z-up)."""
    return 0, (2 if up == 1 else 1)


def _front_vector(up: int) -> FloatArray:
    """Prototype front direction: +Z in Y-up scenes, -Y in Z-up scenes."""
    return np.array([0.0, 0.0, 1.0]) if up == 1 else np.array([0.0, -1.0, 0.0])


def _signed_angle(src: FloatArray, dst: FloatArray, axis: FloatArray) -> FloatArray:
    """Signed angle (radians) about *axis* turning each *src* onto each *dst*."""
    src = np.broadcast_to(src, dst.shape)
    cross = np.cross(src, dst)
    return np.arctan2(cross @ axis, (src * dst).sum(axis=1))
