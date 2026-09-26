# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter utils — surface and path distributions, resting, orientation, and authoring."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, Vt

from bowerbot.schemas import (
    AssetMetadata,
    ScatterAlign,
    ScatterArrangement,
    ScatterAsset,
    ScatterAssetOrder,
    ScatterDropAlign,
    ScatterInstanceSet,
    ScatterNamespace,
    ScatterOutput,
    ScatterPathCircle,
    ScatterPathFacing,
    ScatterPathParams,
    ScatterPathSide,
    ScatterPoseParams,
    ScatterPrototype,
    ScatterRegion,
    ScatterRegionFalloff,
    ScatterRules,
    ScatterSurfaceParams,
    SceneObject,
    SurfaceIndex,
    SurfaceTriangles,
)
from bowerbot.schemas.surface import BoolArray, FloatArray, IntArray
from bowerbot.schemas.transforms import Vec3
from bowerbot.utils import asset_intake_utils, layout_utils, surface_utils
from bowerbot.utils.core.asset_folder import parse_nested_contents_path
from bowerbot.utils.core.bounds import bbox_cache, prim_world_box, world_bounds, world_range
from bowerbot.utils.core.metrics import asset_conform, axis_index, horizontal_axes, up_vector
from bowerbot.utils.core.naming import is_valid_prim_name, safe_prim_name
from bowerbot.utils.core.references import add_references, get_prim_ref_paths
from bowerbot.utils.core.transforms import extract_position, gf_matrix_to_numpy
from bowerbot.utils.core.values import to_vec3

# Keep-probability per sampled point, given its position and triangle.
_Acceptance = Callable[[FloatArray, IntArray], FloatArray]

_PATH_SEGMENTS = 256
_COUNT_OR_DENSITY = "a surface scatter needs a count or a density."
_MAX_SAMPLE_ROUNDS = 24
_MAX_SAMPLE_BATCH = 2_000_000
_SPACING_OVERSAMPLE = 6
_MAX_SPACING_CANDIDATES = 400_000
_MAX_PILE_PIECES = 20_000
# Instance count above which a scatter warns about scene.usda size.
_LARGE_SCATTER = 100_000
# Samples used to measure the area a region or avoid list leaves.
_AREA_PROBE = 20_000
# Share of a model's height treated as its base.
_BASE_SLICE = 0.05
_BASE_GRID = 3
# Steepest face whose ground is plane-fitted from above.
_FIT_MAX_SLOPE_DEGREES = 60.0
_STRANDED_REPORT = 20
_EPS = 1e-9
_PILE_GRID = 400
# Pile drops tried per piece, and base growth when none fits the cone.
_PILE_TRIES = 16
_PILE_GROWTH = 1.05
_PILE_GROWTH_STEPS = 4
# Default pile tilt off the flattest side, degrees.
_PILE_TILT_DEGREES = 10.0
# Share of a piece's box it fills; sizes the pile heightfield.
_PILE_SOLIDITY = 0.5
# Vertices sampled per prototype.
_SHAPE_POINTS = 1500
_DROP_FOOTPRINT = 3
# Bytes one instance adds to an ASCII .usda layer.
_ASCII_BYTES_PER_INSTANCE = 116


# ── parameters and naming ──


def scatter_prim_path(group: str, name: str) -> str:
    """``/Scene/<group>/<name>`` for a scatter, validating both parts."""
    group_path = layout_utils.scene_group_path(group)
    prim_name = safe_prim_name(name)
    if not is_valid_prim_name(prim_name):
        msg = (
            f"name '{name}' is not a valid USD prim name (letters, digits, "
            "underscores; must start with a letter or underscore)."
        )
        raise ValueError(msg)
    return f"{group_path}/{prim_name}"


def check_target(stage: Usd.Stage, prim_path: str, *, replace: bool) -> bool:
    """Return whether *prim_path* exists; refuse when it does and *replace* is off."""
    exists = bool(stage.GetPrimAtPath(prim_path).IsValid())
    if exists and not replace:
        msg = (
            f"{prim_path} already exists. Pass replace=true to regenerate it "
            "(same seed gives the same result), or choose another name."
        )
        raise ValueError(msg)
    return exists


def derive_seed(prim_path: str, seed: int | None) -> int:
    """The explicit *seed*, or a stable one derived from the scatter's path."""
    if seed is not None:
        return seed
    digest = hashlib.blake2b(prim_path.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "little")


def parse_scale_range(raw: list[float] | None) -> tuple[float, float]:
    """Validate a ``[min, max]`` scale range (default no scaling)."""
    if raw is None:
        return 1.0, 1.0
    low, high = float(raw[0]), float(raw[1])
    if low > high:
        msg = "'scale_range' must be [min, max] with min <= max."
        raise ValueError(msg)
    return low, high


def parse_region(
    stage: Usd.Stage, raw: dict[str, Any] | None, up: int,
) -> ScatterRegion | None:
    """Validate a raw ``region`` and resolve its ``center_prim`` to a centre point."""
    if raw is None:
        return None
    falloff = ScatterRegionFalloff(raw.get("falloff", ScatterRegionFalloff.NONE))
    polygon = raw.get("polygon")
    if polygon is not None:
        if any(raw.get(key) is not None for key in ("center", "center_prim", "radius")):
            msg = (
                "region is either a polygon or a circle "
                "(center/center_prim + radius), not both."
            )
            raise ValueError(msg)
        return ScatterRegion(polygon=[tuple(point) for point in polygon], falloff=falloff)
    if raw.get("radius") is None:
        msg = "a circular region needs 'radius'."
        raise ValueError(msg)
    center = _circle_center(stage, raw, up, "a circular region")
    return ScatterRegion(center=center, radius=float(raw["radius"]), falloff=falloff)


def parse_path_circle(
    stage: Usd.Stage, raw: dict[str, Any] | None, up: int,
) -> ScatterPathCircle | None:
    """Validate a raw path ``circle`` and resolve its ``center_prim`` to a centre point."""
    if raw is None:
        return None
    return ScatterPathCircle(
        center=_circle_center(stage, raw, up, "'circle'"),
        radius=float(raw["radius"]),
        start_angle_degrees=float(raw.get("start_angle_degrees", 0.0)),
    )


# ── assets and prototypes ──


def resolve_asset_sources(
    assets: list[ScatterAsset],
    *,
    project_dir: Path | None,
    library_dir: Path | None,
) -> list[tuple[ScatterAsset, Path]]:
    """Resolve every asset in the mix to a root file, reporting all problems at once."""
    problems: list[str] = []
    resolved: list[tuple[ScatterAsset, Path]] = []
    targets: dict[str, Path] = {}
    for idx, entry in enumerate(assets):
        try:
            path = layout_utils.resolve_layout_asset(
                entry.asset, layout_dir=None,
                project_dir=project_dir, library_dir=library_dir,
            )
        except ValueError as e:
            problems.append(f"assets[{idx}]: {e}")
            continue
        target = asset_intake_utils.intake_target_name(path, library_dir)
        prior = targets.setdefault(target, path)
        if prior != path:
            problems.append(
                f"assets[{idx}]: '{path}' and '{prior}' would both stage to "
                f"assets/{target}; rename one source.",
            )
            continue
        resolved.append((entry, path))
    if problems:
        summary = f"scatter assets could not be resolved ({len(problems)} problem(s)):"
        raise ValueError("\n".join([summary, *problems]))
    return resolved


def stage_prototypes(
    stage: Usd.Stage,
    sources: list[tuple[ScatterAsset, Path]],
    *,
    assets_dir: Path,
    library_dir: Path | None,
    project_dir: Path,
) -> list[ScatterPrototype]:
    """Intake every source into the project and measure its conformed bounds."""
    fix_prim: dict[Path, bool] = {}
    fix_xform: dict[Path, bool] = {}
    for entry, path in sources:
        fix_prim[path] = fix_prim.get(path, False) or entry.fix_root_prim
        fix_xform[path] = fix_xform.get(path, False) or entry.fix_root_transforms

    reports: dict[Path, Any] = {}
    problems: list[str] = []
    for path in fix_prim:
        try:
            reports[path] = asset_intake_utils.prepare_asset(
                path, assets_dir, library_dir=library_dir,
                fix_root_prim=fix_prim[path], fix_root_transforms=fix_xform[path],
            )
        except (ValueError, RuntimeError) as e:
            problems.append(f"{path.name}: {e}")
    if problems:
        summary = f"asset intake failed ({len(problems)} asset(s)):"
        raise ValueError("\n".join([summary, *problems]))

    up = axis_index(UsdGeom.GetStageUpAxis(stage))
    prototypes: list[ScatterPrototype] = []
    used: set[str] = set()
    for entry, path in sources:
        report = reports[path]
        unit_scale, correction = asset_conform(stage, report.scene_ref_path)
        bmin, bmax, base_min, base_max, points = _conformed_extents(
            project_dir / report.scene_ref_path, unit_scale, correction, up,
        )
        base = safe_prim_name(Path(report.asset_folder_name).stem) or "proto"
        if not is_valid_prim_name(base):
            base = f"proto_{base}"
        name = base
        n = 2
        while name in used:
            name = f"{base}_{n}"
            n += 1
        used.add(name)
        prototypes.append(ScatterPrototype(
            name=name, source=str(path), scene_ref=report.scene_ref_path,
            weight=entry.weight,
            bounds_min=tuple(bmin.tolist()), bounds_max=tuple(bmax.tolist()),
            base_min=tuple(base_min.tolist()), base_max=tuple(base_max.tolist()),
            points=points,
        ))
    return prototypes


