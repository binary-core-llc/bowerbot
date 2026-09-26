# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Surface utils — world-space triangles and vectorized vertical queries."""

from __future__ import annotations

import math

import numpy as np
from pxr import Sdf, Usd, UsdGeom

from bowerbot.schemas import SurfaceIndex, SurfaceTriangles, SurfaceTuning
from bowerbot.schemas.surface import BoolArray, FloatArray, IntArray
from bowerbot.utils.core.bounds import bbox_cache
from bowerbot.utils.core.metrics import horizontal_axes
from bowerbot.utils.core.transforms import gf_matrix_to_numpy


def collect_triangles(
    stage: Usd.Stage,
    prim_paths: list[str],
    *,
    up: int,
    exclude: list[str] | tuple[str, ...] = (),
    instancer_footprints: bool = False,
) -> SurfaceTriangles:
    """World-space triangles of the gprims under *prim_paths*."""
    missing = [p for p in prim_paths if not stage.GetPrimAtPath(p).IsValid()]
    if missing:
        msg = f"Surface prim(s) not found: {missing}. Use list_scene to find prim paths."
        raise ValueError(msg)

    excluded = [Sdf.Path(p) for p in exclude]
    xform_cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    seen: set[str] = set()
    parts: list[tuple[FloatArray, FloatArray, FloatArray, bool]] = []

    for root_path in prim_paths:
        prim_range = Usd.PrimRange(
            stage.GetPrimAtPath(root_path),
            Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate),
        )
        iterator = iter(prim_range)
        for prim in iterator:
            path = prim.GetPath()
            if any(path.HasPrefix(ex) for ex in excluded) or not _is_drawn(prim):
                iterator.PruneChildren()
                continue
            key = str(path)
            if prim.IsA(UsdGeom.PointInstancer):
                iterator.PruneChildren()
                if instancer_footprints and key not in seen:
                    seen.add(key)
                    footprints = _instancer_footprints(
                        UsdGeom.PointInstancer(prim),
                        gf_matrix_to_numpy(xform_cache.GetLocalToWorldTransform(prim)),
                        up,
                    )
                    if footprints is not None:
                        parts.append((*footprints, False))
                continue
            if key in seen or not prim.IsA(UsdGeom.Gprim):
                continue
            seen.add(key)
            local = _local_triangles(prim)
            if local is None:
                continue
            a, b, c = local
            matrix = gf_matrix_to_numpy(xform_cache.GetLocalToWorldTransform(prim))
            if np.linalg.det(matrix[:3, :3]) < 0:
                b, c = c, b
            parts.append((
                _to_world(a, matrix), _to_world(b, matrix), _to_world(c, matrix),
                _is_double_sided(prim),
            ))

    return _build_triangles(parts, up)


