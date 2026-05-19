# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Geometry math: bounds, units, placement resolution, layout."""

from __future__ import annotations

import math
from pathlib import Path

from pxr import Gf, Usd, UsdGeom

from bowerbot.schemas import ASWFLayerNames, PositionMode
from bowerbot.utils.asset_folder_utils import read_stage_metadata_from_dir

# Default vertical offset (meters) above an asset's top surface when
# placing a prim with no explicit Y position in BOUNDS_OFFSET mode.
DEFAULT_LIGHT_Y_OFFSET = 0.5


def get_geometry_bounds(
    asset_dir: Path,
) -> dict[str, dict[str, float]] | None:
    """Return the asset's geometry bounds in meters, or ``None``."""
    geo_path = asset_dir / ASWFLayerNames.GEO
    if not geo_path.exists():
        return None

    stage = Usd.Stage.Open(str(geo_path))
    if stage is None:
        return None

    root = stage.GetDefaultPrim()
    if root is None:
        return None

    bbox = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_],
    )
    rng = bbox.ComputeWorldBound(root).ComputeAlignedRange()
    if rng.IsEmpty():
        return None

    mpu, _ = read_stage_metadata_from_dir(asset_dir)
    mn = rng.GetMin()
    mx = rng.GetMax()

    return {
        "min": {"x": mn[0] * mpu, "y": mn[1] * mpu, "z": mn[2] * mpu},
        "max": {"x": mx[0] * mpu, "y": mx[1] * mpu, "z": mx[2] * mpu},
        "center": {
            "x": (mn[0] + mx[0]) / 2 * mpu,
            "y": (mn[1] + mx[1]) / 2 * mpu,
            "z": (mn[2] + mx[2]) / 2 * mpu,
        },
        "size": {
            "x": (mx[0] - mn[0]) * mpu,
            "y": (mx[1] - mn[1]) * mpu,
            "z": (mx[2] - mn[2]) * mpu,
        },
    }


def get_mpu(asset_dir: Path) -> float:
    """Return the asset's ``metersPerUnit``, defaulting to 1.0."""
    mpu, _ = read_stage_metadata_from_dir(asset_dir)
    return mpu if mpu > 0 else 1.0


def unit_factor(asset_dir: Path) -> float:
    """Return the factor that converts meters into asset units."""
    mpu = get_mpu(asset_dir)
    return 1.0 / mpu if mpu > 0 else 1.0


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
        ty = bounds["max"]["y"] + DEFAULT_LIGHT_Y_OFFSET

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