def pick_prototypes(
    rng: np.random.Generator, weights: list[float], n: int, order: ScatterAssetOrder,
) -> IntArray:
    """Prototype index per instance: weighted random, or cycling in order."""
    if order is ScatterAssetOrder.CYCLE:
        return np.arange(n, dtype=np.int64) % len(weights)
    w = np.asarray(weights, dtype=np.float64)
    return rng.choice(len(weights), size=n, p=w / w.sum()).astype(np.int64)


def random_scales(
    rng: np.random.Generator, scale_range: tuple[float, float], n: int,
) -> FloatArray:
    """Uniform per-instance scale within *scale_range*, as (n, 3)."""
    low, high = scale_range
    s = rng.uniform(low, high, n) if high > low else np.full(n, low)
    return np.repeat(s[:, None], 3, axis=1)


def side_signs(sides: ScatterPathSide) -> list[int]:
    """Lateral offset signs (+1 left, -1 right, 0 on the line) for *sides*."""
    return {
        ScatterPathSide.CENTER: [0],
        ScatterPathSide.LEFT: [1],
        ScatterPathSide.RIGHT: [-1],
        ScatterPathSide.BOTH: [1, -1],
    }[sides]


def surface_on_accept(
    surface: ScatterSurfaceParams,
    *,
    avoid: SurfaceIndex | None,
    up: int,
    noise_scale: float,
    seed: int,
) -> _Acceptance:
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


# ── regions ──


def region_mask(points: FloatArray, region: ScatterRegion | None, up: int) -> BoolArray:
    """Which *points* fall inside *region* in plan view."""
    if region is None:
        return np.ones(points.shape[0], dtype=bool)
    axes = list(horizontal_axes(up))
    if region.polygon is not None:
        polygon = np.asarray(region.polygon, dtype=np.float64)[:, axes]
        return _point_in_polygon(points[:, axes], polygon)
    center, radius = _region_circle(region)
    return _plan_distance(points, center, up) <= radius


def region_falloff(points: FloatArray, region: ScatterRegion | None, up: int) -> FloatArray:
    """Density multiplier fading from a circular region's centre to its edge."""
    if region is None or region.polygon is not None or region.falloff is ScatterRegionFalloff.NONE:
        return np.ones(points.shape[0])
    center, radius = _region_circle(region)
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


# ── density variation ──


def density_noise(points: FloatArray, scale: float, seed: int) -> FloatArray:
    """Smooth, seeded 3D noise in [0, 1] with features about *scale* across."""
    total = np.zeros(points.shape[0])
    amp_sum = 0.0
    for octave in range(3):
        freq = 2.0 ** octave
        amp = 0.5 ** octave
        offset = 17.31 * (octave + 1)
        total += amp * _value_noise(points * (freq / scale) + offset, seed + octave)
        amp_sum += amp
    n = total / amp_sum
    n = np.clip((n - 0.5) * 2.5 + 0.5, 0.0, 1.0)
    return n * n * (3.0 - 2.0 * n)


# ── surface distributions ──


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
    accept: _Acceptance,
    min_spacing: float | None,
) -> tuple[FloatArray, IntArray, list[str]]:
    """Sample random surface points for a count or density."""
    weights = triangles.areas * tri_mask
    area = float(weights.sum())
    warnings: list[str] = []
    if count is not None:
        target = count
    elif density is not None:
        target = int(round(density * area * mpu * mpu))
    else:
        raise ValueError(_COUNT_OR_DENSITY)
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
        pool = min(max(target * _SPACING_OVERSAMPLE, 1024), _MAX_SPACING_CANDIDATES)
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
    accept: _Acceptance,
) -> tuple[int, float]:
    """Estimate ``(instances, eligible_area_m2)`` without generating the scatter."""
    weights = triangles.areas * tri_mask
    area_m2 = float(weights.sum()) * mpu * mpu
    if count is not None:
        return count, area_m2
    if density is None:
        raise ValueError(_COUNT_OR_DENSITY)
    raw = density * area_m2
    probe = min(int(raw) + 1, 20_000)
    points, tris = surface_utils.sample_on_triangles(rng, triangles, weights, probe)
    rate = float(np.mean(accept(points, tris))) if probe else 0.0
    return int(round(raw * rate)), area_m2


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


def plan_to_world(plan: FloatArray, up: int, height: float = 0.0) -> FloatArray:
    """Lift plan-view points to 3D at *height* on the up axis."""
    axes = list(horizontal_axes(up))
    pts = np.full((plan.shape[0], 3), height, dtype=np.float64)
    pts[:, axes] = plan
    return pts


def pile_instances(
    rng: np.random.Generator,
    index: SurfaceIndex,
    prototypes: list[ScatterPrototype],
    proto_idx: IntArray,
    scales: FloatArray,
    *,
    up: int,
    center: FloatArray,
    radius: float,
    repose_degrees: float,
    tilt_degrees: float,
) -> tuple[FloatArray, FloatArray, BoolArray, float]:
    """Heap pieces under a repose cone, resting on the ground and on each other."""
    n = proto_idx.shape[0]
    if n > _MAX_PILE_PIECES:
        msg = f"a pile holds at most {_MAX_PILE_PIECES:,} pieces per call."
        raise ValueError(msg)
    axes = list(horizontal_axes(up))
    slope = math.tan(math.radians(repose_degrees))
    orientations = pile_orientations(rng, prototypes, proto_idx, up, tilt_degrees)

    extents = np.array([np.subtract(p.bounds_max, p.bounds_min) for p in prototypes])
    sizes = extents[proto_idx] * scales
    reach = float(sizes.max())
    volume = float(np.prod(sizes, axis=1).sum()) * _PILE_SOLIDITY
    natural = (3.0 * volume / (math.pi * max(slope, 1e-3))) ** (1.0 / 3.0)
    half = max(radius, 1.5 * natural) + reach
    cell = max(float(sizes.min()) / 4.0, 2.0 * half / _PILE_GRID)
    dims = int(2.0 * half / cell) + 1
    c_plan = center[axes]
    origin = c_plan - half
    ga = origin[0] + (np.arange(dims) + 0.5) * cell
    gb = origin[1] + (np.arange(dims) + 0.5) * cell
    aa, bb = np.meshgrid(ga, gb, indexing="ij")
    probe = plan_to_world(np.stack([aa.ravel(), bb.ravel()], axis=1), up)
    hit, heights, _ = surface_utils.surface_under(index, probe, mode="top")
    field = np.where(hit, heights, np.nan).reshape(dims, dims)
    if np.isnan(field).all():
        msg = "no surface lies under the pile region; check the region centre and surfaces."
        raise ValueError(msg)
    ground = field.copy()
    distance = np.hypot(aa - c_plan[0], bb - c_plan[1])

    positions = np.zeros((n, 3))
    placed = np.zeros(n, dtype=bool)
    base_radius = radius
    max_radius = half - reach
    for i in range(n):
        proto = prototypes[int(proto_idx[i])]
        pts = quat_rotate(
            np.repeat(orientations[i:i + 1], proto.points.shape[0], axis=0),
            proto.points * scales[i],
        )
        # Piece underside and top per heightfield cell, around a cell-centred pivot.
        da = np.floor(pts[:, axes[0]] / cell + 0.5).astype(np.int64)
        db = np.floor(pts[:, axes[1]] / cell + 0.5).astype(np.int64)
        cells, inverse = np.unique(np.stack([da, db], axis=1), axis=0, return_inverse=True)
        inverse = inverse.ravel()
        under = np.full(cells.shape[0], np.inf)
        over = np.full(cells.shape[0], -np.inf)
        np.minimum.at(under, inverse, pts[:, up])
        np.maximum.at(over, inverse, pts[:, up])
        lowest = float(under.min())

        best: tuple[float, int, int, float] | None = None
        for _ in range(_PILE_GROWTH_STEPS):
            dist = base_radius * np.sqrt(rng.random(_PILE_TRIES))
            angle = rng.random(_PILE_TRIES) * 2.0 * math.pi
            ia = np.floor((c_plan[0] + dist * np.cos(angle) - origin[0]) / cell).astype(np.int64)
            ib = np.floor((c_plan[1] + dist * np.sin(angle) - origin[1]) / cell).astype(np.int64)
            ca = ia[:, None] + cells[None, :, 0]
            cb = ib[:, None] + cells[None, :, 1]
            inside = ((ca >= 0) & (ca < dims) & (cb >= 0) & (cb < dims)).all(axis=1)
            below = field[np.clip(ca, 0, dims - 1), np.clip(cb, 0, dims - 1)]
            valid = inside & ~np.isnan(below).any(axis=1)
            if not valid.any():
                continue
            rest = np.where(valid, (below - under[None, :]).max(axis=1), np.inf)
            env = (
                ground[ia.clip(0, dims - 1), ib.clip(0, dims - 1)]
                + np.maximum(base_radius - distance[ia.clip(0, dims - 1), ib.clip(0, dims - 1)],
                             0.0) * slope
            )
            excess = np.where(valid, rest + lowest - env, np.inf)
            k = int(np.argmin(excess))
            if best is None or excess[k] < best[0]:
                best = (float(excess[k]), int(ia[k]), int(ib[k]), float(rest[k]))
            fits = np.flatnonzero(excess <= 1e-6)
            if fits.size:
                # Settle into the lowest spot that fits.
                k = int(fits[np.argmin(rest[fits] + lowest)])
                best = (float(excess[k]), int(ia[k]), int(ib[k]), float(rest[k]))
                break
            base_radius = min(base_radius * _PILE_GROWTH, max_radius)
        if best is None:
            continue

        _, pa, pb, rest_height = best
        ca, cb = pa + cells[:, 0], pb + cells[:, 1]
        field[ca, cb] = np.fmax(field[ca, cb], over + rest_height)
        positions[i, axes[0]] = origin[0] + (pa + 0.5) * cell
        positions[i, axes[1]] = origin[1] + (pb + 0.5) * cell
        positions[i, up] = rest_height
        placed[i] = True

    return positions, orientations, placed, base_radius


