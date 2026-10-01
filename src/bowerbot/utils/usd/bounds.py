# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""World-space bounding boxes of prims."""

from __future__ import annotations

import numpy as np
from pxr import Gf
from pxr import Usd
from pxr import UsdGeom

from bowerbot import schemas

# ── World-aligned bounds ──


def bounds_cache(*, include_render: bool = False) -> UsdGeom.BBoxCache:
    """A bounds cache at the default time: default-purpose geometry, plus render-only if asked."""
    purposes = [UsdGeom.Tokens.default_]
    if include_render:
        purposes.append(UsdGeom.Tokens.render)
    return UsdGeom.BBoxCache(Usd.TimeCode.Default(), purposes)


def world_range(prim: Usd.Prim, cache: UsdGeom.BBoxCache) -> Gf.Range3d | None:
    """World-aligned box of a prim, or None when it has no geometry."""
    rng = cache.ComputeWorldBound(prim).ComputeAlignedRange()
    return None if rng.IsEmpty() else rng


def range_corners(rng: Gf.Range3d) -> schemas.FloatArray:
    """The eight corners of a box, ``(8, 3)``."""
    return np.array([list(rng.GetCorner(i)) for i in range(8)])


def world_bounds(
    prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache,
) -> dict | None:
    """Compute world-aligned AABB for a prim, rounded to 4 decimals."""
    rng = world_range(prim, bbox_cache)
    if rng is None:
        return None
    mn, mx = rng.GetMin(), rng.GetMax()
    return {
        "min": {"x": round(mn[0], 4), "y": round(mn[1], 4), "z": round(mn[2], 4)},
        "max": {"x": round(mx[0], 4), "y": round(mx[1], 4), "z": round(mx[2], 4)},
    }


def prim_world_box(
    stage: Usd.Stage, prim_path: str,
) -> tuple[schemas.FloatArray, schemas.FloatArray]:
    """World-aligned bounding box ``(min, max)`` of a prim; raises if empty."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)
    rng = world_range(prim, bounds_cache(include_render=True))
    if rng is None:
        msg = f"Prim {prim_path} has no geometry bounds."
        raise ValueError(msg)
    return np.array(rng.GetMin()), np.array(rng.GetMax())


def base_center(lo: schemas.FloatArray, hi: schemas.FloatArray, up: int) -> schemas.FloatArray:
    """The centre of a box's bottom face: one box ``(3,)`` or many ``(n, 3)``."""
    center = (lo + hi) / 2.0
    center[..., up] = lo[..., up]
    return center
