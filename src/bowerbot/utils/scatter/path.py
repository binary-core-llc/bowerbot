# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""scatter_along_path: the path, its stations and tangents, facing, and estimates."""

from __future__ import annotations

import math

import numpy as np
from pxr import Usd
from pxr import UsdGeom

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import scatter
from bowerbot.utils import usd


def generate(
    stage: Usd.Stage,
    path: schemas.ScatterPathParams,
    pose: schemas.ScatterPoseParams,
    *,
    prototypes: list[schemas.ScatterPrototype],
    index: schemas.SurfaceIndex | None,
    up: int,
    seed: int,
) -> tuple[schemas.ScatterInstanceSet, list[str]]:
    """Compute every instance of a scatter_along_path call in world space."""
    rng = np.random.default_rng(seed)
    up_vec = usd.metrics.up_vector(up)
    points, closed, center = build(stage, path, up)
    spacing = path.spacing
    if path.count is None and spacing is None:
        mean_scale = sum(pose.scale_range) / 2.0
        spacing = max(prototype_length(p, up, path.facing) for p in prototypes) * mean_scale
        spacing += path.gap
        if spacing <= 0:
            raise ValueError("could not derive spacing from the assets; pass 'spacing'.")
    stations, half, _ = arc_stations(
        points, closed, up, count=path.count, spacing=spacing or 1.0,
        start_offset=path.start_offset,
    )
    tangents = station_tangents(points, closed, up, stations, half)
    signs = np.array(side_signs(path.sides), dtype=np.float64)
    per_station = signs.size
    station_idx = np.repeat(np.arange(stations.size), per_station)
    sign = np.tile(signs, stations.size)
    tangent = tangents[station_idx]
    lateral = np.cross(up_vec, tangent) * (sign * path.offset)[:, None]
    contacts = sample(points, closed, up, stations)[station_idx] + lateral

    n = contacts.shape[0]
    weights = [proto.weight for proto in prototypes]
    proto_idx = scatter.instances.pick_prototypes(rng, weights, n, path.asset_order)
    scales = scatter.instances.random_scales(rng, pose.scale_range, n)
    normals = np.repeat(up_vec[None, :], n, axis=0)
    warnings: list[str] = []
    if index is not None:
        hit, heights, tris = usd.surface.surface_under(
            index, contacts, mode="nearest", reference=contacts[:, up].copy(),
        )
        contacts[hit, up] = heights[hit]
        normals[hit] = index.triangles.normals[tris[hit]]
        if (~hit).any():
            warnings.append(
                f"{int((~hit).sum())} of {n} instance(s) have no surface under them "
                "and keep the path height.",
            )

    yaw = facing_yaw(
        path.facing, rng=rng, up=up, positions=contacts, tangents=tangent,
        side_sign=sign, center=center, direction_degrees=path.direction_degrees,
        prototypes=prototypes, proto_idx=proto_idx,
    ) + math.radians(path.yaw_offset_degrees)
    headings = usd.transforms.quat_axis_angle(up_vec, yaw)
    orientations = headings
    settle = np.full(n, pose.align is schemas.ScatterAlign.UP)
    if path.follow_slope and index is not None:
        pitch = _path_pitch(index, points, closed, up, stations, half, station_idx, lateral)
        axis = np.cross(tangent, up_vec)
        orientations = usd.transforms.quat_mul(
            usd.transforms.quat_axis_angle(axis, pitch), orientations,
        )
    if pose.align is schemas.ScatterAlign.SURFACE:
        if index is not None:
            base_min, base_max = scatter.instances.prototype_bases(prototypes, proto_idx)
            normals, settle = scatter.instances.ground_normals(
                index, contacts, headings, scales, base_min, base_max, normals, up,
            )
        orientations = usd.transforms.quat_mul(
            usd.transforms.quat_between(up_vec, normals), orientations,
        )
    if path.follow_slope:
        settle[:] = False
    positions = scatter.instances.rest_positions(
        contacts, orientations, scales, prototypes, proto_idx, up,
        embed=pose.embed, settle=settle, index=index,
    )
    return schemas.ScatterInstanceSet(
        proto_indices=proto_idx, positions=positions,
        orientations=orientations, scales=scales,
    ), warnings


def estimate(
    stage: Usd.Stage, path: schemas.ScatterPathParams, up: int,
) -> tuple[int | None, float]:
    """Return ``(instances or None when spacing is automatic, path_length)``."""
    points, closed, _ = build(stage, path, up)
    length = _plan_length(points, closed, up)
    if path.count is None and path.spacing is None:
        return None, length
    stations, _, _ = arc_stations(
        points, closed, up, count=path.count, spacing=path.spacing or 1.0,
        start_offset=path.start_offset,
    )
    return int(stations.size) * len(side_signs(path.sides)), length


