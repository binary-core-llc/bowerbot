# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Placement math: an asset's position from bounds offsets, and suggested grid layouts."""

from __future__ import annotations

import math

from pxr import Gf

from bowerbot import constants
from bowerbot import schemas


def resolve_asset_position(
    mode: schemas.PositionMode,
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
    if mode is schemas.PositionMode.ABSOLUTE:
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
        ty = bounds["max"]["y"] + constants.LightDefaults.Y_OFFSET

    return tx, ty, tz


def suggest_grid_layout(
    count: int,
    *,
    spacing: float = 2.0,
    room_bounds: tuple[float, float, float] = (10.0, 3.0, 8.0),
    center: tuple[float, float] | None = None,
) -> list[tuple[float, float, float]]:
    """Compute ``(x, y, z)`` positions for *count* objects in a grid."""
    if count <= 0:
        return []

    room_width, _, room_depth = room_bounds
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)

    cx = center[0] if center else room_width / 2
    cz = center[1] if center else room_depth / 2

    x_offset = cx - (cols - 1) * spacing / 2
    z_offset = cz - (rows - 1) * spacing / 2

    placements: list[tuple[float, float, float]] = []
    for i in range(count):
        row = i // cols
        col = i % cols
        x = x_offset + col * spacing
        z = z_offset + row * spacing
        placements.append((x, 0.0, z))
    return placements
