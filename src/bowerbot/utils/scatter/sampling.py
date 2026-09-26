# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter sampling — random points on eligible surfaces, with spacing and acceptance."""

from __future__ import annotations

import numpy as np

from bowerbot.schemas import (
    ScatterRegion,
    ScatterRules,
    ScatterSurfaceParams,
    ScatterTuning,
    SurfaceIndex,
    SurfaceTriangles,
)
from bowerbot.schemas.scatter import ScatterAcceptance
from bowerbot.schemas.surface import BoolArray, FloatArray, IntArray
from bowerbot.utils import surface_utils
from bowerbot.utils.core.metrics import horizontal_axes
from bowerbot.utils.scatter.noise import density_noise
from bowerbot.utils.scatter.regions import region_falloff, region_mask, region_plan_bounds


def surface_on_accept(
    surface: ScatterSurfaceParams,
    *,
    avoid: SurfaceIndex | None,
    up: int,
    noise_scale: float,
    seed: int,
) -> ScatterAcceptance:
    """Build the per-point acceptance probability for scatter_on_surface."""
    axes = list(horizontal_axes(up))
    region = surface.region

    def accept(points: FloatArray, _tris: IntArray) -> FloatArray:
        prob = region_mask(points, region, up).astype(np.float64)
        prob *= region_falloff(points, region, up)
        if avoid is not None and points.shape[0]:
            covered = surface_utils.plan_coverage(
                avoid, points[:, axes[0]], points[:, axes[1]], surface.avoid_margin,
            )
            prob[covered] = 0.0
        if surface.variation > 0:
            noise = density_noise(points, noise_scale, seed)
            prob *= (1.0 - surface.variation) + surface.variation * noise
        return prob

    return accept


def eligible_triangles(
    triangles: SurfaceTriangles,
    up: int,
    *,
    max_slope_degrees: float,
    region: ScatterRegion | None,
) -> BoolArray:
    """Triangles that are flat enough and overlap the region in plan view."""
    mask = surface_utils.slope_mask(triangles, up, max_slope_degrees)
    bounds = region_plan_bounds(region, up)
    if bounds is not None and triangles.count:
        axes = list(horizontal_axes(up))
        tri = np.stack(
            [triangles.v0[:, axes], triangles.v1[:, axes], triangles.v2[:, axes]], axis=1,
        )
        lo, hi = tri.min(axis=1), tri.max(axis=1)
        overlap = np.all(hi >= bounds[0], axis=1) & np.all(lo <= bounds[1], axis=1)
        mask &= overlap
    return mask


def no_surface_message(triangles: SurfaceTriangles, up: int, max_slope_degrees: float) -> str:
    """Explain why no triangle qualified, pointing at the likely fix."""
    if triangles.count == 0:
        return (
            "the surface prims contain no Mesh/Cube/Sphere/Plane geometry (a "
            "scatter can't be a surface). Use list_prim_children to find the "
            "mesh parts to scatter onto."
        )
    facing_down = int((triangles.normals[:, up] < 0).sum())
    msg = (
        f"no surface area is within max_slope_degrees={max_slope_degrees:g} of up "
        "inside the region."
    )
    if facing_down > triangles.count // 2:
        msg += (
            f" {facing_down} of {triangles.count} faces point downward; the mesh's "
            "normals may be flipped, or the target is the underside of something. "
            "Raise max_slope_degrees to 180 to cover every face."
        )
    return msg


def scatter_surface_points(
    rng: np.random.Generator,
    triangles: SurfaceTriangles,
    tri_mask: BoolArray,
    *,
    up: int,
    mpu: float,
    count: int | None,
    density: float | None,
    accept: ScatterAcceptance,
    min_spacing: float | None,
) -> tuple[FloatArray, IntArray, list[str]]:
    """Sample random surface points for a count or density."""
    weights = triangles.areas * tri_mask
    area = float(weights.sum())
    warnings: list[str] = []
    if count is not None:
        target = count
    else:
        target = int(round(_require_density(density) * area * mpu * mpu))
    if target > ScatterRules.MAX_INSTANCES:
        msg = (
            f"this scatter would create about {target:,} instances; the maximum "
            f"per call is {ScatterRules.MAX_INSTANCES:,}. Lower the density or count, "
            "or split the area with regions."
        )
        raise ValueError(msg)
    if target == 0:
        return np.zeros((0, 3)), np.zeros(0, dtype=np.int64), [
            "density x area rounds to zero instances; raise the density.",
        ]

    if min_spacing is not None:
        pool = min(
            max(target * ScatterTuning.SPACING_OVERSAMPLE, 1024),
            ScatterTuning.MAX_SPACING_CANDIDATES,
        )
        points, tris = _accepted_samples(rng, triangles, weights, pool, accept, exact=True)
        keep = _greedy_min_spacing(points, min_spacing, target)
        if keep.size < target:
            warnings.append(
                f"only {keep.size} of {target} instances fit with "
                f"min_spacing={min_spacing:g}; lower min_spacing or the count.",
            )
        return points[keep], tris[keep], warnings

    exact = count is not None
    points, tris = _accepted_samples(rng, triangles, weights, target, accept, exact=exact)
    if exact and points.shape[0] < target:
        warnings.append(
            f"only {points.shape[0]} of {target} instances found room; the region, "
            "avoid list or variation leaves too little eligible surface.",
        )
    return points, tris, warnings