def build(
    stage: Usd.Stage, path: schemas.ScatterPathParams, up: int,
) -> tuple[schemas.FloatArray, bool, schemas.FloatArray]:
    """Return ``(points, closed, centre)`` for the requested path in world space."""
    if path.points is not None:
        points = np.asarray(path.points, dtype=np.float64)
        return points, path.closed, points.mean(axis=0)
    if path.circle is not None:
        circle = path.circle
        center = np.asarray(circle.center, dtype=np.float64)
        axes = list(usd.metrics.horizontal_axes(up))
        angles = math.radians(circle.start_angle_degrees) + np.linspace(
            0.0, 2.0 * math.pi, constants.ScatterTuning.PATH_SEGMENTS, endpoint=False,
        )
        points = np.repeat(center[None, :], constants.ScatterTuning.PATH_SEGMENTS, axis=0)
        points[:, axes[0]] += circle.radius * np.cos(angles)
        points[:, axes[1]] += circle.radius * np.sin(angles)
        return points, True, center
    if path.curve_prim is None:
        msg = "a path needs points, a circle or a curve_prim."
        raise ValueError(msg)
    return _curve_points(stage, path.curve_prim)


def arc_stations(
    points: schemas.FloatArray,
    closed: bool,
    up: int,
    *,
    count: int | None,
    spacing: float,
    start_offset: float,
) -> tuple[schemas.FloatArray, schemas.FloatArray, float]:
    """Arc-length stations along the path, with the chord half-step and path length."""
    length = _plan_length(points, closed, up)
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
    if stations.size > constants.ScatterRules.MAX_INSTANCES:
        msg = f"the path would create {stations.size:,} stations; increase spacing."
        raise ValueError(msg)
    return stations, np.full(stations.size, step / 2.0), length


def sample(
    points: schemas.FloatArray, closed: bool, up: int, stations: schemas.FloatArray,
) -> schemas.FloatArray:
    """Interpolate 3D positions at plan arc-length *stations*."""
    pts = np.vstack([points, points[:1]]) if closed else points
    axes = list(usd.metrics.horizontal_axes(up))
    seg = np.diff(pts[:, axes], axis=0)
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = cum[-1]
    s = np.mod(stations, total) if closed else np.clip(stations, 0.0, total)
    k = np.clip(np.searchsorted(cum, s, side="right") - 1, 0, seg_len.size - 1)
    t = np.where(seg_len[k] > 0, (s - cum[k]) / np.where(seg_len[k] > 0, seg_len[k], 1.0), 0.0)
    return pts[k] + t[:, None] * (pts[k + 1] - pts[k])


def station_tangents(
    points: schemas.FloatArray,
    closed: bool,
    up: int,
    stations: schemas.FloatArray,
    half: schemas.FloatArray,
) -> schemas.FloatArray:
    """Unit plan-view tangents from the chord across each station."""
    ahead = sample(points, closed, up, stations + half)
    behind = sample(points, closed, up, stations - half)
    chord = ahead - behind
    chord[:, up] = 0.0
    norm = np.linalg.norm(chord, axis=1)
    fallback = norm < 1e-12
    if fallback.any():
        chord[fallback] = _segment_direction(points, closed, up, stations[fallback])
        norm = np.linalg.norm(chord, axis=1)
    return chord / norm[:, None]


def prototype_length(
    proto: schemas.ScatterPrototype, up: int, facing: schemas.ScatterPathFacing,
) -> float:
    """Extent a prototype occupies along the path for automatic spacing."""
    side_axis, front_axis = _side_and_front_axes(up)
    extent = np.subtract(proto.bounds_max, proto.bounds_min)
    if facing is schemas.ScatterPathFacing.TANGENT:
        return float(max(extent[side_axis], extent[front_axis]))
    return float(extent[side_axis])