def pile_orientations(
    rng: np.random.Generator,
    prototypes: list[ScatterPrototype],
    proto_idx: IntArray,
    up: int,
    tilt_degrees: float,
) -> FloatArray:
    """Lay each piece on its flattest side with a random spin and a small tilt."""
    n = int(proto_idx.shape[0])
    up_vec = up_vector(up)
    axes = horizontal_axes(up)
    extents = np.array([np.subtract(p.bounds_max, p.bounds_min) for p in prototypes])[proto_idx]
    thin = np.argmin(extents, axis=1)
    q = np.tile([1.0, 0.0, 0.0, 0.0], (n, 1))
    lay = thin != up
    if lay.any():
        # A quarter turn about the third axis stands the thinnest axis up.
        turn = np.zeros((n, 3))
        turn[np.flatnonzero(lay), 3 - thin[lay] - up] = 1.0
        q[lay] = quat_axis_angle(turn[lay], np.full(int(lay.sum()), math.pi / 2.0))
    flip_axis = np.zeros(3)
    flip_axis[axes[0]] = 1.0
    q = quat_mul(quat_axis_angle(flip_axis, np.where(rng.random(n) < 0.5, math.pi, 0.0)), q)
    q = quat_mul(quat_axis_angle(up_vec, rng.random(n) * 2.0 * math.pi), q)
    phi = rng.random(n) * 2.0 * math.pi
    tilt_axis = np.zeros((n, 3))
    tilt_axis[:, axes[0]] = np.cos(phi)
    tilt_axis[:, axes[1]] = np.sin(phi)
    tilt = rng.random(n) * math.radians(tilt_degrees)
    return quat_mul(quat_axis_angle(tilt_axis, tilt), q)