def estimate_surface_count(
    rng: np.random.Generator,
    triangles: SurfaceTriangles,
    tri_mask: BoolArray,
    *,
    mpu: float,
    count: int | None,
    density: float | None,
    accept: ScatterAcceptance,
) -> tuple[int, float]:
    """Estimate ``(instances, eligible_area_m2)`` without generating the scatter."""
    weights = triangles.areas * tri_mask
    area_m2 = float(weights.sum()) * mpu * mpu
    if count is not None:
        return count, area_m2
    raw = _require_density(density) * area_m2
    probe = min(int(raw) + 1, ScatterTuning.PROBE_SAMPLES)
    points, tris = surface_utils.sample_on_triangles(rng, triangles, weights, probe)
    rate = float(np.mean(accept(points, tris))) if probe else 0.0
    return int(round(raw * rate)), area_m2


def require_eligible(
    triangles: SurfaceTriangles, up: int, surface: ScatterSurfaceParams,
) -> BoolArray:
    """Eligible-triangle mask, refusing with a diagnosis when nothing qualifies."""
    mask = eligible_triangles(
        triangles, up, max_slope_degrees=surface.max_slope_degrees, region=surface.region,
    )
    if not mask.any():
        msg = "Nothing to scatter onto: " + no_surface_message(
            triangles, up, surface.max_slope_degrees,
        )
        raise ValueError(msg)
    return mask


def _accepted_samples(
    rng: np.random.Generator,
    triangles: SurfaceTriangles,
    weights: FloatArray,
    target: int,
    accept: ScatterAcceptance,
    *,
    exact: bool,
) -> tuple[FloatArray, IntArray]:
    """Sample then thin by *accept*; with *exact*, keep sampling until *target*."""
    batch = target
    kept_pts: list[FloatArray] = []
    kept_tris: list[IntArray] = []
    got = 0
    for _ in range(ScatterTuning.MAX_SAMPLE_ROUNDS if exact else 1):
        points, tris = surface_utils.sample_on_triangles(rng, triangles, weights, batch)
        prob = accept(points, tris)
        keep = rng.random(points.shape[0]) < prob
        kept_pts.append(points[keep])
        kept_tris.append(tris[keep])
        got += int(keep.sum())
        if not exact or got >= target:
            break
        rate = max(float(keep.mean()) if keep.size else 0.0, 1e-3)
        batch = int(min(max((target - got) / rate * 1.25, 1024), ScatterTuning.MAX_SAMPLE_BATCH))
    points = np.concatenate(kept_pts) if kept_pts else np.zeros((0, 3))
    tris = np.concatenate(kept_tris) if kept_tris else np.zeros(0, dtype=np.int64)
    if exact:
        return points[:target], tris[:target]
    return points, tris


def eligible_share(
    rng: np.random.Generator,
    surface: ScatterSurfaceParams,
    triangles: SurfaceTriangles,
    tri_mask: BoolArray,
    avoid: SurfaceIndex | None,
    up: int,
) -> float:
    """Share of the eligible area inside the region and clear of avoid."""
    if surface.region is None and avoid is None:
        return 1.0
    points, _ = surface_utils.sample_on_triangles(
        rng, triangles, triangles.areas * tri_mask, ScatterTuning.PROBE_SAMPLES,
    )
    if points.shape[0] == 0:
        return 0.0
    keep = region_mask(points, surface.region, up)
    if avoid is not None:
        axes = list(horizontal_axes(up))
        keep &= ~surface_utils.plan_coverage(
            avoid, points[:, axes[0]], points[:, axes[1]], surface.avoid_margin,
        )
    return float(keep.mean())


def _greedy_min_spacing(points: FloatArray, spacing: float, limit: int) -> FloatArray:
    """Keep points in order unless one already kept lies closer than *spacing*."""
    cell = spacing
    r2 = spacing * spacing
    keys = np.floor(points / cell).astype(np.int64).tolist()
    coords = points.tolist()
    grid: dict[tuple[int, int, int], list[int]] = {}
    neighbours = [(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)]
    kept: list[int] = []
    for i, (px, py, pz) in enumerate(coords):
        kx, ky, kz = keys[i]
        clear = True
        for dx, dy, dz in neighbours:
            bucket = grid.get((kx + dx, ky + dy, kz + dz))
            if not bucket:
                continue
            for j in bucket:
                qx, qy, qz = coords[j]
                if (px - qx) ** 2 + (py - qy) ** 2 + (pz - qz) ** 2 < r2:
                    clear = False
                    break
            if not clear:
                break
        if clear:
            kept.append(i)
            grid.setdefault((kx, ky, kz), []).append(i)
            if len(kept) >= limit:
                break
    return np.asarray(kept, dtype=np.int64)


def _require_density(density: float | None) -> float:
    """*density*, which a surface scatter needs when no count is given."""
    if density is None:
        msg = "a surface scatter needs a count or a density."
        raise ValueError(msg)
    return density