def facing_yaw(
    facing: schemas.ScatterPathFacing,
    *,
    rng: np.random.Generator,
    up: int,
    positions: schemas.FloatArray,
    tangents: schemas.FloatArray,
    side_sign: schemas.FloatArray,
    center: schemas.FloatArray,
    direction_degrees: float | None,
    prototypes: list[schemas.ScatterPrototype],
    proto_idx: schemas.IntArray,
) -> schemas.FloatArray:
    """Yaw turning each prototype's front (+Z in Y-up, -Y in Z-up) toward *facing*."""
    n = int(positions.shape[0])
    up_vec = usd.metrics.up_vector(up)
    front = _front_vector(up)
    if facing is schemas.ScatterPathFacing.RANDOM:
        return rng.random(n) * 2.0 * math.pi
    if facing is schemas.ScatterPathFacing.TANGENT:
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
    if facing is schemas.ScatterPathFacing.PATH:
        left = np.cross(up_vec, tangents)
        toward = -left * side_sign[:, None]
        toward = np.where((side_sign == 0)[:, None], tangents, toward)
        return _signed_angle(np.broadcast_to(front, toward.shape), toward, up_vec)
    if facing in (schemas.ScatterPathFacing.CENTER, schemas.ScatterPathFacing.OUTWARD):
        target = center[None, :] - positions
        target[:, up] = 0.0
        norm = np.linalg.norm(target, axis=1)
        target = np.where(norm[:, None] > 1e-12, target / np.maximum(norm, 1e-12)[:, None],
                          tangents)
        if facing is schemas.ScatterPathFacing.OUTWARD:
            target = -target
        return _signed_angle(np.broadcast_to(front, target.shape), target, up_vec)
    axes = list(usd.metrics.horizontal_axes(up))
    theta = math.radians(direction_degrees or 0.0)
    fixed = np.zeros(3)
    fixed[axes[0]] = math.cos(theta)
    fixed[axes[1]] = math.sin(theta)
    return _signed_angle(front[None, :], fixed[None, :], up_vec).repeat(n)


def side_signs(sides: schemas.ScatterPathSide) -> list[int]:
    """Lateral offset signs (+1 left, -1 right, 0 on the line) for *sides*."""
    return {
        schemas.ScatterPathSide.CENTER: [0],
        schemas.ScatterPathSide.LEFT: [1],
        schemas.ScatterPathSide.RIGHT: [-1],
        schemas.ScatterPathSide.BOTH: [1, -1],
    }[sides]


# ── Helpers ──


def _curve_points(
    stage: Usd.Stage, prim_path: str,
) -> tuple[schemas.FloatArray, bool, schemas.FloatArray]:
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
    world = usd.transforms.gf_matrix_to_numpy(usd.transforms.world_matrix(prim))
    points = usd.transforms.transform_points(points, world)
    closed = curves.GetWrapAttr().Get() == UsdGeom.Tokens.periodic
    return points, closed, points.mean(axis=0)


def _plan_length(points: schemas.FloatArray, closed: bool, up: int) -> float:
    pts = np.vstack([points, points[:1]]) if closed else points
    axes = list(usd.metrics.horizontal_axes(up))
    seg = np.diff(pts[:, axes], axis=0)
    return float(np.hypot(seg[:, 0], seg[:, 1]).sum())


def _segment_direction(
    points: schemas.FloatArray, closed: bool, up: int, stations: schemas.FloatArray,
) -> schemas.FloatArray:
    """Direction of the path segment containing each station (tangent fallback)."""
    pts = np.vstack([points, points[:1]]) if closed else points
    axes = list(usd.metrics.horizontal_axes(up))
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


def _front_vector(up: int) -> schemas.FloatArray:
    """Prototype front direction: +Z in Y-up scenes, -Y in Z-up scenes."""
    return np.array([0.0, 0.0, 1.0]) if up == 1 else np.array([0.0, -1.0, 0.0])


def _signed_angle(
    src: schemas.FloatArray, dst: schemas.FloatArray, axis: schemas.FloatArray,
) -> schemas.FloatArray:
    """Signed angle (radians) about *axis* turning each *src* onto each *dst*."""
    src = np.broadcast_to(src, dst.shape)
    cross = np.cross(src, dst)
    return np.arctan2(cross @ axis, (src * dst).sum(axis=1))


def _path_pitch(
    index: schemas.SurfaceIndex,
    points: schemas.FloatArray,
    closed: bool,
    up: int,
    stations: schemas.FloatArray,
    half: schemas.FloatArray,
    station_idx: schemas.IntArray,
    lateral: schemas.FloatArray,
) -> schemas.FloatArray:
    """Pitch (radians) of the surface along the path across each instance."""
    ahead = sample(points, closed, up, stations + half)[station_idx] + lateral
    behind = sample(points, closed, up, stations - half)[station_idx] + lateral
    hit_a, h_a, _ = usd.surface.surface_under(
        index, ahead, mode="nearest", reference=ahead[:, up].copy(),
    )
    hit_b, h_b, _ = usd.surface.surface_under(
        index, behind, mode="nearest", reference=behind[:, up].copy(),
    )
    axes = list(usd.metrics.horizontal_axes(up))
    run = np.linalg.norm((ahead - behind)[:, axes], axis=1)
    rise = np.where(hit_a & hit_b, h_a - h_b, 0.0)
    return np.arctan2(rise, np.maximum(run, 1e-9))
