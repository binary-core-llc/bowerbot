# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Geometry service — spatial math for placing prims in a scene.

Covers:

* Asset bounds (geometry AABB in meters).
* Unit factors (meters ↔ asset-native units).
* Coordinate resolution (``absolute`` or ``bounds_offset``) for
  prims placed inside an asset folder.
* Scene-level layout helpers (grid, wall).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from pxr import Gf, Usd, UsdGeom

from bowerbot.schemas import ASWFLayerNames, PlacementCategory, PositionMode
from bowerbot.services.asset_service import read_stage_metadata_from_dir

# Default vertical offset (meters) above an asset's top surface when
# placing a prim with no explicit Y position in bounds_offset mode.
DEFAULT_LIGHT_Y_OFFSET = 0.5


@dataclass
class Placement:
    """A computed placement position (translate + optional rotate)."""

    translate: tuple[float, float, float]
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)


def get_geometry_bounds(
    asset_dir: Path,
) -> dict[str, dict[str, float]] | None:
    """Return the asset's geometry bounds in meters.

    Returns a dict with ``min``, ``max``, ``center``, and ``size``
    keys, each containing ``x``, ``y``, ``z`` values in meters.
    Returns ``None`` if bounds cannot be computed.
    """
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
    """Return the asset's ``metersPerUnit``, reading from ``geo.usda``.

    Defaults to 1.0 when the asset has no geo layer or the value
    cannot be read.
    """
    mpu, _ = read_stage_metadata_from_dir(asset_dir)
    return mpu if mpu > 0 else 1.0


def meters_to_asset_units(asset_dir: Path, value: float) -> float:
    """Convert a meters value into the asset's native units."""
    mpu = get_mpu(asset_dir)
    if abs(mpu - 1.0) < 1e-6:
        return value
    return value / mpu


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

    Works for any prim placed inside an asset — lights, cameras, nested
    references, or anything else.

    Args:
        mode: Coordinate system to interpret the translate values.
        bounds: Asset-local geometry bounds (meters), only used for
            ``BOUNDS_OFFSET`` mode.
        tx, ty, tz: Input translate values.
        has_explicit_y: Whether the caller provided an explicit Y.
            Only affects ``BOUNDS_OFFSET`` mode.
        world_to_local_mat: Inverse world transform of the container's
            scene placement. When provided in ``ABSOLUTE`` mode, converts
            world-space input to asset-internal coordinates.
        asset_mpu: Asset's ``metersPerUnit`` — used to convert
            asset-internal coordinates back into meters after
            applying *world_to_local_mat*.
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

    return apply_bounds_offsets(bounds, tx, ty, tz, has_explicit_y=has_explicit_y)


def apply_bounds_offsets(
    bounds: dict[str, dict[str, float]],
    tx: float,
    ty: float,
    tz: float,
    *,
    has_explicit_y: bool,
) -> tuple[float, float, float]:
    """Convert offset-from-bounds values to absolute asset-local positions.

    * X/Z offsets come from the asset's bounding-box center.
    * Y is an offset from the top (positive) or bottom (negative)
      surface. When *has_explicit_y* is ``False``, defaults to
      ``DEFAULT_LIGHT_Y_OFFSET`` above the top surface.
    """
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
) -> list[Placement]:
    """Compute positions for *count* objects in a grid.

    Automatically picks rows/columns from ``ceil(sqrt(count))``,
    centred in the room (or at *center*).
    """
    if count <= 0:
        return []

    room_width, _, room_depth = room_bounds
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)

    cx = center[0] if center else room_width / 2
    cz = center[1] if center else room_depth / 2

    x_offset = cx - (cols - 1) * spacing / 2
    z_offset = cz - (rows - 1) * spacing / 2

    placements: list[Placement] = []
    for i in range(count):
        row = i // cols
        col = i % cols
        x = x_offset + col * spacing
        z = z_offset + row * spacing
        placements.append(Placement(translate=(x, 0.0, z)))
    return placements


def suggest_wall_layout(
    count: int,
    *,
    wall: str = "back",
    spacing: float = 2.0,
    wall_offset: float = 0.05,
    room_bounds: tuple[float, float, float] = (10.0, 3.0, 8.0),
) -> list[Placement]:
    """Place *count* objects along a named wall."""
    room_width, _, room_depth = room_bounds
    placements: list[Placement] = []
    total_span = (count - 1) * spacing

    for i in range(count):
        offset_along = -total_span / 2 + i * spacing

        match wall:
            case "back":
                x = room_width / 2 + offset_along
                z = wall_offset
                ry = 0.0
            case "front":
                x = room_width / 2 + offset_along
                z = room_depth - wall_offset
                ry = 180.0
            case "left":
                x = wall_offset
                z = room_depth / 2 + offset_along
                ry = 90.0
            case "right":
                x = room_width - wall_offset
                z = room_depth / 2 + offset_along
                ry = -90.0
            case _:
                x, z, ry = 0.0, 0.0, 0.0

        placements.append(
            Placement(translate=(x, 0.0, z), rotate=(0.0, ry, 0.0)),
        )
    return placements


def compute_placement_y(
    category: PlacementCategory,
    *,
    surface_height: float = 0.0,
    room_height: float = 3.0,
) -> float:
    """Compute the Y position based on a placement category."""
    match category:
        case PlacementCategory.FLOOR:
            return 0.0
        case PlacementCategory.SURFACE:
            return surface_height
        case PlacementCategory.CEILING:
            return room_height
        case PlacementCategory.WALL:
            return 0.0
        case _:
            return 0.0


def boxes_overlap(
    pos_a: tuple[float, float, float],
    size_a: tuple[float, float, float],
    pos_b: tuple[float, float, float],
    size_b: tuple[float, float, float],
) -> bool:
    """Return True if two axis-aligned bounding boxes overlap."""
    for i in range(3):
        half_a = size_a[i] / 2
        half_b = size_b[i] / 2
        if abs(pos_a[i] - pos_b[i]) >= (half_a + half_b):
            return False
    return True