def generate_surface_scatter(
    surface: ScatterSurfaceParams,
    pose: ScatterPoseParams,
    *,
    triangles: SurfaceTriangles,
    avoid: SurfaceIndex | None,
    prototypes: list[ScatterPrototype],
    up: int,
    mpu: float,
    seed: int,
) -> tuple[ScatterInstanceSet, list[str]]:
    """Compute every instance of a scatter_on_surface call in world space."""
    rng = np.random.default_rng(seed)
    tri_mask = _require_eligible(triangles, up, surface)
    weights = [proto.weight for proto in prototypes]
    warnings: list[str] = []

    if surface.arrangement is ScatterArrangement.PILE:
        index = surface_utils.build_vertical_index(triangles, up, up_facing_only=True)
        count, center, radius = _pile_setup(surface)
        proto_idx = pick_prototypes(rng, weights, count, ScatterAssetOrder.RANDOM)
        scales = random_scales(rng, pose.scale_range, count)
        positions, orientations, placed, base_radius = pile_instances(
            rng, index, prototypes, proto_idx, scales,
            up=up, center=center,
            radius=radius, repose_degrees=surface.repose_degrees,
            tilt_degrees=pose.tilt_jitter_degrees or _PILE_TILT_DEGREES,
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
        return ScatterInstanceSet(
            proto_indices=proto_idx[placed], positions=positions[placed],
            orientations=orientations[placed], scales=scales[placed],
        ), warnings

    accept = surface_on_accept(
        surface, avoid=avoid, up=up,
        noise_scale=_noise_scale(surface, triangles, up), seed=seed,
    )
    if surface.arrangement is ScatterArrangement.ROWS:
        contacts, tris = _rows_contacts(rng, surface, triangles, tri_mask, up)
        keep = rng.random(contacts.shape[0]) < accept(contacts, tris)
        contacts, tris = contacts[keep], tris[keep]
    else:
        contacts, tris, warnings = scatter_surface_points(
            rng, triangles, tri_mask, up=up, mpu=mpu, count=surface.count,
            density=surface.density, accept=accept, min_spacing=surface.min_spacing,
        )

    n = contacts.shape[0]
    normals = triangles.normals[tris]
    proto_idx = pick_prototypes(rng, weights, n, ScatterAssetOrder.RANDOM)
    scales = random_scales(rng, pose.scale_range, n)
    headings = random_headings(rng, n, up, random_yaw=pose.random_yaw)
    index = surface_utils.build_vertical_index(triangles, up, up_facing_only=True)
    settle = np.ones(n, dtype=bool)
    if pose.align is ScatterAlign.SURFACE:
        base_min, base_max = prototype_bases(prototypes, proto_idx)
        normals, settle = ground_normals(
            index, contacts, headings, scales, base_min, base_max, normals, up,
        )
    orientations = surface_orientations(
        rng, headings, normals, up, align=pose.align,
        tilt_jitter_degrees=pose.tilt_jitter_degrees,
    )
    positions = rest_positions(
        contacts, orientations, scales, prototypes, proto_idx, up,
        embed=pose.embed, settle=settle, index=index,
    )
    return ScatterInstanceSet(
        proto_indices=proto_idx, positions=positions,
        orientations=orientations, scales=scales,
    ), warnings


def estimate_surface_scatter(
    surface: ScatterSurfaceParams,
    *,
    triangles: SurfaceTriangles,
    avoid: SurfaceIndex | None,
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
    if surface.arrangement is ScatterArrangement.PILE:
        count, _, _ = _pile_setup(surface)
        return count, area_m2
    accept = surface_on_accept(
        surface, avoid=avoid, up=up,
        noise_scale=_noise_scale(surface, triangles, up), seed=seed,
    )
    if surface.arrangement is ScatterArrangement.ROWS:
        contacts, tris = _rows_contacts(rng, surface, triangles, tri_mask, up)
        return int(round(float(accept(contacts, tris).sum()))), area_m2
    estimate, _ = estimate_surface_count(
        rng, triangles, tri_mask, mpu=mpu, count=surface.count,
        density=surface.density, accept=accept,
    )
    return estimate, area_m2


# ── paths ──


def build_path(
    stage: Usd.Stage, path: ScatterPathParams, up: int,
) -> tuple[FloatArray, bool, FloatArray]:
    """Return ``(points, closed, centre)`` for the requested path in world space."""
    if path.points is not None:
        points = np.asarray(path.points, dtype=np.float64)
        return points, path.closed, points.mean(axis=0)
    if path.circle is not None:
        circle = path.circle
        center = np.asarray(circle.center, dtype=np.float64)
        axes = list(horizontal_axes(up))
        angles = math.radians(circle.start_angle_degrees) + np.linspace(
            0.0, 2.0 * math.pi, _PATH_SEGMENTS, endpoint=False,
        )
        points = np.repeat(center[None, :], _PATH_SEGMENTS, axis=0)
        points[:, axes[0]] += circle.radius * np.cos(angles)
        points[:, axes[1]] += circle.radius * np.sin(angles)
        return points, True, center
    if path.curve_prim is None:
        msg = "a path needs points, a circle or a curve_prim."
        raise ValueError(msg)
    return _curve_points(stage, path.curve_prim)


def path_stations(
    points: FloatArray,
    closed: bool,
    up: int,
    *,
    count: int | None,
    spacing: float,
    start_offset: float,
) -> tuple[FloatArray, FloatArray, float]:
    """Arc-length stations along the path, with the chord half-step and path length."""
    length = _plan_length(points, closed, up)
    if length <= 0:
        raise ValueError("the path has zero length in plan view.")
    if count is not None:
        if closed:
            stations = (start_offset + np.arange(count) * length / count) % length
            step = length / count
        elif count == 1:
            stations = np.array([min(start_offset, length) if start_offset else length / 2])
            step = length
        else:
            stations = np.linspace(min(start_offset, length), length, count)
            step = (length - min(start_offset, length)) / (count - 1) or length
    elif closed:
        n = max(1, int(round(length / spacing)))
        stations = (start_offset + np.arange(n) * length / n) % length
        step = length / n
    else:
        stations = np.arange(start_offset, length + 1e-9, spacing)
        step = spacing
    if stations.size > ScatterRules.MAX_INSTANCES:
        msg = f"the path would create {stations.size:,} stations; increase spacing."
        raise ValueError(msg)
    return stations, np.full(stations.size, step / 2.0), length


def sample_path(
    points: FloatArray, closed: bool, up: int, stations: FloatArray,
) -> FloatArray:
    """Interpolate 3D positions at plan arc-length *stations*."""
    pts = np.vstack([points, points[:1]]) if closed else points
    axes = list(horizontal_axes(up))
    seg = np.diff(pts[:, axes], axis=0)
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = cum[-1]
    s = np.mod(stations, total) if closed else np.clip(stations, 0.0, total)
    k = np.clip(np.searchsorted(cum, s, side="right") - 1, 0, seg_len.size - 1)
    t = np.where(seg_len[k] > 0, (s - cum[k]) / np.where(seg_len[k] > 0, seg_len[k], 1.0), 0.0)
    return pts[k] + t[:, None] * (pts[k + 1] - pts[k])


def path_tangents(
    points: FloatArray, closed: bool, up: int, stations: FloatArray, half: FloatArray,
) -> FloatArray:
    """Unit plan-view tangents from the chord across each station."""
    ahead = sample_path(points, closed, up, stations + half)
    behind = sample_path(points, closed, up, stations - half)
    chord = ahead - behind
    chord[:, up] = 0.0
    norm = np.linalg.norm(chord, axis=1)
    fallback = norm < 1e-12
    if fallback.any():
        chord[fallback] = _segment_direction(points, closed, up, stations[fallback])
        norm = np.linalg.norm(chord, axis=1)
    return chord / norm[:, None]


def prototype_length(proto: ScatterPrototype, up: int, facing: ScatterPathFacing) -> float:
    """Extent a prototype occupies along the path for automatic spacing."""
    side_axis, front_axis = _side_and_front_axes(up)
    extent = np.subtract(proto.bounds_max, proto.bounds_min)
    if facing is ScatterPathFacing.TANGENT:
        return float(max(extent[side_axis], extent[front_axis]))
    return float(extent[side_axis])


def facing_yaw(
    facing: ScatterPathFacing,
    *,
    rng: np.random.Generator,
    up: int,
    positions: FloatArray,
    tangents: FloatArray,
    side_sign: FloatArray,
    center: FloatArray,
    direction_degrees: float | None,
    prototypes: list[ScatterPrototype],
    proto_idx: IntArray,
) -> FloatArray:
    """Yaw turning each prototype's front (+Z in Y-up, -Y in Z-up) toward *facing*."""
    n = int(positions.shape[0])
    up_vec = up_vector(up)
    front = _front_vector(up)
    if facing is ScatterPathFacing.RANDOM:
        return rng.random(n) * 2.0 * math.pi
    if facing is ScatterPathFacing.TANGENT:
        side_axis, front_axis = _side_and_front_axes(up)
        long_is_side = np.array([
            np.subtract(p.bounds_max, p.bounds_min)[side_axis]
            >= np.subtract(p.bounds_max, p.bounds_min)[front_axis]
            for p in prototypes
        ])[proto_idx]
        side = np.zeros(3)
        side[side_axis] = 1.0
        ref = np.where(long_is_side[:, None], side, front)
        return _signed_angle(ref, tangents, up_vec)
    if facing is ScatterPathFacing.PATH:
        left = np.cross(up_vec, tangents)
        toward = -left * side_sign[:, None]
        toward = np.where((side_sign == 0)[:, None], tangents, toward)
        return _signed_angle(np.broadcast_to(front, toward.shape), toward, up_vec)
    if facing in (ScatterPathFacing.CENTER, ScatterPathFacing.OUTWARD):
        target = center[None, :] - positions
        target[:, up] = 0.0
        norm = np.linalg.norm(target, axis=1)
        target = np.where(norm[:, None] > 1e-12, target / np.maximum(norm, 1e-12)[:, None],
                          tangents)
        if facing is ScatterPathFacing.OUTWARD:
            target = -target
        return _signed_angle(np.broadcast_to(front, target.shape), target, up_vec)
    axes = list(horizontal_axes(up))
    theta = math.radians(direction_degrees or 0.0)
    fixed = np.zeros(3)
    fixed[axes[0]] = math.cos(theta)
    fixed[axes[1]] = math.sin(theta)
    return _signed_angle(front[None, :], fixed[None, :], up_vec).repeat(n)

def generate_path_scatter(
    stage: Usd.Stage,
    path: ScatterPathParams,
    pose: ScatterPoseParams,
    *,
    prototypes: list[ScatterPrototype],
    index: SurfaceIndex | None,
    up: int,
    seed: int,
) -> tuple[ScatterInstanceSet, list[str]]:
    """Compute every instance of a scatter_along_path call in world space."""
    rng = np.random.default_rng(seed)
    up_vec = up_vector(up)
    points, closed, center = build_path(stage, path, up)
    spacing = path.spacing
    if path.count is None and spacing is None:
        mean_scale = sum(pose.scale_range) / 2.0
        spacing = max(prototype_length(p, up, path.facing) for p in prototypes) * mean_scale
        spacing += path.gap
        if spacing <= 0:
            raise ValueError("could not derive spacing from the assets; pass 'spacing'.")
    stations, half, _ = path_stations(
        points, closed, up, count=path.count, spacing=spacing or 1.0,
        start_offset=path.start_offset,
    )
    tangents = path_tangents(points, closed, up, stations, half)
    signs = np.array(side_signs(path.sides), dtype=np.float64)
    per_station = signs.size
    station_idx = np.repeat(np.arange(stations.size), per_station)
    sign = np.tile(signs, stations.size)
    tangent = tangents[station_idx]
    lateral = np.cross(up_vec, tangent) * (sign * path.offset)[:, None]
    contacts = sample_path(points, closed, up, stations)[station_idx] + lateral

    n = contacts.shape[0]
    weights = [proto.weight for proto in prototypes]
    proto_idx = pick_prototypes(rng, weights, n, path.asset_order)
    scales = random_scales(rng, pose.scale_range, n)
    normals = np.repeat(up_vec[None, :], n, axis=0)
    warnings: list[str] = []
    if index is not None:
        hit, heights, tris = surface_utils.surface_under(
            index, contacts, mode="nearest", reference=contacts[:, up].copy(),
        )
        contacts[hit, up] = heights[hit]
        normals[hit] = index.triangles.normals[tris[hit]]
        if (~hit).any():
            warnings.append(
                f"{int((~hit).sum())} of {n} instance(s) have no surface under them "
                "and keep the path height.",
            )

    yaw = facing_yaw(
        path.facing, rng=rng, up=up, positions=contacts, tangents=tangent,
        side_sign=sign, center=center, direction_degrees=path.direction_degrees,
        prototypes=prototypes, proto_idx=proto_idx,
    ) + math.radians(path.yaw_offset_degrees)
    headings = quat_axis_angle(up_vec, yaw)
    orientations = headings
    settle = np.full(n, pose.align is ScatterAlign.UP)
    if path.follow_slope and index is not None:
        pitch = _path_pitch(index, points, closed, up, stations, half, station_idx, lateral)
        axis = np.cross(tangent, up_vec)
        orientations = quat_mul(quat_axis_angle(axis, pitch), orientations)
    if pose.align is ScatterAlign.SURFACE:
        if index is not None:
            base_min, base_max = prototype_bases(prototypes, proto_idx)
            normals, settle = ground_normals(
                index, contacts, headings, scales, base_min, base_max, normals, up,
            )
        orientations = quat_mul(quat_between(up_vec, normals), orientations)
    if path.follow_slope:
        settle[:] = False
    positions = rest_positions(
        contacts, orientations, scales, prototypes, proto_idx, up,
        embed=pose.embed, settle=settle, index=index,
    )
    return ScatterInstanceSet(
        proto_indices=proto_idx, positions=positions,
        orientations=orientations, scales=scales,
    ), warnings


def estimate_path_scatter(
    stage: Usd.Stage, path: ScatterPathParams, up: int,
) -> tuple[int | None, float]:
    """Return ``(instances or None when spacing is automatic, path_length)``."""
    points, closed, _ = build_path(stage, path, up)
    length = _plan_length(points, closed, up)
    if path.count is None and path.spacing is None:
        return None, length
    stations, _, _ = path_stations(
        points, closed, up, count=path.count, spacing=path.spacing or 1.0,
        start_offset=path.start_offset,
    )
    return int(stations.size) * len(side_signs(path.sides)), length


# ── orientation ──


def quat_axis_angle(axis: FloatArray, angle: FloatArray) -> FloatArray:
    """Quaternions ``(w, x, y, z)`` rotating *angle* radians about unit *axis*."""
    axis = np.broadcast_to(axis, (angle.shape[0], 3))
    half = angle / 2.0
    return np.column_stack([np.cos(half), axis * np.sin(half)[:, None]])


def quat_mul(a: FloatArray, b: FloatArray) -> FloatArray:
    """Hamilton product ``a * b`` (apply *b* first, then *a*)."""
    w1, x1, y1, z1 = a.T
    w2, x2, y2, z2 = b.T
    return np.column_stack([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ])


def quat_rotate(q: FloatArray, v: FloatArray) -> FloatArray:
    """Rotate vectors *v* (n, 3) by quaternions *q* (n, 4)."""
    w = q[:, :1]
    u = q[:, 1:]
    t = 2.0 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


def quat_between(src: FloatArray, dst: FloatArray) -> FloatArray:
    """Shortest-arc quaternions turning unit *src* (3,) onto each unit *dst*."""
    d = dst @ src
    axis = np.cross(np.broadcast_to(src, dst.shape), dst)
    q = np.column_stack([1.0 + d, axis])
    opposite = d < -1.0 + 1e-9
    if opposite.any():
        perp = np.cross(src, [1.0, 0.0, 0.0])
        if np.linalg.norm(perp) < 1e-6:
            perp = np.cross(src, [0.0, 0.0, 1.0])
        perp /= np.linalg.norm(perp)
        q[opposite] = np.concatenate([[0.0], perp])
    return q / np.linalg.norm(q, axis=1)[:, None]


def quat_conj(q: FloatArray) -> FloatArray:
    """Inverse of unit quaternions ``(w, x, y, z)``."""
    return q * np.array([1.0, -1.0, -1.0, -1.0], dtype=np.float64)


def quat_heading(q: FloatArray, up: int) -> FloatArray:
    """The turn about up alone that keeps each rotation's heading (tilt removed)."""
    axes = horizontal_axes(up)
    up_vec = up_vector(up)
    angle = np.zeros(q.shape[0])
    todo = np.ones(q.shape[0], dtype=bool)
    for axis in axes:
        ref = np.zeros(3)
        ref[axis] = 1.0
        f = quat_rotate(q[todo], np.tile(ref, (int(todo.sum()), 1)))
        f[:, up] = 0.0
        # A vertical reference axis has no heading; try the other one.
        clear = np.linalg.norm(f, axis=1) > 1e-6
        rows = np.flatnonzero(todo)[clear]
        angle[rows] = np.arctan2(np.cross(ref, f[clear]) @ up_vec, f[clear] @ ref)
        todo[rows] = False
    return quat_axis_angle(up_vec, angle)


def random_headings(
    rng: np.random.Generator, n: int, up: int, *, random_yaw: bool,
) -> FloatArray:
    """Yaw-only rotations about up: uniformly random, or none."""
    yaw = rng.random(n) * 2.0 * math.pi if random_yaw else np.zeros(n)
    return quat_axis_angle(up_vector(up), yaw)


def surface_orientations(
    rng: np.random.Generator,
    headings: FloatArray,
    normals: FloatArray,
    up: int,
    *,
    align: ScatterAlign,
    tilt_jitter_degrees: float,
) -> FloatArray:
    """*headings*, optional random tilt, then (optionally) align to normals."""
    n = int(normals.shape[0])
    up_vec = up_vector(up)
    q = headings
    if tilt_jitter_degrees > 0:
        axes = horizontal_axes(up)
        phi = rng.random(n) * 2.0 * math.pi
        axis = np.zeros((n, 3))
        axis[:, axes[0]] = np.cos(phi)
        axis[:, axes[1]] = np.sin(phi)
        tilt = rng.random(n) * math.radians(tilt_jitter_degrees)
        q = quat_mul(quat_axis_angle(axis, tilt), q)
    if align is ScatterAlign.SURFACE:
        q = quat_mul(quat_between(up_vec, normals), q)
    return q


def quat_to_rotate_xyz(q: FloatArray) -> list[tuple[float, float, float]]:
    """Convert ``(w, x, y, z)`` quaternions to xformOp:rotateXYZ degrees."""
    out: list[tuple[float, float, float]] = []
    for w, x, y, z in q.tolist():
        rotation = Gf.Rotation(Gf.Quatd(w, Gf.Vec3d(x, y, z)))
        rz, ry, rx = rotation.Decompose(Gf.Vec3d.ZAxis(), Gf.Vec3d.YAxis(), Gf.Vec3d.XAxis())
        out.append(_smallest_rotate_xyz(rx, ry, rz))
    return out


# ── resting ──


def rest_positions(
    contacts: FloatArray,
    orientations: FloatArray,
    scales: FloatArray,
    prototypes: list[ScatterPrototype],
    proto_idx: IntArray,
    up: int,
    *,
    embed: float,
    settle: BoolArray,
    index: SurfaceIndex | None,
) -> FloatArray:
    """Set each piece's base centre on its contact point, then settle and embed it."""
    bmin = np.stack([p.bounds_min for p in prototypes])[proto_idx]
    bmax = np.stack([p.bounds_max for p in prototypes])[proto_idx]
    base_min, base_max = prototype_bases(prototypes, proto_idx)
    base = (base_min + base_max) / 2.0
    up_vec = up_vector(up)
    positions = contacts - quat_rotate(orientations, base * scales)
    if index is not None and settle.any():
        samples = base_samples(
            positions[settle], orientations[settle], scales[settle],
            base_min[settle], base_max[settle], up,
        )
        shift, _ = settle_shift(index, samples, up)
        positions[settle, up] += shift
    height = (bmax[:, up] - bmin[:, up]) * scales[:, up]
    if embed > 0:
        local_up = quat_rotate(orientations, np.broadcast_to(up_vec, contacts.shape))
        positions -= local_up * (embed * height)[:, None]
    return positions


def prototype_bases(
    prototypes: list[ScatterPrototype], proto_idx: IntArray,
) -> tuple[FloatArray, FloatArray]:
    """Per-instance ``(base_min, base_max)`` of each instance's prototype."""
    base_min = np.stack([p.base_min for p in prototypes])[proto_idx]
    base_max = np.stack([p.base_max for p in prototypes])[proto_idx]
    return base_min, base_max


def ground_normals(
    index: SurfaceIndex,
    contacts: FloatArray,
    headings: FloatArray,
    scales: FloatArray,
    base_min: FloatArray,
    base_max: FloatArray,
    fallback: FloatArray,
    up: int,
) -> tuple[FloatArray, BoolArray]:
    """Normal of the ground fitted under each base footprint, else *fallback*."""
    axes = list(horizontal_axes(up))
    center = (base_min + base_max) / 2.0
    positions = contacts - quat_rotate(headings, center * scales)
    samples = base_samples(positions, headings, scales, base_min, base_max, up)
    n, k, _ = samples.shape
    flat = samples.reshape(-1, 3)
    hit, heights, _ = surface_utils.surface_under(
        index, flat, mode="nearest", reference=flat[:, up].copy(),
    )
    w = hit.reshape(n, k).astype(np.float64)
    a = samples[:, :, axes[0]] - contacts[:, None, axes[0]]
    b = samples[:, :, axes[1]] - contacts[:, None, axes[1]]
    h = np.where(hit, heights, 0.0).reshape(n, k) - contacts[:, None, up]
    count = np.maximum(w.sum(axis=1), 1.0)

    def mean(v: FloatArray) -> FloatArray:
        return (w * v).sum(axis=1) / count

    ma, mb, mh = mean(a), mean(b), mean(h)
    caa = mean(a * a) - ma * ma
    cbb = mean(b * b) - mb * mb
    cab = mean(a * b) - ma * mb
    cah = mean(a * h) - ma * mh
    cbh = mean(b * h) - mb * mh
    det = caa * cbb - cab * cab
    fitted = (
        (w.sum(axis=1) >= 3)
        & (det > 1e-6 * (caa + cbb) ** 2 + _EPS)
        & (fallback[:, up] >= math.cos(math.radians(_FIT_MAX_SLOPE_DEGREES)))
    )
    safe = np.where(fitted, det, 1.0)
    normals = np.zeros((n, 3))
    normals[:, axes[0]] = -(cah * cbb - cbh * cab) / safe
    normals[:, axes[1]] = -(cbh * caa - cah * cab) / safe
    normals[:, up] = 1.0
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    return np.where(fitted[:, None], normals, fallback), fitted


def base_samples(
    positions: FloatArray,
    orientations: FloatArray,
    scales: FloatArray,
    base_min: FloatArray,
    base_max: FloatArray,
    up: int,
) -> FloatArray:
    """``(n, k, 3)`` points on each piece's base footprint, in the positions' frame."""
    axes = list(horizontal_axes(up))
    t = np.linspace(0.0, 1.0, _BASE_GRID)
    ta, tb = (g.ravel() for g in np.meshgrid(t, t, indexing="ij"))
    n, k = positions.shape[0], ta.size
    local = np.repeat(base_min[:, None, :], k, axis=1)
    extent = base_max - base_min
    local[:, :, axes[0]] += ta[None, :] * extent[:, None, axes[0]]
    local[:, :, axes[1]] += tb[None, :] * extent[:, None, axes[1]]
    local *= scales[:, None, :]
    rotated = quat_rotate(np.repeat(orientations, k, axis=0), local.reshape(-1, 3))
    return positions[:, None, :] + rotated.reshape(n, k, 3)


def settle_shift(
    index: SurfaceIndex, samples: FloatArray, up: int,
) -> tuple[FloatArray, BoolArray]:
    """Up shift that lands each piece's highest base sample on the surface."""
    n, k, _ = samples.shape
    flat = samples.reshape(-1, 3)
    hit, heights, _ = surface_utils.surface_under(
        index, flat, mode="nearest", reference=flat[:, up].copy(),
    )
    gap = np.where(hit, flat[:, up] - np.where(hit, heights, 0.0), -np.inf).reshape(n, k)
    worst = gap.max(axis=1)
    supported = np.isfinite(worst)
    return np.where(supported, -worst, 0.0), supported


# ── authoring ──


def to_local(
    stage: Usd.Stage, parent_path: str, instances: ScatterInstanceSet,
) -> ScatterInstanceSet:
    """Re-express world-space instances in the frame of *parent_path*."""
    parent = stage.GetPrimAtPath(parent_path)
    if not parent.IsValid():
        return instances
    world = UsdGeom.Xformable(parent).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    if world == Gf.Matrix4d(1.0):
        return instances
    inverse = world.GetInverse()
    matrix = gf_matrix_to_numpy(inverse)
    positions = instances.positions @ matrix[:3, :3] + matrix[3, :3]
    rot = inverse.RemoveScaleShear().ExtractRotationQuat()
    parent_q = np.array([[rot.GetReal(), *rot.GetImaginary()]])
    orientations = quat_mul(np.repeat(parent_q, instances.count, axis=0),
                            instances.orientations)
    return ScatterInstanceSet(
        proto_indices=instances.proto_indices, positions=positions,
        orientations=orientations, scales=instances.scales,
    )


def write_scatter(
    stage: Usd.Stage,
    *,
    prim_path: str,
    output: ScatterOutput,
    prototypes: list[ScatterPrototype],
    instances: ScatterInstanceSet,
    first_index: int,
) -> dict[str, Any]:
    """Author a scatter in scene.usda as a PointInstancer or as placements."""
    if stage.GetPrimAtPath(prim_path).IsValid():
        stage.RemovePrim(prim_path)
    if output is ScatterOutput.PLACEMENTS:
        if instances.count > ScatterRules.MAX_PLACEMENTS:
            msg = (
                f"{instances.count:,} instances is too many for output='placements' "
                f"(max {ScatterRules.MAX_PLACEMENTS:,}); use output='instancer'."
            )
            raise ValueError(msg)
        stage.DefinePrim(prim_path, "Xform")
        local = to_local(stage, prim_path, instances)
        add_references(
            stage, placement_objects(prim_path, prototypes, local, first_index),
        )
        return {"placements": instances.count, "warnings": []}

    write_instancer(stage, prim_path, prototypes, instances)
    return {"placements": 0, "warnings": instancer_size_warning(instances.count)}


def write_instancer(
    stage: Usd.Stage,
    prim_path: str,
    prototypes: list[ScatterPrototype],
    instances: ScatterInstanceSet,
) -> None:
    """Author a PointInstancer whose prototypes are placement wrappers of the assets."""
    instancer = UsdGeom.PointInstancer.Define(stage, prim_path)
    xformable = UsdGeom.Xformable(instancer)
    xformable.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.0))
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(0.0, 0.0, 0.0))
    xformable.AddScaleOp().Set(Gf.Vec3f(1.0, 1.0, 1.0))

    prototypes_path = f"{prim_path}/{ScatterNamespace.PROTOTYPES}"
    stage.DefinePrim(prototypes_path, "Scope")
    add_references(stage, [
        SceneObject(
            prim_path=f"{prototypes_path}/{proto.name}",
            asset=AssetMetadata(
                name=proto.name, source_skill="local", source_id=proto.source,
                file_path=proto.scene_ref,
            ),
        )
        for proto in prototypes
    ])
    instancer.CreatePrototypesRel().SetTargets(
        [Sdf.Path(f"{prototypes_path}/{proto.name}") for proto in prototypes],
    )

    local = to_local(stage, prim_path, instances)
    q = local.orientations / np.linalg.norm(local.orientations, axis=1)[:, None]
    instancer.CreateProtoIndicesAttr(
        Vt.IntArray.FromNumpy(local.proto_indices.astype(np.int32)),
    )
    instancer.CreatePositionsAttr(
        Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(local.positions, dtype=np.float32)),
    )
    instancer.CreateOrientationsAttr(
        Vt.QuathArray.FromNumpy(np.ascontiguousarray(q[:, [1, 2, 3, 0]], dtype=np.float16)),
    )
    instancer.CreateScalesAttr(
        Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(local.scales, dtype=np.float32)),
    )
    time = Usd.TimeCode.Default()
    extent = instancer.ComputeExtentAtTime(time, time)
    if extent:
        instancer.CreateExtentAttr(extent)


