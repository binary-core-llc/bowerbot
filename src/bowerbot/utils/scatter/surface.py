# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""scatter_on_surface: eligible triangles, sampling, rows, and estimates."""

from __future__ import annotations

import math

import numpy as np

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import scatter
from bowerbot.utils import usd


def generate(
    surface: schemas.ScatterSurfaceParams,
    pose: schemas.ScatterPoseParams,
    *,
    triangles: schemas.SurfaceTriangles,
    avoid: schemas.SurfaceIndex | None,
    prototypes: list[schemas.ScatterPrototype],
    up: int,
    mpu: float,
    seed: int,
) -> tuple[schemas.ScatterInstanceSet, list[str]]:
    """Compute every instance of a scatter_on_surface call in world space."""
    rng = np.random.default_rng(seed)
    tri_mask = _require_eligible(triangles, up, surface)
    weights = [proto.weight for proto in prototypes]
    warnings: list[str] = []

    if surface.arrangement is schemas.ScatterArrangement.PILE:
        index = usd.surface.build_vertical_index(triangles, up, up_facing_only=True)
        count, center, radius = _pile_setup(surface)
        proto_idx = scatter.instances.pick_prototypes(
            rng, weights, count, schemas.ScatterAssetOrder.RANDOM,
        )
        scales = scatter.instances.random_scales(rng, pose.scale_range, count)
        positions, orientations, placed, base_radius = scatter.pile.heap(
            rng, index, prototypes, proto_idx, scales,
            up=up, center=center,
            radius=radius, repose_degrees=surface.repose_degrees,
            tilt_degrees=pose.tilt_jitter_degrees or constants.ScatterDefaults.PILE_TILT_DEGREES,
        )
        if not placed.all():
            warnings.append(
                f"{int((~placed).sum())} piece(s) found no surface under the pile "
                "region and were skipped.",
            )
        if base_radius > radius * 1.01:
            warnings.append(
                f"{count} pieces don't fit a {surface.repose_degrees:g}-degree "
                f"heap of radius {radius:g}, so it spread to a radius of "
                f"{base_radius:.2f}. Raise the radius or repose_degrees, or lower count.",
            )
        return schemas.ScatterInstanceSet(
            proto_indices=proto_idx[placed], positions=positions[placed],
            orientations=orientations[placed], scales=scales[placed],
        ), warnings

    accept = accept_probability(
        surface, avoid=avoid, up=up,
        noise_scale=_noise_scale(surface, triangles, up), seed=seed,
    )
    if surface.arrangement is schemas.ScatterArrangement.ROWS:
        contacts, tris = _rows_contacts(rng, surface, triangles, tri_mask, up)
        keep = rng.random(contacts.shape[0]) < accept(contacts, tris)
        contacts, tris = contacts[keep], tris[keep]
    else:
        contacts, tris, warnings = sample_points(
            rng, triangles, tri_mask, up=up, mpu=mpu, count=surface.count,
            density=surface.density, accept=accept, min_spacing=surface.min_spacing,
        )

    n = contacts.shape[0]
    normals = triangles.normals[tris]
    proto_idx = scatter.instances.pick_prototypes(rng, weights, n, schemas.ScatterAssetOrder.RANDOM)
    scales = scatter.instances.random_scales(rng, pose.scale_range, n)
    headings = scatter.instances.random_headings(rng, n, up, random_yaw=pose.random_yaw)
    index = usd.surface.build_vertical_index(triangles, up, up_facing_only=True)
    settle = np.ones(n, dtype=bool)
    if pose.align is schemas.ScatterAlign.SURFACE:
        base_min, base_max = scatter.instances.prototype_bases(prototypes, proto_idx)
        normals, settle = scatter.instances.ground_normals(
            index, contacts, headings, scales, base_min, base_max, normals, up,
        )
    orientations = scatter.instances.surface_orientations(
        rng, headings, normals, up, align=pose.align,
        tilt_jitter_degrees=pose.tilt_jitter_degrees,
    )
    positions = scatter.instances.rest_positions(
        contacts, orientations, scales, prototypes, proto_idx, up,
        embed=pose.embed, settle=settle, index=index,
    )
    return schemas.ScatterInstanceSet(
        proto_indices=proto_idx, positions=positions,
        orientations=orientations, scales=scales,
    ), warnings