def build_vertical_index(
    triangles: SurfaceTriangles, up: int, *, pad: float = 0.0, up_facing_only: bool = False,
) -> SurfaceIndex:
    """Bin triangles on the ground plane for local vertical-line queries."""
    axes = horizontal_axes(up)
    keep = np.arange(triangles.count)
    if up_facing_only:
        keep = keep[triangles.normals[:, up] > 1e-3]
    if keep.size == 0:
        return _empty_index(triangles, up, axes)

    tri_a = np.stack([triangles.v0[keep][:, axes[0]], triangles.v1[keep][:, axes[0]],
                      triangles.v2[keep][:, axes[0]]], axis=1)
    tri_b = np.stack([triangles.v0[keep][:, axes[1]], triangles.v1[keep][:, axes[1]],
                      triangles.v2[keep][:, axes[1]]], axis=1)
    amin = tri_a.min(axis=1) - pad
    amax = tri_a.max(axis=1) + pad
    bmin = tri_b.min(axis=1) - pad
    bmax = tri_b.max(axis=1) + pad

    origin = np.array([amin.min(), bmin.min()])
    extent = max(amax.max() - origin[0], bmax.max() - origin[1], SurfaceTuning.EPS)
    typical = float(np.median(np.maximum(amax - amin, bmax - bmin)))
    cell = max(typical, extent / math.sqrt(SurfaceTuning.MAX_GRID_CELLS), SurfaceTuning.EPS)
    dims = (
        int((amax.max() - origin[0]) / cell) + 1,
        int((bmax.max() - origin[1]) / cell) + 1,
    )

    ia0 = ((amin - origin[0]) / cell).astype(np.int64)
    ia1 = ((amax - origin[0]) / cell).astype(np.int64)
    ib0 = ((bmin - origin[1]) / cell).astype(np.int64)
    ib1 = ((bmax - origin[1]) / cell).astype(np.int64)
    span_a = ia1 - ia0 + 1
    span_b = ib1 - ib0 + 1
    per_tri = span_a * span_b

    tri_rep = np.repeat(np.arange(keep.size), per_tri)
    local = np.arange(per_tri.sum()) - np.repeat(np.cumsum(per_tri) - per_tri, per_tri)
    cell_a = ia0[tri_rep] + local // span_b[tri_rep]
    cell_b = ib0[tri_rep] + local % span_b[tri_rep]
    cell_ids = cell_a * dims[1] + cell_b

    order = np.argsort(cell_ids, kind="stable")
    cell_tris = keep[tri_rep[order]]
    counts = np.bincount(cell_ids, minlength=dims[0] * dims[1])
    cell_start = np.concatenate([[0], np.cumsum(counts)])
    return SurfaceIndex(
        triangles=triangles, up=up, axes=axes, origin=origin, cell=cell, dims=dims,
        cell_start=cell_start, cell_tris=cell_tris,
    )


def vertical_hits(
    index: SurfaceIndex, qa: FloatArray, qb: FloatArray,
) -> tuple[IntArray, IntArray, FloatArray]:
    """Every (query, triangle, height) where a vertical line meets a triangle."""
    out_q, out_t, out_h = [], [], []
    for start in range(0, qa.shape[0], SurfaceTuning.QUERY_CHUNK):
        sl = slice(start, start + SurfaceTuning.QUERY_CHUNK)
        q, t = _candidate_pairs(index, qa[sl], qb[sl])
        if q.size == 0:
            continue
        pa, pb = qa[sl][q], qb[sl][q]
        l0, l1, l2, valid = _barycentric_2d(index, t, pa, pb)
        tol = -SurfaceTuning.BARY_EPS
        inside = valid & (l0 >= tol) & (l1 >= tol) & (l2 >= tol)
        q, t = q[inside], t[inside]
        up = index.up
        triangles = index.triangles
        height = (
            l0[inside] * triangles.v0[t, up]
            + l1[inside] * triangles.v1[t, up]
            + l2[inside] * triangles.v2[t, up]
        )
        out_q.append(q + start)
        out_t.append(t)
        out_h.append(height)
    if not out_q:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros(0)
    return np.concatenate(out_q), np.concatenate(out_t), np.concatenate(out_h)


def surface_under(
    index: SurfaceIndex,
    points: FloatArray,
    *,
    mode: str,
    reference: FloatArray | None = None,
) -> tuple[BoolArray, FloatArray, IntArray]:
    """One surface hit per point along its vertical line: top, nearest or below."""
    n = points.shape[0]
    axes = index.axes
    q, t, h = vertical_hits(index, points[:, axes[0]], points[:, axes[1]])
    if mode == "top":
        score = h
    elif reference is None:
        msg = f"surface_under mode {mode!r} needs reference heights"
        raise ValueError(msg)
    elif mode == "nearest":
        score = -np.abs(h - reference[q])
    elif mode == "below":
        allowed = h <= reference[q] + 1e-6
        q, t, h = q[allowed], t[allowed], h[allowed]
        score = h
    else:
        msg = f"unknown surface_under mode {mode!r}"
        raise ValueError(msg)

    hit = np.zeros(n, dtype=bool)
    heights = np.full(n, np.nan)
    tris = np.full(n, -1, dtype=np.int64)
    if q.size == 0:
        return hit, heights, tris
    order = np.lexsort((-score, q))
    q_sorted = q[order]
    first = np.ones(q_sorted.size, dtype=bool)
    first[1:] = q_sorted[1:] != q_sorted[:-1]
    best = order[first]
    hit[q[best]] = True
    heights[q[best]] = h[best]
    tris[q[best]] = t[best]
    return hit, heights, tris