def instancer_size_warning(count: int) -> list[str]:
    """Warn when an instancer makes scene.usda heavy to re-save."""
    if count <= _LARGE_SCATTER:
        return []
    megabytes = count * _ASCII_BYTES_PER_INSTANCE / 1e6
    return [
        f"{count:,} instances add about {megabytes:,.0f} MB to scene.usda, which "
        "BowerBot re-saves after every edit. Lower the density, or split the area "
        "into several scatters with regions.",
    ]


def placement_objects(
    group_path: str,
    prototypes: list[ScatterPrototype],
    instances: ScatterInstanceSet,
    first_index: int,
) -> list[SceneObject]:
    """One placement wrapper per instance under *group_path*, numbered from *first_index*."""
    rotations = quat_to_rotate_xyz(instances.orientations)
    objects: list[SceneObject] = []
    for i in range(instances.count):
        proto = prototypes[int(instances.proto_indices[i])]
        objects.append(SceneObject(
            prim_path=f"{group_path}/{proto.name}_{first_index + i:02d}",
            asset=AssetMetadata(
                name=proto.name, source_skill="local", source_id=proto.source,
                file_path=proto.scene_ref,
            ),
            translate=to_vec3(instances.positions[i].tolist()),
            rotate=rotations[i],
            scale=to_vec3(instances.scales[i].tolist()),
        ))
    return objects