def estimate(
    surface: schemas.ScatterSurfaceParams,
    *,
    triangles: schemas.SurfaceTriangles,
    avoid: schemas.SurfaceIndex | None,
    up: int,
    mpu: float,
    seed: int,
) -> tuple[int, float]:
    """Estimate ``(instances, eligible_area_m2)`` for validate_only."""
    rng = np.random.default_rng(seed)
    tri_mask = _require_eligible(triangles, up, surface)
    area_m2 = float((triangles.areas * tri_mask).sum()) * mpu * mpu * _eligible_share(
        np.random.default_rng([seed, 1]), surface, triangles, tri_mask, avoid, up,
    )
    if surface.arrangement is schemas.ScatterArrangement.PILE:
        count, _, _ = _pile_setup(surface)
        return count, area_m2
    accept = accept_probability(
        surface, avoid=avoid, up=up,
        noise_scale=_noise_scale(surface, triangles, up), seed=seed,
    )
    if surface.arrangement is schemas.ScatterArrangement.ROWS:
        contacts, tris = _rows_contacts(rng, surface, triangles, tri_mask, up)
        return int(round(float(accept(contacts, tris).sum()))), area_m2
    estimate, _ = estimate_count(
        rng, triangles, tri_mask, mpu=mpu, count=surface.count,
        density=surface.density, accept=accept,
    )
    return estimate, area_m2


def accept_probability(
    surface: schemas.ScatterSurfaceParams,
    *,
    avoid: schemas.SurfaceIndex | None,
    up: int,
    noise_scale: float,
    seed: int,
) -> schemas.ScatterAcceptance:
    """Build the per-point acceptance probability for scatter_on_surface."""
    axes = list(usd.metrics.horizontal_axes(up))
    region = surface.region

    def accept(points: schemas.FloatArray, _tris: schemas.IntArray) -> schemas.FloatArray:
        prob = scatter.region.mask(points, region, up).astype(np.float64)
        prob *= scatter.region.falloff(points, region, up)
        if avoid is not None and points.shape[0]:
            covered = usd.surface.plan_coverage(
                avoid, points[:, axes[0]], points[:, axes[1]], surface.avoid_margin,
            )
            prob[covered] = 0.0
        if surface.variation > 0:
            noise = scatter.noise.density(points, noise_scale, seed)
            prob *= (1.0 - surface.variation) + surface.variation * noise
        return prob

    return accept


def eligible_triangles(
    triangles: schemas.SurfaceTriangles,
    up: int,
    *,
    max_slope_degrees: float,
    region: schemas.ScatterRegion | None,
) -> schemas.BoolArray:
    """Triangles that are flat enough and overlap the region in plan view."""
    mask = usd.surface.slope_mask(triangles, up, max_slope_degrees)
    bounds = scatter.region.plan_bounds(region, up)
    if bounds is not None and triangles.count:
        axes = list(usd.metrics.horizontal_axes(up))
        tri = np.stack(
            [triangles.v0[:, axes], triangles.v1[:, axes], triangles.v2[:, axes]], axis=1,
        )
        lo, hi = tri.min(axis=1), tri.max(axis=1)
        overlap = np.all(hi >= bounds[0], axis=1) & np.all(lo <= bounds[1], axis=1)
        mask &= overlap
    return mask


def no_surface_message(
    triangles: schemas.SurfaceTriangles, up: int, max_slope_degrees: float,
) -> str:
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


