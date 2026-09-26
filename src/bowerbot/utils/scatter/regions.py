# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter regions — plan-view masks, falloff and bounds of a region."""

from __future__ import annotations

import numpy as np

from bowerbot.schemas import (
    ScatterRegion,
    ScatterRegionFalloff,
)
from bowerbot.schemas.surface import BoolArray, FloatArray
from bowerbot.utils.core.metrics import horizontal_axes


def region_mask(points: FloatArray, region: ScatterRegion | None, up: int) -> BoolArray:
    """Which *points* fall inside *region* in plan view."""
    if region is None:
        return np.ones(points.shape[0], dtype=bool)
    axes = list(horizontal_axes(up))
    if region.polygon is not None:
        polygon = np.asarray(region.polygon, dtype=np.float64)[:, axes]
        return _point_in_polygon(points[:, axes], polygon)
    center, radius = region_circle(region)
    return _plan_distance(points, center, up) <= radius


def region_falloff(points: FloatArray, region: ScatterRegion | None, up: int) -> FloatArray:
    """Density multiplier fading from a circular region's centre to its edge."""
    if region is None or region.polygon is not None or region.falloff is ScatterRegionFalloff.NONE:
        return np.ones(points.shape[0])
    center, radius = region_circle(region)
    t = np.clip(_plan_distance(points, center, up) / radius, 0.0, 1.0)
    if region.falloff is ScatterRegionFalloff.LINEAR:
        return 1.0 - t
    return 1.0 - t * t * (3.0 - 2.0 * t)


def region_plan_bounds(
    region: ScatterRegion | None, up: int,
) -> tuple[FloatArray, FloatArray] | None:
    """Plan-view bounding box of *region*, or ``None`` for no region."""
    if region is None:
        return None
    axes = list(horizontal_axes(up))
    if region.polygon is not None:
        plan = np.asarray(region.polygon)[:, axes]
        return plan.min(axis=0), plan.max(axis=0)
    center = np.asarray(region.center)[axes]
    return center - region.radius, center + region.radius


def plan_to_world(plan: FloatArray, up: int, height: float = 0.0) -> FloatArray:
    """Lift plan-view points to 3D at *height* on the up axis."""
    axes = list(horizontal_axes(up))
    pts = np.full((plan.shape[0], 3), height, dtype=np.float64)
    pts[:, axes] = plan
    return pts


def _point_in_polygon(plan: FloatArray, polygon: FloatArray) -> BoolArray:
    """Even-odd test of plan points against a closed polygon."""
    inside = np.zeros(plan.shape[0], dtype=bool)
    x, y = plan[:, 0], plan[:, 1]
    for (x0, y0), (x1, y1) in zip(polygon, np.roll(polygon, -1, axis=0), strict=True):
        crosses = (y0 > y) != (y1 > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
        inside ^= crosses & (x < x_cross)
    return inside


def region_circle(region: ScatterRegion) -> tuple[FloatArray, float]:
    """A circular region's centre and radius."""
    if region.center is None or region.radius is None:
        msg = "a region needs a polygon, or a center and a radius."
        raise ValueError(msg)
    return np.asarray(region.center, dtype=np.float64), region.radius


def _plan_distance(points: FloatArray, center: FloatArray, up: int) -> FloatArray:
    """Plan-view distance from each point to *center*."""
    axes = list(horizontal_axes(up))
    offset = points[:, axes] - center[axes]
    return np.hypot(offset[:, 0], offset[:, 1])