def count_by_prototype(
    prototypes: list[ScatterPrototype], instances: ScatterInstanceSet,
) -> dict[str, int]:
    """Instances per prototype name."""
    counts = np.bincount(instances.proto_indices, minlength=len(prototypes))
    return {proto.name: int(c) for proto, c in zip(prototypes, counts, strict=True)}


def format_scatter_prim(prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache) -> dict[str, Any]:
    """``list_scene`` entry for a scatter PointInstancer."""
    instancer = UsdGeom.PointInstancer(prim)
    indices = instancer.GetProtoIndicesAttr().Get() or []
    stage = prim.GetStage()
    prototypes = []
    for target in instancer.GetPrototypesRel().GetTargets():
        proto = stage.GetPrimAtPath(target)
        child = proto.GetChild("asset") if proto.IsValid() else proto
        refs = get_prim_ref_paths(child) if child and child.IsValid() else []
        prototypes.append(refs[0] if refs else str(target))
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "scatter",
        "type": "PointInstancer",
        "instances": len(indices),
        "prototypes": prototypes,
        "position": extract_position(prim),
        "bounds": world_bounds(prim, bbox_cache),
    }


# ── drop to surface ──


def drop_targets(stage: Usd.Stage, prim_paths: list[str]) -> tuple[list[str], list[str]]:
    """Expand paths to ``(placement wrappers, scatters)``; groups expand to their contents."""
    wrappers: list[str] = []
    scatters: list[str] = []
    for prim_path in prim_paths:
        if parse_nested_contents_path(prim_path) is not None:
            msg = (
                f"{prim_path} is a nested placement inside an asset; "
                "drop_to_surface moves scene-level placements only."
            )
            raise ValueError(msg)
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            msg = f"Prim not found: {prim_path}"
            raise ValueError(msg)
        iterator = iter(Usd.PrimRange(prim))
        for candidate in iterator:
            path = str(candidate.GetPath())
            if candidate.IsA(UsdGeom.PointInstancer):
                iterator.PruneChildren()
                if path not in scatters:
                    scatters.append(path)
                continue
            if _is_placement_wrapper(candidate):
                if path not in wrappers:
                    wrappers.append(path)
                iterator.PruneChildren()
    if not wrappers and not scatters:
        msg = (
            f"No placements or scatters found under {prim_paths}. Pass placement "
            "or scatter paths (/Scene/<Group>/<Name>) or a group that contains them."
        )
        raise ValueError(msg)
    return wrappers, scatters


def drop_scatter(
    stage: Usd.Stage, prim_path: str, index: SurfaceIndex, *, align: ScatterDropAlign,
) -> dict[str, Any]:
    """Reseat a scatter's instances on the surface in place, optionally re-tilting them."""
    up = index.up
    instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(prim_path))
    time = Usd.TimeCode.Default()
    positions = np.asarray(instancer.GetPositionsAttr().Get() or [], dtype=np.float64)
    n = positions.shape[0]
    if n == 0:
        return {"prim_path": prim_path, "supported": False}
    proto_idx = np.asarray(instancer.GetProtoIndicesAttr().Get(), dtype=np.int64)
    raw_q = instancer.GetOrientationsAttr().Get()
    orientations = (
        np.asarray(raw_q, dtype=np.float64)[:, [3, 0, 1, 2]] if raw_q
        else np.tile([1.0, 0.0, 0.0, 0.0], (n, 1))
    )
    raw_s = instancer.GetScalesAttr().Get()
    scales = np.asarray(raw_s, dtype=np.float64) if raw_s else np.ones((n, 3))

    world_gf = UsdGeom.XformCache(time).GetLocalToWorldTransform(instancer.GetPrim())
    world = gf_matrix_to_numpy(world_gf)
    to_local = np.linalg.inv(world)
    targets = instancer.GetPrototypesRel().GetTargets()
    proto_min = np.zeros((len(targets), 3))
    proto_max = np.zeros((len(targets), 3))
    for i, target in enumerate(targets):
        points = _prototype_points(stage, str(target), up)
        local = points @ to_local[:3, :3] + to_local[3, :3]
        proto_min[i], proto_max[i] = _base_footprint(local, up)
    base_min, base_max = proto_min[proto_idx], proto_max[proto_idx]

    retilted = 0
    if align is ScatterDropAlign.SURFACE:
        rotation = world_gf.RemoveScaleShear().ExtractRotationQuat()
        to_world_q = np.tile([rotation.GetReal(), *rotation.GetImaginary()], (n, 1))
        world_scale = float(np.cbrt(abs(np.linalg.det(world[:3, :3]))))
        up_vec = up_vector(up)
        base = (base_min + base_max) / 2.0
        centers_local = positions + quat_rotate(orientations, base * scales)
        centers = centers_local @ world[:3, :3] + world[3, :3]
        headings = quat_heading(quat_mul(to_world_q, orientations), up)
        hit, _, tris = surface_utils.surface_under(
            index, centers, mode="nearest", reference=centers[:, up].copy(),
        )
        fallback = np.where(
            hit[:, None], index.triangles.normals[np.maximum(tris, 0)], up_vec,
        )
        normals, fitted = ground_normals(
            index, centers, headings, scales * world_scale, base_min, base_max,
            fallback, up,
        )
        tilted = quat_mul(
            quat_conj(to_world_q), quat_mul(quat_between(up_vec, normals), headings),
        )
        orientations = np.where(fitted[:, None], tilted, orientations)
        positions = centers_local - quat_rotate(orientations, base * scales)
        retilted = int(fitted.sum())

    samples = base_samples(positions, orientations, scales, base_min, base_max, up)
    world_samples = samples.reshape(-1, 3) @ world[:3, :3] + world[3, :3]
    shift, supported = settle_shift(index, world_samples.reshape(samples.shape), up)
    if not supported.any():
        return {"prim_path": prim_path, "supported": False}
    delta = np.outer(shift, up_vector(up)) @ to_local[:3, :3]
    if retilted:
        instancer.GetOrientationsAttr().Set(Vt.QuathArray.FromNumpy(
            np.ascontiguousarray(orientations[:, [1, 2, 3, 0]], dtype=np.float16),
        ))
    instancer.GetPositionsAttr().Set(
        Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(positions + delta, dtype=np.float32)),
    )
    extent = instancer.ComputeExtentAtTime(time, time)
    if extent:
        instancer.CreateExtentAttr(extent)
    stranded = np.flatnonzero(~supported)[:_STRANDED_REPORT]
    stranded_at = world_samples.reshape(samples.shape)[stranded].mean(axis=1)
    return {
        "prim_path": prim_path,
        "supported": True,
        "instances": n,
        "reseated": int(supported.sum()),
        "retilted": retilted,
        "moved_by": {
            "min": round(float(shift[supported].min()), 4),
            "max": round(float(shift[supported].max()), 4),
        },
        "no_surface_under": {
            "count": int((~supported).sum()),
            "instances": stranded.tolist(),
            "positions": np.round(stranded_at, 3).tolist(),
        },
    }