def plan_coverage(
    index: SurfaceIndex, qa: FloatArray, qb: FloatArray, margin: float,
) -> BoolArray:
    """Whether each plan-view point lies on (or within *margin* of) any triangle."""
    covered = np.zeros(qa.shape[0], dtype=bool)
    for start in range(0, qa.shape[0], SurfaceTuning.QUERY_CHUNK):
        sl = slice(start, start + SurfaceTuning.QUERY_CHUNK)
        q, t = _candidate_pairs(index, qa[sl], qb[sl])
        if q.size == 0:
            continue
        pa, pb = qa[sl][q], qb[sl][q]
        l0, l1, l2, valid = _barycentric_2d(index, t, pa, pb)
        tol = -SurfaceTuning.BARY_EPS
        inside = valid & (l0 >= tol) & (l1 >= tol) & (l2 >= tol)
        if margin > 0:
            near = _distance_to_triangle_2d(index, t, pa, pb) <= margin
            inside = inside | near
        hit_q = np.unique(q[inside])
        covered[hit_q + start] = True
    return covered


def sample_on_triangles(
    rng: np.random.Generator, triangles: SurfaceTriangles, weights: FloatArray, n: int,
) -> tuple[FloatArray, IntArray]:
    """Draw *n* points uniformly by area (times *weights*) over the triangles."""
    total = float(weights.sum())
    if n <= 0 or total <= 0:
        return np.zeros((0, 3)), np.zeros(0, dtype=np.int64)
    tri = rng.choice(triangles.count, size=n, p=weights / total)
    r1 = np.sqrt(rng.random(n))
    r2 = rng.random(n)
    u = (1.0 - r1)[:, None]
    v = (r1 * (1.0 - r2))[:, None]
    w = (r1 * r2)[:, None]
    points = u * triangles.v0[tri] + v * triangles.v1[tri] + w * triangles.v2[tri]
    return points, tri


def slope_mask(triangles: SurfaceTriangles, up: int, max_slope_degrees: float) -> BoolArray:
    """Triangles whose normal is within *max_slope_degrees* of the up axis."""
    if max_slope_degrees >= 180.0:
        return np.ones(triangles.count, dtype=bool)
    return triangles.normals[:, up] >= math.cos(math.radians(max_slope_degrees)) - 1e-9


def plan_bounds(triangles: SurfaceTriangles, up: int) -> tuple[FloatArray, FloatArray]:
    """Plan-view ``(min, max)`` of the triangles on the ground axes."""
    axes = list(horizontal_axes(up))
    pts = np.concatenate([triangles.v0[:, axes], triangles.v1[:, axes], triangles.v2[:, axes]])
    return pts.min(axis=0), pts.max(axis=0)


# ── internals ──


def _is_drawn(prim: Usd.Prim) -> bool:
    """False for invisible prims and guide / proxy purpose geometry."""
    imageable = UsdGeom.Imageable(prim)
    if not imageable:
        return True
    if imageable.ComputeVisibility() == UsdGeom.Tokens.invisible:
        return False
    return imageable.ComputePurpose() in (UsdGeom.Tokens.default_, UsdGeom.Tokens.render)


def _is_double_sided(prim: Usd.Prim) -> bool:
    gprim = UsdGeom.Gprim(prim)
    value = gprim.GetDoubleSidedAttr().Get() if gprim else None
    return bool(value)


def _local_triangles(
    prim: Usd.Prim,
) -> tuple[FloatArray, FloatArray, FloatArray] | None:
    """Triangles of a supported gprim in its own local space."""
    if prim.IsA(UsdGeom.Mesh):
        return _mesh_triangles(UsdGeom.Mesh(prim))
    if prim.IsA(UsdGeom.Cube):
        return _cube_triangles(UsdGeom.Cube(prim))
    if prim.IsA(UsdGeom.Sphere):
        return _sphere_triangles(UsdGeom.Sphere(prim))
    if hasattr(UsdGeom, "Plane") and prim.IsA(UsdGeom.Plane):
        return _plane_triangles(UsdGeom.Plane(prim))
    return None