def sample_points(
    rng: np.random.Generator,
    triangles: schemas.SurfaceTriangles,
    tri_mask: schemas.BoolArray,
    *,
    up: int,
    mpu: float,
    count: int | None,
    density: float | None,
    accept: schemas.ScatterAcceptance,
    min_spacing: float | None,
) -> tuple[schemas.FloatArray, schemas.IntArray, list[str]]:
    """Sample random surface points for a count or density."""
    weights = triangles.areas * tri_mask
    area = float(weights.sum())
    warnings: list[str] = []
    if count is not None:
        target = count
    elif density is not None:
        target = int(round(density * area * mpu * mpu))
    else:
        raise ValueError(constants.ScatterRules.COUNT_OR_DENSITY)
    if target > constants.ScatterRules.MAX_INSTANCES:
        msg = (
            f"this scatter would create about {target:,} instances; the maximum "
            f"per call is {constants.ScatterRules.MAX_INSTANCES:,}. Lower the density or count, "
            "or split the area with regions."
        )
        raise ValueError(msg)
    if target == 0:
        return np.zeros((0, 3)), np.zeros(0, dtype=np.int64), [
            "density x area rounds to zero instances; raise the density.",
        ]

    if min_spacing is not None:
        pool = min(
            max(target * constants.ScatterTuning.SPACING_OVERSAMPLE, 1024),
            constants.ScatterTuning.MAX_SPACING_CANDIDATES,
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


def estimate_count(
    rng: np.random.Generator,
    triangles: schemas.SurfaceTriangles,
    tri_mask: schemas.BoolArray,
    *,
    mpu: float,
    count: int | None,
    density: float | None,
    accept: schemas.ScatterAcceptance,
) -> tuple[int, float]:
    """Estimate ``(instances, eligible_area_m2)`` without generating the scatter."""
    weights = triangles.areas * tri_mask
    area_m2 = float(weights.sum()) * mpu * mpu
    if count is not None:
        return count, area_m2
    if density is None:
        raise ValueError(constants.ScatterRules.COUNT_OR_DENSITY)
    raw = density * area_m2
    probe = min(int(raw) + 1, 20_000)
    points, tris = usd.surface.sample_on_triangles(rng, triangles, weights, probe)
    rate = float(np.mean(accept(points, tris))) if probe else 0.0
    return int(round(raw * rate)), area_m2


def rows_plan_points(
    rng: np.random.Generator,
    lo: schemas.FloatArray,
    hi: schemas.FloatArray,
    *,
    spacing: float,
    row_spacing: float,
    direction_degrees: float,
    jitter: float,
) -> schemas.FloatArray:
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
    if us.size * vs.size > constants.ScatterRules.MAX_INSTANCES:
        msg = (
            f"rows would create {us.size * vs.size:,} lattice points; the maximum "
            f"is {constants.ScatterRules.MAX_INSTANCES:,}. "
            "Increase spacing/row_spacing or add a region."
        )
        raise ValueError(msg)
    uu, vv = np.meshgrid(us, vs, indexing="ij")
    plan = uu.reshape(-1, 1) * along + vv.reshape(-1, 1) * across
    if jitter > 0:
        plan += rng.uniform(-jitter, jitter, plan.shape)
    return plan


def plan_to_world(plan: schemas.FloatArray, up: int, height: float = 0.0) -> schemas.FloatArray:
    """Lift plan-view points to 3D at *height* on the up axis."""
    axes = list(usd.metrics.horizontal_axes(up))
    pts = np.full((plan.shape[0], 3), height, dtype=np.float64)
    pts[:, axes] = plan
    return pts


# ── Helpers ──


def _require_eligible(
    triangles: schemas.SurfaceTriangles, up: int, surface: schemas.ScatterSurfaceParams,
) -> schemas.BoolArray:
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


def _noise_scale(
    surface: schemas.ScatterSurfaceParams, triangles: schemas.SurfaceTriangles, up: int,
) -> float:
    """Variation feature size: explicit, else a fifth of the covered extent."""
    if surface.variation_scale is not None:
        return surface.variation_scale
    bounds = (
        scatter.region.plan_bounds(surface.region, up)
        or usd.surface.plan_bounds(triangles, up)
    )
    return max(float(np.max(bounds[1] - bounds[0])) / 5.0, 1e-6)


def _rows_contacts(
    rng: np.random.Generator,
    surface: schemas.ScatterSurfaceParams,
    triangles: schemas.SurfaceTriangles,
    tri_mask: schemas.BoolArray,
    up: int,
) -> tuple[schemas.FloatArray, schemas.IntArray]:
    """Row lattice points projected straight down onto the top surface."""
    if surface.spacing is None or surface.row_spacing is None:
        msg = "arrangement 'rows' needs spacing and row_spacing."
        raise ValueError(msg)
    lo, hi = (
        scatter.region.plan_bounds(surface.region, up)
        or usd.surface.plan_bounds(triangles, up)
    )
    plan = rows_plan_points(
        rng, lo, hi, spacing=surface.spacing, row_spacing=surface.row_spacing,
        direction_degrees=surface.row_direction_degrees, jitter=surface.jitter,
    )
    points = plan_to_world(plan, up)
    index = usd.surface.build_vertical_index(triangles, up, up_facing_only=True)
    hit, heights, tris = usd.surface.surface_under(index, points, mode="top")
    ok = hit.copy()
    ok[hit] = tri_mask[tris[hit]]
    points = points[ok]
    points[:, up] = heights[ok]
    return points, tris[ok]


def _accepted_samples(
    rng: np.random.Generator,
    triangles: schemas.SurfaceTriangles,
    weights: schemas.FloatArray,
    target: int,
    accept: schemas.ScatterAcceptance,
    *,
    exact: bool,
) -> tuple[schemas.FloatArray, schemas.IntArray]:
    """Sample then thin by *accept*; with *exact*, keep sampling until *target*."""
    batch = target
    kept_pts: list[schemas.FloatArray] = []
    kept_tris: list[schemas.IntArray] = []
    got = 0
    for _ in range(constants.ScatterTuning.MAX_SAMPLE_ROUNDS if exact else 1):
        points, tris = usd.surface.sample_on_triangles(rng, triangles, weights, batch)
        prob = accept(points, tris)
        keep = rng.random(points.shape[0]) < prob
        kept_pts.append(points[keep])
        kept_tris.append(tris[keep])
        got += int(keep.sum())
        if not exact or got >= target:
            break
        rate = max(float(keep.mean()) if keep.size else 0.0, 1e-3)
        batch = int(min(
            max((target - got) / rate * 1.25, 1024), constants.ScatterTuning.MAX_SAMPLE_BATCH,
        ))
    points = np.concatenate(kept_pts) if kept_pts else np.zeros((0, 3))
    tris = np.concatenate(kept_tris) if kept_tris else np.zeros(0, dtype=np.int64)
    if exact:
        return points[:target], tris[:target]
    return points, tris


def _eligible_share(
    rng: np.random.Generator,
    surface: schemas.ScatterSurfaceParams,
    triangles: schemas.SurfaceTriangles,
    tri_mask: schemas.BoolArray,
    avoid: schemas.SurfaceIndex | None,
    up: int,
) -> float:
    """Share of the eligible area inside the region and clear of avoid."""
    if surface.region is None and avoid is None:
        return 1.0
    points, _ = usd.surface.sample_on_triangles(
        rng, triangles, triangles.areas * tri_mask, constants.ScatterTuning.AREA_PROBE,
    )
    if points.shape[0] == 0:
        return 0.0
    keep = scatter.region.mask(points, surface.region, up)
    if avoid is not None:
        axes = list(usd.metrics.horizontal_axes(up))
        keep &= ~usd.surface.plan_coverage(
            avoid, points[:, axes[0]], points[:, axes[1]], surface.avoid_margin,
        )
    return float(keep.mean())


def _greedy_min_spacing(
    points: schemas.FloatArray, spacing: float, limit: int,
) -> schemas.FloatArray:
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


def _pile_setup(surface: schemas.ScatterSurfaceParams) -> tuple[int, schemas.FloatArray, float]:
    """A pile's piece count, centre and base radius."""
    region = surface.region
    if surface.count is None or region is None or region.polygon is not None:
        msg = "arrangement 'pile' needs a count and a circular region."
        raise ValueError(msg)
    center, radius = scatter.region.circle(region)
    return surface.count, center, radius