def drop_prim(
    stage: Usd.Stage,
    prim_path: str,
    index: SurfaceIndex,
    *,
    align: ScatterDropAlign,
) -> dict[str, Any]:
    """Move one placement so it rests on the highest surface under its footprint."""
    up = index.up
    axes = list(index.axes)
    prim = stage.GetPrimAtPath(prim_path)
    bmin, bmax = prim_world_box(stage, prim_path)
    grid = np.linspace(0.1, 0.9, _DROP_FOOTPRINT)
    ga, gb = np.meshgrid(grid, grid, indexing="ij")
    footprint = np.zeros((ga.size, 3))
    footprint[:, axes[0]] = bmin[axes[0]] + ga.ravel() * (bmax[axes[0]] - bmin[axes[0]])
    footprint[:, axes[1]] = bmin[axes[1]] + gb.ravel() * (bmax[axes[1]] - bmin[axes[1]])
    ceiling = np.full(footprint.shape[0], bmax[up])
    hit, heights, _ = surface_utils.surface_under(
        index, footprint, mode="below", reference=ceiling,
    )
    if not hit.any():
        # Fully buried: use the nearest ground above instead.
        hit, heights, _ = surface_utils.surface_under(
            index, footprint, mode="nearest", reference=ceiling,
        )
    if not hit.any():
        return {"prim_path": prim_path, "supported": False}

    xformable = UsdGeom.Xformable(prim)
    ops = {op.GetOpType(): op for op in xformable.GetOrderedXformOps()}
    translate_op = ops.get(UsdGeom.XformOp.TypeTranslate)
    if translate_op is None:
        msg = f"{prim_path} has no translate op; only BowerBot placements can be dropped."
        raise ValueError(msg)
    parent_world = UsdGeom.Xformable(prim.GetParent()).ComputeLocalToWorldTransform(
        Usd.TimeCode.Default(),
    ) if prim.GetParent().IsA(UsdGeom.Xformable) else Gf.Matrix4d(1.0)
    to_parent = parent_world.GetInverse()
    old_local = np.array(translate_op.Get() or Gf.Vec3d(0.0, 0.0, 0.0), dtype=np.float64)
    up_vec = up_vector(up)

    rotate_value = None
    world_shift = np.zeros(3)
    if align is ScatterDropAlign.SURFACE and int(hit.sum()) >= 3:
        pts = footprint[hit].copy()
        pts[:, up] = heights[hit]
        design = np.column_stack([pts[:, axes[0]], pts[:, axes[1]], np.ones(pts.shape[0])])
        coef, *_ = np.linalg.lstsq(design, pts[:, up], rcond=None)
        normal = np.zeros(3)
        normal[axes[0]], normal[axes[1]], normal[up] = -coef[0], -coef[1], 1.0
        normal /= np.linalg.norm(normal)
        tilt = quat_between(up_vec, normal[None, :])[0]
        rotate_op = ops.get(UsdGeom.XformOp.TypeRotateXYZ)
        if rotate_op is None:
            msg = f"{prim_path} has no rotateXYZ op; use align='keep' to drop it upright."
            raise ValueError(msg)
        old_rot = _rotate_xyz_rotation(rotate_op.Get())
        tilt_rot = Gf.Rotation(Gf.Quatd(tilt[0], Gf.Vec3d(*tilt[1:].tolist())))
        new_rot = old_rot * tilt_rot
        rz, ry, rx = new_rot.Decompose(Gf.Vec3d.ZAxis(), Gf.Vec3d.YAxis(), Gf.Vec3d.XAxis())
        rotate_value = Gf.Vec3f(rx, ry, rz)

        pivot = np.asarray(
            UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            .ExtractTranslation(), dtype=np.float64,
        )
        base = (bmin + bmax) / 2.0
        base[up] = bmin[up]
        swung = base + quat_rotate(tilt[None, :], (pivot - base)[None, :])[0]
        world_shift += swung - pivot
        fitted = coef[0] * pts[:, axes[0]] + coef[1] * pts[:, axes[1]] + coef[2]
        residual = float(np.max(pts[:, up] - fitted))
        target = float(coef[0] * base[axes[0]] + coef[1] * base[axes[1]] + coef[2])
        target += max(residual, 0.0)
        world_shift += up_vec * (target - base[up])
    else:
        world_shift += up_vec * (float(np.nanmax(heights[hit])) - bmin[up])

    shift_local = np.asarray(to_parent.TransformDir(Gf.Vec3d(*world_shift.tolist())))
    new_local = old_local + shift_local
    translate_op.Set(Gf.Vec3d(*new_local.tolist()))
    if rotate_value is not None:
        ops[UsdGeom.XformOp.TypeRotateXYZ].Set(rotate_value)
    return {
        "prim_path": prim_path,
        "supported": True,
        "from": [round(v, 4) for v in old_local.tolist()],
        "to": [round(v, 4) for v in new_local.tolist()],
        "moved_by": round(float(np.dot(world_shift, up_vec)), 4),
    }


# ── internals ──


def _circle_center(
    stage: Usd.Stage, raw: dict[str, Any], up: int, label: str,
) -> Vec3:
    """A circle's centre from ``center`` or from ``center_prim``."""
    if (raw.get("center") is None) == (raw.get("center_prim") is None):
        msg = f"{label} needs exactly one of 'center' or 'center_prim'."
        raise ValueError(msg)
    if raw.get("center") is not None:
        return to_vec3(raw["center"], "center")
    bmin, bmax = prim_world_box(stage, raw["center_prim"])
    center = (bmin + bmax) / 2.0
    center[up] = bmin[up]
    return to_vec3(center.tolist(), "center_prim")


def _conformed_extents(
    root_file: Path, unit_scale: float, correction: float | None, up: int,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray]:
    """Conformed bounds, base footprint and vertex sample of an asset."""
    stage = Usd.Stage.Open(str(root_file))
    root = stage.GetDefaultPrim() if stage else None
    if root is None or not root.IsValid():
        msg = f"{root_file.name} has no default prim to measure."
        raise ValueError(msg)
    rng = world_range(root, bbox_cache(include_render=True))
    if rng is None:
        msg = f"{root_file.name} has no geometry bounds, so it cannot rest on a surface."
        raise ValueError(msg)
    corners = np.array([list(rng.GetCorner(i)) for i in range(8)])
    triangles = surface_utils.collect_triangles(
        stage, [str(root.GetPath())],
        up=axis_index(UsdGeom.GetStageUpAxis(stage)),
    )
    points = (
        np.concatenate([
            triangles.v0, triangles.v1, triangles.v2,
            (triangles.v0 + triangles.v1 + triangles.v2) / 3.0,
        ])
        if triangles.count else corners
    )
    if correction is not None:
        rotate = gf_matrix_to_numpy(
            Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d.XAxis(), correction)),
        )[:3, :3]
        corners = corners @ rotate
        points = points @ rotate
    corners *= unit_scale
    points *= unit_scale
    base_min, base_max = _base_footprint(points, up)
    shape = np.unique(points, axis=0)
    if shape.shape[0] > _SHAPE_POINTS:
        shape = shape[np.linspace(0, shape.shape[0] - 1, _SHAPE_POINTS).astype(np.int64)]
    return corners.min(axis=0), corners.max(axis=0), base_min, base_max, shape


def _base_footprint(points: FloatArray, up: int) -> tuple[FloatArray, FloatArray]:
    """Box around the lowest slice of *points*: what meets the ground when upright."""
    bottom = float(points[:, up].min())
    top = float(points[:, up].max())
    base = points[points[:, up] <= bottom + _BASE_SLICE * (top - bottom) + _EPS]
    base_min = base.min(axis=0)
    base_max = base.max(axis=0)
    base_min[up] = base_max[up] = bottom
    return base_min, base_max


def _prototype_points(stage: Usd.Stage, prim_path: str, up: int) -> FloatArray:
    """World-space vertices of a prototype, or its box corners if it has no mesh."""
    triangles = surface_utils.collect_triangles(stage, [prim_path], up=up)
    if triangles.count:
        return np.concatenate([triangles.v0, triangles.v1, triangles.v2])
    rng = world_range(stage.GetPrimAtPath(prim_path), bbox_cache(include_render=True))
    if rng is None:
        msg = f"Prototype {prim_path} has no geometry, so it cannot rest on a surface."
        raise ValueError(msg)
    return np.array([list(rng.GetCorner(i)) for i in range(8)])