def _mesh_triangles(
    mesh: UsdGeom.Mesh,
) -> tuple[FloatArray, FloatArray, FloatArray] | None:
    points = mesh.GetPointsAttr().Get()
    counts = mesh.GetFaceVertexCountsAttr().Get()
    indices = mesh.GetFaceVertexIndicesAttr().Get()
    if not points or not counts or not indices:
        return None
    pts = np.asarray(points, dtype=np.float64)
    counts_np = np.asarray(counts, dtype=np.int64)
    idx = np.asarray(indices, dtype=np.int64)
    if counts_np.sum() != idx.size:
        return None

    starts = np.cumsum(counts_np) - counts_np
    ntri = np.clip(counts_np - 2, 0, None)
    total = int(ntri.sum())
    if total == 0:
        return None
    face = np.repeat(np.arange(counts_np.size), ntri)
    k = np.arange(total) - np.repeat(np.cumsum(ntri) - ntri, ntri)
    base = starts[face]
    i0 = idx[base]
    i1 = idx[base + k + 1]
    i2 = idx[base + k + 2]
    if mesh.GetOrientationAttr().Get() == UsdGeom.Tokens.leftHanded:
        i1, i2 = i2, i1
    valid = (i0 < pts.shape[0]) & (i1 < pts.shape[0]) & (i2 < pts.shape[0])
    return pts[i0[valid]], pts[i1[valid]], pts[i2[valid]]


def _cube_triangles(cube: UsdGeom.Cube) -> tuple[FloatArray, FloatArray, FloatArray]:
    half = (cube.GetSizeAttr().Get() or 2.0) / 2.0
    corners = np.array([
        [x, y, z] for x in (-half, half) for y in (-half, half) for z in (-half, half)
    ])
    # Outward quads; corner index = 4x + 2y + z.
    quads = [
        (0, 1, 3, 2), (4, 6, 7, 5),  # -X, +X
        (0, 4, 5, 1), (2, 3, 7, 6),  # -Y, +Y
        (0, 2, 6, 4), (1, 5, 7, 3),  # -Z, +Z
    ]
    tris = [(q[0], q[1], q[2]) for q in quads] + [(q[0], q[2], q[3]) for q in quads]
    t = np.array(tris)
    return corners[t[:, 0]], corners[t[:, 1]], corners[t[:, 2]]


