# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""World-space bounding boxes of prims."""

from __future__ import annotations

import numpy as np
from pxr import Usd
from pxr import UsdGeom

from bowerbot import schemas

# ── World-aligned bounds ──


def world_bounds(
    prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache,
) -> dict | None:
    """Compute world-aligned AABB for a prim, rounded to 4 decimals."""
    rng = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
    if rng.IsEmpty():
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
    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render],
    )
    rng = cache.ComputeWorldBound(prim).ComputeAlignedRange()
    if rng.IsEmpty():
        msg = f"Prim {prim_path} has no geometry bounds."
        raise ValueError(msg)
    return np.array(rng.GetMin()), np.array(rng.GetMax())
