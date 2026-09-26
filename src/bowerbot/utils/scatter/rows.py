# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter rows — a jittered row lattice draped over the surface."""

from __future__ import annotations

import math

import numpy as np

from bowerbot.schemas import (
    ScatterRules,
    ScatterSurfaceParams,
    SurfaceTriangles,
)
from bowerbot.schemas.surface import BoolArray, FloatArray, IntArray
from bowerbot.utils import surface_utils
from bowerbot.utils.scatter.regions import plan_to_world, region_plan_bounds


def rows_plan_points(
    rng: np.random.Generator,
    lo: FloatArray,
    hi: FloatArray,
    *,
    spacing: float,
    row_spacing: float,
    direction_degrees: float,
    jitter: float,
) -> FloatArray:
    """A rotated lattice of plan points covering ``[lo, hi]`` (rows x in-row)."""
    theta = math.radians(direction_degrees)
    along = np.array([math.cos(theta), math.sin(theta)], dtype=np.float64)
    across = np.array([-math.sin(theta), math.cos(theta)], dtype=np.float64)
    corners = np.array(
        [[lo[0], lo[1]], [hi[0], lo[1]], [lo[0], hi[1]], [hi[0], hi[1]]], dtype=np.float64,
    )
    u = corners @ along
    v = corners @ across
    us = np.arange(u.min(), u.max() + 1e-9, spacing, dtype=np.float64)
    vs = np.arange(v.min(), v.max() + 1e-9, row_spacing, dtype=np.float64)
    if us.size * vs.size > ScatterRules.MAX_INSTANCES:
        msg = (
            f"rows would create {us.size * vs.size:,} lattice points; the maximum "
            f"is {ScatterRules.MAX_INSTANCES:,}. Increase spacing/row_spacing or add a region."
        )
        raise ValueError(msg)
    uu, vv = np.meshgrid(us, vs, indexing="ij")
    plan = uu.reshape(-1, 1) * along + vv.reshape(-1, 1) * across
    if jitter > 0:
        plan += rng.uniform(-jitter, jitter, plan.shape)
    return plan


def rows_contacts(
    rng: np.random.Generator,
    surface: ScatterSurfaceParams,
    triangles: SurfaceTriangles,
    tri_mask: BoolArray,
    up: int,
) -> tuple[FloatArray, IntArray]:
    """Row lattice points projected straight down onto the top surface."""
    if surface.spacing is None or surface.row_spacing is None:
        msg = "arrangement 'rows' needs spacing and row_spacing."
        raise ValueError(msg)
    lo, hi = region_plan_bounds(surface.region, up) or surface_utils.plan_bounds(triangles, up)
    plan = rows_plan_points(
        rng, lo, hi, spacing=surface.spacing, row_spacing=surface.row_spacing,
        direction_degrees=surface.row_direction_degrees, jitter=surface.jitter,
    )
    points = plan_to_world(plan, up)
    index = surface_utils.build_vertical_index(triangles, up, up_facing_only=True)
    hit, heights, tris = surface_utils.surface_under(index, points, mode="top")
    ok = hit.copy()
    ok[hit] = tri_mask[tris[hit]]
    points = points[ok]
    points[:, up] = heights[ok]
    return points, tris[ok]