def _require_eligible(
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


def _noise_scale(
    surface: ScatterSurfaceParams, triangles: SurfaceTriangles, up: int,
) -> float:
    """Variation feature size: explicit, else a fifth of the covered extent."""
    if surface.variation_scale is not None:
        return surface.variation_scale
    bounds = region_plan_bounds(surface.region, up) or surface_utils.plan_bounds(triangles, up)
    return max(float(np.max(bounds[1] - bounds[0])) / 5.0, 1e-6)


def _rows_contacts(
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


def _path_pitch(
    index: SurfaceIndex,
    points: FloatArray,
    closed: bool,
    up: int,
    stations: FloatArray,
    half: FloatArray,
    station_idx: IntArray,
    lateral: FloatArray,
) -> FloatArray:
    """Pitch (radians) of the surface along the path across each instance."""
    ahead = sample_path(points, closed, up, stations + half)[station_idx] + lateral
    behind = sample_path(points, closed, up, stations - half)[station_idx] + lateral
    hit_a, h_a, _ = surface_utils.surface_under(
        index, ahead, mode="nearest", reference=ahead[:, up].copy(),
    )
    hit_b, h_b, _ = surface_utils.surface_under(
        index, behind, mode="nearest", reference=behind[:, up].copy(),
    )
    axes = list(horizontal_axes(up))
    run = np.linalg.norm((ahead - behind)[:, axes], axis=1)
    rise = np.where(hit_a & hit_b, h_a - h_b, 0.0)
    return np.arctan2(rise, np.maximum(run, 1e-9))


def _accepted_samples(
    rng: np.random.Generator,
    triangles: SurfaceTriangles,
    weights: FloatArray,
    target: int,
    accept: _Acceptance,
    *,
    exact: bool,
) -> tuple[FloatArray, IntArray]:
    """Sample then thin by *accept*; with *exact*, keep sampling until *target*."""
    batch = target
    kept_pts: list[FloatArray] = []
    kept_tris: list[IntArray] = []
    got = 0
    for _ in range(_MAX_SAMPLE_ROUNDS if exact else 1):
        points, tris = surface_utils.sample_on_triangles(rng, triangles, weights, batch)
        prob = accept(points, tris)
        keep = rng.random(points.shape[0]) < prob
        kept_pts.append(points[keep])
        kept_tris.append(tris[keep])
        got += int(keep.sum())
        if not exact or got >= target:
            break
        rate = max(float(keep.mean()) if keep.size else 0.0, 1e-3)
        batch = int(min(max((target - got) / rate * 1.25, 1024), _MAX_SAMPLE_BATCH))
    points = np.concatenate(kept_pts) if kept_pts else np.zeros((0, 3))
    tris = np.concatenate(kept_tris) if kept_tris else np.zeros(0, dtype=np.int64)
    if exact:
        return points[:target], tris[:target]
    return points, tris


def _eligible_share(
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
        rng, triangles, triangles.areas * tri_mask, _AREA_PROBE,
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


def _value_noise(p: FloatArray, seed: int) -> FloatArray:
    """Trilinear value noise on an integer lattice hashed with *seed*."""
    cell = np.floor(p)
    f = p - cell
    f = f * f * (3.0 - 2.0 * f)
    base = cell.astype(np.int64)
    result = np.zeros(p.shape[0])
    for dx in (0, 1):
        wx = f[:, 0] if dx else 1.0 - f[:, 0]
        for dy in (0, 1):
            wy = f[:, 1] if dy else 1.0 - f[:, 1]
            for dz in (0, 1):
                wz = f[:, 2] if dz else 1.0 - f[:, 2]
                h = _lattice_hash(base[:, 0] + dx, base[:, 1] + dy, base[:, 2] + dz, seed)
                result += wx * wy * wz * h
    return result


def _lattice_hash(ix: IntArray, iy: IntArray, iz: IntArray, seed: int) -> FloatArray:
    """Deterministic hash of lattice coordinates to [0, 1) (splitmix64 finalizer)."""
    h = (
        ix.astype(np.uint64) * np.uint64(0x9E3779B185EBCA87)
        ^ iy.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)
        ^ iz.astype(np.uint64) * np.uint64(0x165667B19E3779F9)
        ^ np.uint64((seed * 0x27D4EB2F165667C5) & 0xFFFFFFFFFFFFFFFF)
    )
    h ^= h >> np.uint64(30)
    h *= np.uint64(0xBF58476D1CE4E5B9)
    h ^= h >> np.uint64(27)
    h *= np.uint64(0x94D049BB133111EB)
    h ^= h >> np.uint64(31)
    top_bits: FloatArray = (h >> np.uint64(11)).astype(np.float64)
    return top_bits / float(1 << 53)


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


def _curve_points(stage: Usd.Stage, prim_path: str) -> tuple[FloatArray, bool, FloatArray]:
    """World-space control points of the first curve on a BasisCurves prim."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid() or not prim.IsA(UsdGeom.BasisCurves):
        msg = f"curve_prim {prim_path} is not a BasisCurves prim."
        raise ValueError(msg)
    curves = UsdGeom.BasisCurves(prim)
    points = np.asarray(curves.GetPointsAttr().Get() or [], dtype=np.float64)
    counts = curves.GetCurveVertexCountsAttr().Get() or [len(points)]
    points = points[: int(counts[0])]
    if points.shape[0] < 2:
        msg = f"curve_prim {prim_path} has fewer than 2 points."
        raise ValueError(msg)
    world = gf_matrix_to_numpy(
        UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()),
    )
    points = points @ world[:3, :3] + world[3, :3]
    closed = curves.GetWrapAttr().Get() == UsdGeom.Tokens.periodic
    return points, closed, points.mean(axis=0)


def _plan_length(points: FloatArray, closed: bool, up: int) -> float:
    pts = np.vstack([points, points[:1]]) if closed else points
    axes = list(horizontal_axes(up))
    seg = np.diff(pts[:, axes], axis=0)
    return float(np.hypot(seg[:, 0], seg[:, 1]).sum())


def _segment_direction(
    points: FloatArray, closed: bool, up: int, stations: FloatArray,
) -> FloatArray:
    """Direction of the path segment containing each station (tangent fallback)."""
    pts = np.vstack([points, points[:1]]) if closed else points
    axes = list(horizontal_axes(up))
    seg = np.diff(pts, axis=0)
    seg[:, up] = 0.0
    seg_len = np.hypot(*seg[:, axes].T)
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    s = np.mod(stations, cum[-1]) if closed else np.clip(stations, 0.0, cum[-1])
    k = np.clip(np.searchsorted(cum, s, side="right") - 1, 0, seg.shape[0] - 1)
    return seg[k]


def _side_and_front_axes(up: int) -> tuple[int, int]:
    """Prototype side axis (X) and front axis (Z for Y-up, Y for Z-up)."""
    return 0, (2 if up == 1 else 1)


def _front_vector(up: int) -> FloatArray:
    """Prototype front direction: +Z in Y-up scenes, -Y in Z-up scenes."""
    return np.array([0.0, 0.0, 1.0]) if up == 1 else np.array([0.0, -1.0, 0.0])


def _signed_angle(src: FloatArray, dst: FloatArray, axis: FloatArray) -> FloatArray:
    """Signed angle (radians) about *axis* turning each *src* onto each *dst*."""
    src = np.broadcast_to(src, dst.shape)
    cross = np.cross(src, dst)
    return np.arctan2(cross @ axis, (src * dst).sum(axis=1))


def _is_placement_wrapper(prim: Usd.Prim) -> bool:
    """A scene placement wrapper: an Xformable whose ``asset`` child carries a reference."""
    child = prim.GetChild("asset")
    return (
        prim.IsA(UsdGeom.Xformable)
        and child.IsValid()
        and bool(get_prim_ref_paths(child))
    )


def _smallest_rotate_xyz(rx: float, ry: float, rz: float) -> tuple[float, float, float]:
    """Smaller of the two equivalent rotateXYZ triples, so a yaw stays (0, yaw, 0)."""
    def wrap(angle: float) -> float:
        wrapped = (angle + 180.0) % 360.0 - 180.0
        return 0.0 if abs(wrapped) < 1e-6 else round(wrapped, 4)

    first = (wrap(rx), wrap(ry), wrap(rz))
    second = (wrap(rx + 180.0), wrap(180.0 - ry), wrap(rz + 180.0))
    return min(first, second, key=lambda angles: sum(abs(a) for a in angles))


def _rotate_xyz_rotation(value: Any) -> Gf.Rotation:
    """Gf.Rotation equal to an xformOp:rotateXYZ value (X applied first)."""
    rx, ry, rz = (float(v) for v in (value or (0.0, 0.0, 0.0)))
    return (
        Gf.Rotation(Gf.Vec3d.XAxis(), rx)
        * Gf.Rotation(Gf.Vec3d.YAxis(), ry)
        * Gf.Rotation(Gf.Vec3d.ZAxis(), rz)
    )


def _region_circle(region: ScatterRegion) -> tuple[FloatArray, float]:
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


def _pile_setup(surface: ScatterSurfaceParams) -> tuple[int, FloatArray, float]:
    """A pile's piece count, centre and base radius."""
    region = surface.region
    if surface.count is None or region is None or region.polygon is not None:
        msg = "arrangement 'pile' needs a count and a circular region."
        raise ValueError(msg)
    center, radius = _region_circle(region)
    return surface.count, center, radius
