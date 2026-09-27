# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Bounds — the one bounding-box cache, and world-space bounds of prims."""

from __future__ import annotations

import numpy as np
from pxr import Gf, Sdf, Tf, Usd, UsdGeom

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
    """World-aligned range of the geometry under *prim*, or ``None`` when it has none.

    Geometry is gprims: instance proxies and the gprims a PointInstancer
    repeats included. Lights are not geometry, although USD gives some of
    them an extent (a lamp's bulb would make it taller and float it above
    the floor), and neither are cameras.
    """
    rng = _geometry_range(prim, cache, Gf.Matrix4d(1.0))
    return None if rng.IsEmpty() else rng


def untransformed_range(prim: Usd.Prim, cache: UsdGeom.BBoxCache) -> Gf.Range3d | None:
    """Like :func:`world_range`, in *prim*'s own space (its own transform left out)."""
    to_local = Gf.Matrix4d(1.0)
    if prim.IsA(UsdGeom.Xformable):
        to_local = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(
            cache.GetTime(),
        ).GetInverse()
    rng = _geometry_range(prim, cache, to_local)
    return None if rng.IsEmpty() else rng


def _geometry_range(
    prim: Usd.Prim, cache: UsdGeom.BBoxCache, to_frame: Gf.Matrix4d,
) -> Gf.Range3d:
    """Aligned range, in the frame *to_frame* maps world into, of the geometry under *prim*.

    USD's own bound is used for every part of the tree that holds no light,
    so only the branches that do are walked.
    """
    predicate = Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)
    light_types = {
        Usd.SchemaRegistry.GetSchemaTypeName(kind)
        for kind in Tf.Type.FindByName("UsdLuxBoundableLightBase").GetAllDerivedTypes()
    }
    lights = [
        part.GetPath() for part in Usd.PrimRange(prim, predicate)
        if part.GetTypeName() in light_types
    ]
    return _range_without(prim, cache, to_frame, lights)


def _range_without(
    prim: Usd.Prim,
    cache: UsdGeom.BBoxCache,
    to_frame: Gf.Matrix4d,
    lights: list[Sdf.Path],
) -> Gf.Range3d:
    """USD's bound of *prim*, with the branches holding *lights* walked to leave them out."""
    path = prim.GetPath()
    inside = [light for light in lights if light.HasPrefix(path)]
    if not inside:
        box = cache.ComputeWorldBound(prim)
        box.Transform(to_frame)
        return box.ComputeAlignedRange()
    if path in inside:
        return Gf.Range3d()
    if prim.IsA(UsdGeom.PointInstancer):
        return _instancer_range(UsdGeom.PointInstancer(prim), cache, to_frame)
    total = Gf.Range3d()
    for child in prim.GetFilteredChildren(Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)):
        total.UnionWith(_range_without(child, cache, to_frame, inside))
    return total


def _instancer_range(
    instancer: UsdGeom.PointInstancer, cache: UsdGeom.BBoxCache, to_frame: Gf.Matrix4d,
) -> Gf.Range3d:
    """Range of every visible instance, from its prototype's geometry (not its lights)."""
    time = cache.GetTime()
    indices = np.asarray(instancer.GetProtoIndicesAttr().Get(time) or [], dtype=np.int64)
    xforms = np.asarray(instancer.ComputeInstanceTransformsAtTime(
        time, time,
        UsdGeom.PointInstancer.IncludeProtoXform, UsdGeom.PointInstancer.IgnoreMask,
    ))
    if indices.size == 0 or xforms.shape[0] != indices.size:
        return Gf.Range3d()
    mask = instancer.ComputeMaskAtTime(time)
    keep = np.asarray(mask, dtype=bool) if mask else np.ones(indices.size, dtype=bool)
    stage = instancer.GetPrim().GetStage()
    targets = instancer.GetPrototypesRel().GetTargets()
    lo = np.full((len(targets), 3), np.nan)
    hi = np.full((len(targets), 3), np.nan)
    for i, target in enumerate(targets):
        prototype = stage.GetPrimAtPath(target)
        rng = untransformed_range(prototype, cache) if prototype.IsValid() else None
        if rng is not None:
            lo[i], hi[i] = rng.GetMin(), rng.GetMax()
    keep &= (indices >= 0) & (indices < len(targets))
    keep[keep] &= ~np.isnan(lo[indices[keep], 0])
    if not keep.any():
        return Gf.Range3d()
    frame = np.asarray(
        UsdGeom.Xformable(instancer).ComputeLocalToWorldTransform(time) * to_frame,
    )
    matrices = xforms[keep] @ frame
    picked = indices[keep]
    center = np.einsum(
        "ni,nij->nj", (lo[picked] + hi[picked]) / 2.0, matrices[:, :3, :3],
    ) + matrices[:, 3, :3]
    half = np.einsum("ni,nij->nj", (hi[picked] - lo[picked]) / 2.0, np.abs(matrices[:, :3, :3]))
    return Gf.Range3d(
        Gf.Vec3d(*(center - half).min(axis=0)), Gf.Vec3d(*(center + half).max(axis=0)),
    )


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
