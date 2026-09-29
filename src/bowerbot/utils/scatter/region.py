# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Plan-view regions: which points fall inside, density falloff, bounds."""

from __future__ import annotations

import numpy as np

from bowerbot import schemas
from bowerbot.utils import usd


def mask(
    points: schemas.FloatArray, region: schemas.ScatterRegion | None, up: int,
) -> schemas.BoolArray:
    """Which *points* fall inside *region* in plan view."""
    if region is None:
        return np.ones(points.shape[0], dtype=bool)
    axes = list(usd.metrics.horizontal_axes(up))
    if region.polygon is not None:
        polygon = np.asarray(region.polygon, dtype=np.float64)[:, axes]
        return _point_in_polygon(points[:, axes], polygon)
    center, radius = circle(region)
    return _plan_distance(points, center, up) <= radius


def falloff(
    points: schemas.FloatArray, region: schemas.ScatterRegion | None, up: int,
) -> schemas.FloatArray:
    """Density multiplier fading from a circular region's centre to its edge."""
    if (
        region is None
        or region.polygon is not None
        or region.falloff is schemas.ScatterRegionFalloff.NONE
    ):
        return np.ones(points.shape[0])
    center, radius = circle(region)
    t = np.clip(_plan_distance(points, center, up) / radius, 0.0, 1.0)
    if region.falloff is schemas.ScatterRegionFalloff.LINEAR:
        return 1.0 - t
    return 1.0 - t * t * (3.0 - 2.0 * t)


def plan_bounds(
    region: schemas.ScatterRegion | None, up: int,
) -> tuple[schemas.FloatArray, schemas.FloatArray] | None:
    """Plan-view bounding box of *region*, or ``None`` for no region."""
    if region is None:
        return None
    axes = list(usd.metrics.horizontal_axes(up))
    if region.polygon is not None:
        plan = np.asarray(region.polygon)[:, axes]
        return plan.min(axis=0), plan.max(axis=0)
    center = np.asarray(region.center)[axes]
    return center - region.radius, center + region.radius


def circle(region: schemas.ScatterRegion) -> tuple[schemas.FloatArray, float]:
    """A circular region's centre and radius."""
    if region.center is None or region.radius is None:
        msg = "a region needs a polygon, or a center and a radius."
        raise ValueError(msg)
    return np.asarray(region.center, dtype=np.float64), region.radius


# ── Helpers ──


def _point_in_polygon(plan: schemas.FloatArray, polygon: schemas.FloatArray) -> schemas.BoolArray:
    """Even-odd test of plan points against a closed polygon."""
    inside = np.zeros(plan.shape[0], dtype=bool)
    x, y = plan[:, 0], plan[:, 1]
    for (x0, y0), (x1, y1) in zip(polygon, np.roll(polygon, -1, axis=0), strict=True):
        crosses = (y0 > y) != (y1 > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
        inside ^= crosses & (x < x_cross)
    return inside


def _plan_distance(
    points: schemas.FloatArray, center: schemas.FloatArray, up: int,
) -> schemas.FloatArray:
    """Plan-view distance from each point to *center*."""
    axes = list(usd.metrics.horizontal_axes(up))
    offset = points[:, axes] - center[axes]
    return np.hypot(offset[:, 0], offset[:, 1])
