# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Bounds — the one bounding-box cache, and world-space bounds of prims."""

from __future__ import annotations

import numpy as np
from pxr import Gf, Usd, UsdGeom

from bowerbot.schemas.surface import FloatArray


def bbox_cache(
    *, include_render: bool = False, time: Usd.TimeCode | None = None,
) -> UsdGeom.BBoxCache:
    """A bounding-box cache over default-purpose geometry, plus render geometry if asked."""
    purposes = [UsdGeom.Tokens.default_]
    if include_render:
        purposes.append(UsdGeom.Tokens.render)
    return UsdGeom.BBoxCache(time if time is not None else Usd.TimeCode.Default(), purposes)


def world_range(prim: Usd.Prim, cache: UsdGeom.BBoxCache) -> Gf.Range3d | None:
    """World-aligned range of *prim*, or ``None`` when it has no geometry."""
    rng = cache.ComputeWorldBound(prim).ComputeAlignedRange()
    return None if rng.IsEmpty() else rng


def world_bounds(
    prim: Usd.Prim, cache: UsdGeom.BBoxCache,
) -> dict[str, dict[str, float]] | None:
    """Compute world-aligned AABB for a prim, rounded to 4 decimals."""
    rng = world_range(prim, cache)
    if rng is None:
        return None
    mn, mx = rng.GetMin(), rng.GetMax()
    return {
        "min": {"x": round(mn[0], 4), "y": round(mn[1], 4), "z": round(mn[2], 4)},
        "max": {"x": round(mx[0], 4), "y": round(mx[1], 4), "z": round(mx[2], 4)},
    }


def prim_world_box(
    stage: Usd.Stage, prim_path: str,
) -> tuple[FloatArray, FloatArray]:
    """World-aligned bounding box ``(min, max)`` of a prim; raises if empty."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)
    rng = world_range(prim, bbox_cache(include_render=True))
    if rng is None:
        msg = f"Prim {prim_path} has no geometry bounds."
        raise ValueError(msg)
    return np.array(rng.GetMin()), np.array(rng.GetMax())
