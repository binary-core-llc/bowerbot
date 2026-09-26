# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter along a path — placing pieces along polylines, circles and curves."""

from __future__ import annotations

import math

import numpy as np
from pxr import Usd

from bowerbot.schemas import (
    ScatterAlign,
    ScatterInstanceSet,
    ScatterPathParams,
    ScatterPoseParams,
    ScatterPrototype,
    SurfaceIndex,
)
from bowerbot.utils import surface_utils
from bowerbot.utils.core.metrics import up_vector
from bowerbot.utils.scatter.orientation import quat_axis_angle, quat_between, quat_mul
from bowerbot.utils.scatter.paths import (
    build_path,
    facing_yaw,
    path_pitch,
    path_stations,
    path_tangents,
    plan_length,
    prototype_length,
    sample_path,
    side_signs,
)
from bowerbot.utils.scatter.prototypes import pick_prototypes, prototype_bases, random_scales
from bowerbot.utils.scatter.resting import ground_normals, rest_positions


def generate_path_scatter(
    stage: Usd.Stage,
    path: ScatterPathParams,
    pose: ScatterPoseParams,
    *,
    prototypes: list[ScatterPrototype],
    index: SurfaceIndex | None,
    up: int,
    seed: int,
) -> tuple[ScatterInstanceSet, list[str]]:
    """Compute every instance of a scatter_along_path call in world space."""
    rng = np.random.default_rng(seed)
    up_vec = up_vector(up)
    points, closed, center = build_path(stage, path, up)
    spacing = path.spacing
    if path.count is None and spacing is None:
        mean_scale = sum(pose.scale_range) / 2.0
        spacing = max(prototype_length(p, up, path.facing) for p in prototypes) * mean_scale
        spacing += path.gap
        if spacing <= 0:
            raise ValueError("could not derive spacing from the assets; pass 'spacing'.")
    stations, half, _ = path_stations(
        points, closed, up, count=path.count, spacing=spacing or 1.0,
        start_offset=path.start_offset,
    )
    tangents = path_tangents(points, closed, up, stations, half)
    signs = np.array(side_signs(path.sides), dtype=np.float64)
    per_station = signs.size
    station_idx = np.repeat(np.arange(stations.size), per_station)
    sign = np.tile(signs, stations.size)
    tangent = tangents[station_idx]
    lateral = np.cross(up_vec, tangent) * (sign * path.offset)[:, None]
    contacts = sample_path(points, closed, up, stations)[station_idx] + lateral

    n = contacts.shape[0]
    weights = [proto.weight for proto in prototypes]
    proto_idx = pick_prototypes(rng, weights, n, path.asset_order)
    scales = random_scales(rng, pose.scale_range, n)
    normals = np.repeat(up_vec[None, :], n, axis=0)
    warnings: list[str] = []
    if index is not None:
        hit, heights, tris = surface_utils.surface_under(
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
    headings = quat_axis_angle(up_vec, yaw)
    orientations = headings
    settle = np.full(n, pose.align is ScatterAlign.UP)
    if path.follow_slope and index is not None:
        pitch = path_pitch(index, points, closed, up, stations, half, station_idx, lateral)
        axis = np.cross(tangent, up_vec)
        orientations = quat_mul(quat_axis_angle(axis, pitch), orientations)
    if pose.align is ScatterAlign.SURFACE:
        if index is not None:
            base_min, base_max = prototype_bases(prototypes, proto_idx)
            normals, settle = ground_normals(
                index, contacts, headings, scales, base_min, base_max, normals, up,
            )
        orientations = quat_mul(quat_between(up_vec, normals), orientations)
    if path.follow_slope:
        settle[:] = False
    positions = rest_positions(
        contacts, orientations, scales, prototypes, proto_idx, up,
        embed=pose.embed, settle=settle, index=index,
    )
    return ScatterInstanceSet(
        proto_indices=proto_idx, positions=positions,
        orientations=orientations, scales=scales,
    ), warnings


def estimate_path_scatter(
    stage: Usd.Stage, path: ScatterPathParams, up: int,
) -> tuple[int | None, float]:
    """Return ``(instances or None when spacing is automatic, path_length)``."""
    points, closed, _ = build_path(stage, path, up)
    length = plan_length(points, closed, up)
    if path.count is None and path.spacing is None:
        return None, length
    stations, _, _ = path_stations(
        points, closed, up, count=path.count, spacing=path.spacing or 1.0,
        start_offset=path.start_offset,
    )
    return int(stations.size) * len(side_signs(path.sides)), length