def _sphere_triangles(
    sphere: UsdGeom.Sphere,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    radius = sphere.GetRadiusAttr().Get() or 1.0
    n_lon, n_lat = SurfaceTuning.SPHERE_SEGMENTS
    theta = np.linspace(0.0, math.pi, n_lat + 1)
    phi = np.linspace(0.0, 2.0 * math.pi, n_lon + 1)
    tt, pp = np.meshgrid(theta, phi, indexing="ij")
    grid = np.stack([
        radius * np.sin(tt) * np.cos(pp),
        radius * np.cos(tt),
        radius * np.sin(tt) * np.sin(pp),
    ], axis=-1)
    a = grid[:-1, :-1].reshape(-1, 3)
    b = grid[1:, :-1].reshape(-1, 3)
    c = grid[1:, 1:].reshape(-1, 3)
    d = grid[:-1, 1:].reshape(-1, 3)
    # Winding chosen so normals point outward.
    return np.concatenate([a, a]), np.concatenate([c, d]), np.concatenate([b, c])


def _plane_triangles(plane: UsdGeom.Plane) -> tuple[FloatArray, FloatArray, FloatArray]:
    width = plane.GetWidthAttr().Get() or 2.0
    length = plane.GetLengthAttr().Get() or 2.0
    axis = plane.GetAxisAttr().Get() or UsdGeom.Tokens.z
    hw, hl = float(width) / 2.0, float(length) / 2.0
    quad: list[tuple[float, float, float]]
    if axis == UsdGeom.Tokens.x:
        quad = [(0.0, -hw, -hl), (0.0, hw, -hl), (0.0, hw, hl), (0.0, -hw, hl)]
    elif axis == UsdGeom.Tokens.y:
        quad = [(-hw, 0.0, -hl), (-hw, 0.0, hl), (hw, 0.0, hl), (hw, 0.0, -hl)]
    else:
        quad = [(-hw, -hl, 0.0), (hw, -hl, 0.0), (hw, hl, 0.0), (-hw, hl, 0.0)]
    q = np.array(quad, dtype=np.float64)
    return q[[0, 0]], q[[1, 2]], q[[2, 3]]


def _instancer_footprints(
    instancer: UsdGeom.PointInstancer, world: FloatArray, up: int,
) -> tuple[FloatArray, FloatArray, FloatArray] | None:
    """Two footprint triangles per visible instance, from its prototype's box."""
    time = Usd.TimeCode.Default()
    proto_idx = instancer.GetProtoIndicesAttr().Get()
    if not proto_idx:
        return None
    proto_idx = np.asarray(proto_idx, dtype=np.int64)
    xforms = np.asarray(instancer.ComputeInstanceTransformsAtTime(
        time, time,
        UsdGeom.PointInstancer.IncludeProtoXform, UsdGeom.PointInstancer.IgnoreMask,
    ))
    if xforms.shape[0] != proto_idx.size:
        return None
    mask = instancer.ComputeMaskAtTime(time)
    keep = np.asarray(mask, dtype=bool) if mask else np.ones(proto_idx.size, dtype=bool)

    stage = instancer.GetPrim().GetStage()
    cache = bbox_cache(include_render=True, time=time)
    targets = instancer.GetPrototypesRel().GetTargets()
    lo = np.full((len(targets), 3), np.nan)
    hi = np.full((len(targets), 3), np.nan)
    for i, target in enumerate(targets):
        prim = stage.GetPrimAtPath(target)
        if not prim.IsValid():
            continue
        box = cache.ComputeUntransformedBound(prim).ComputeAlignedRange()
        if not box.IsEmpty():
            lo[i], hi[i] = box.GetMin(), box.GetMax()
    keep &= (proto_idx >= 0) & (proto_idx < len(targets))
    keep[keep] &= ~np.isnan(lo[proto_idx[keep], 0])
    if not keep.any():
        return None

    proto_idx = proto_idx[keep]
    matrices = xforms[keep] @ world
    rotation = matrices[:, :3, :3]
    half = (hi[proto_idx] - lo[proto_idx]) / 2.0
    center = np.einsum(
        "ni,nij->nj", (lo[proto_idx] + hi[proto_idx]) / 2.0, rotation,
    ) + matrices[:, 3, :3]
    lengths = np.linalg.norm(rotation, axis=2)
    upness = np.abs(rotation[:, :, up]) / np.maximum(lengths, SurfaceTuning.EPS)
    normal_axis = np.argmax(upness, axis=1)
    rows = np.arange(proto_idx.size)
    edge_a = half[rows, (normal_axis + 1) % 3, None] * rotation[rows, (normal_axis + 1) % 3]
    edge_b = half[rows, (normal_axis + 2) % 3, None] * rotation[rows, (normal_axis + 2) % 3]
    c0 = center + edge_a + edge_b
    c1 = center - edge_a + edge_b
    c2 = center - edge_a - edge_b
    c3 = center + edge_a - edge_b
    return np.concatenate([c0, c0]), np.concatenate([c1, c2]), np.concatenate([c2, c3])


def _to_world(points: FloatArray, matrix: FloatArray) -> FloatArray:
    return points @ matrix[:3, :3] + matrix[3, :3]


def _build_triangles(
    parts: list[tuple[FloatArray, FloatArray, FloatArray, bool]], up: int,
) -> SurfaceTriangles:
    if not parts:
        empty = np.zeros((0, 3))
        return SurfaceTriangles(v0=empty, v1=empty, v2=empty, normals=empty, areas=np.zeros(0))
    v0 = np.concatenate([p[0] for p in parts])
    v1 = np.concatenate([p[1] for p in parts])
    v2 = np.concatenate([p[2] for p in parts])
    double = np.concatenate([np.full(p[0].shape[0], p[3]) for p in parts])
    cross = np.cross(v1 - v0, v2 - v0)
    length = np.linalg.norm(cross, axis=1)
    keep = length > SurfaceTuning.EPS
    normals = cross[keep] / length[keep][:, None]
    return SurfaceTriangles(
        v0=v0[keep], v1=v1[keep], v2=v2[keep],
        normals=_orient_double_sided(normals, double[keep], up),
        areas=0.5 * length[keep],
    )


def _orient_double_sided(normals: FloatArray, double: BoolArray, up: int) -> FloatArray:
    """Double-sided faces have no back: point their normal to the upper hemisphere."""
    if not double.any():
        return normals
    out = normals.copy()
    flip = double & (out[:, up] < 0)
    out[flip] = -out[flip]
    return out


def _empty_index(triangles: SurfaceTriangles, up: int, axes: tuple[int, int]) -> SurfaceIndex:
    return SurfaceIndex(
        triangles=triangles, up=up, axes=axes, origin=np.zeros(2), cell=1.0, dims=(1, 1),
        cell_start=np.zeros(2, dtype=np.int64), cell_tris=np.zeros(0, dtype=np.int64),
    )


def _candidate_pairs(
    index: SurfaceIndex, qa: FloatArray, qb: FloatArray,
) -> tuple[IntArray, IntArray]:
    """Expand each query into the triangles registered in its grid cell."""
    ia = np.floor((qa - index.origin[0]) / index.cell).astype(np.int64)
    ib = np.floor((qb - index.origin[1]) / index.cell).astype(np.int64)
    valid = (ia >= 0) & (ia < index.dims[0]) & (ib >= 0) & (ib < index.dims[1])
    cell = np.where(valid, ia * index.dims[1] + ib, 0)
    start = index.cell_start[cell]
    counts = np.where(valid, index.cell_start[cell + 1] - start, 0)
    total = int(counts.sum())
    if total == 0:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty
    q = np.repeat(np.arange(qa.shape[0]), counts)
    offsets = np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
    t = index.cell_tris[np.repeat(start, counts) + offsets]
    return q, t


def _barycentric_2d(
    index: SurfaceIndex, t: IntArray, pa: FloatArray, pb: FloatArray,
) -> tuple[FloatArray, FloatArray, FloatArray, BoolArray]:
    a_ax, b_ax = index.axes
    triangles = index.triangles
    a0, b0 = triangles.v0[t, a_ax], triangles.v0[t, b_ax]
    a1, b1 = triangles.v1[t, a_ax], triangles.v1[t, b_ax]
    a2, b2 = triangles.v2[t, a_ax], triangles.v2[t, b_ax]
    det = (b1 - b2) * (a0 - a2) + (a2 - a1) * (b0 - b2)
    valid = np.abs(det) > SurfaceTuning.EPS
    safe = np.where(valid, det, 1.0)
    l0 = ((b1 - b2) * (pa - a2) + (a2 - a1) * (pb - b2)) / safe
    l1 = ((b2 - b0) * (pa - a2) + (a0 - a2) * (pb - b2)) / safe
    return l0, l1, 1.0 - l0 - l1, valid


def _distance_to_triangle_2d(
    index: SurfaceIndex, t: IntArray, pa: FloatArray, pb: FloatArray,
) -> FloatArray:
    """Plan-view distance from each point to its paired triangle's edges."""
    a_ax, b_ax = index.axes
    triangles = index.triangles
    verts = [
        (triangles.v0[t, a_ax], triangles.v0[t, b_ax]),
        (triangles.v1[t, a_ax], triangles.v1[t, b_ax]),
        (triangles.v2[t, a_ax], triangles.v2[t, b_ax]),
    ]
    best = np.full(pa.shape[0], np.inf)
    for (sa, sb), (ea, eb) in zip(verts, verts[1:] + verts[:1], strict=True):
        da, db = ea - sa, eb - sb
        length2 = da * da + db * db
        safe_length2 = np.where(length2 > SurfaceTuning.EPS, length2, 1.0)
        s = np.clip(((pa - sa) * da + (pb - sb) * db) / safe_length2, 0.0, 1.0)
        dist = np.hypot(pa - (sa + s * da), pb - (sb + s * db))
        best = np.minimum(best, dist)
    return best
