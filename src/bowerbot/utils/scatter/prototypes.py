# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter prototypes — staging assets to instance, with their bounds, bases and points."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from pxr import Gf, Usd, UsdGeom

from bowerbot.schemas import (
    ScatterAsset,
    ScatterAssetOrder,
    ScatterPrototype,
    ScatterTuning,
    SurfaceTuning,
)
from bowerbot.schemas.surface import FloatArray, IntArray
from bowerbot.utils import asset_intake_utils, layout_utils, surface_utils
from bowerbot.utils.core.bounds import bbox_cache, world_range
from bowerbot.utils.core.metrics import asset_conform, axis_index
from bowerbot.utils.core.naming import is_valid_prim_name, safe_prim_name
from bowerbot.utils.core.transforms import gf_matrix_to_numpy


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


def prototype_bases(
    prototypes: list[ScatterPrototype], proto_idx: IntArray,
) -> tuple[FloatArray, FloatArray]:
    """Per-instance ``(base_min, base_max)`` of each instance's prototype."""
    base_min = np.stack([p.base_min for p in prototypes])[proto_idx]
    base_max = np.stack([p.base_max for p in prototypes])[proto_idx]
    return base_min, base_max


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
    base_min, base_max = base_footprint(points, up)
    shape = np.unique(points, axis=0)
    if shape.shape[0] > ScatterTuning.SHAPE_POINTS:
        picks = np.linspace(0, shape.shape[0] - 1, ScatterTuning.SHAPE_POINTS).astype(np.int64)
        shape = shape[picks]
    return corners.min(axis=0), corners.max(axis=0), base_min, base_max, shape


def base_footprint(points: FloatArray, up: int) -> tuple[FloatArray, FloatArray]:
    """Box around the lowest slice of *points*: what meets the ground when upright."""
    bottom = float(points[:, up].min())
    top = float(points[:, up].max())
    cut = bottom + ScatterTuning.BASE_SLICE * (top - bottom) + SurfaceTuning.EPS
    base = points[points[:, up] <= cut]
    base_min = base.min(axis=0)
    base_max = base.max(axis=0)
    base_min[up] = base_max[up] = bottom
    return base_min, base_max


def prototype_points(stage: Usd.Stage, prim_path: str, up: int) -> FloatArray:
    """World-space vertices of a prototype, or its box corners if it has no mesh."""
    triangles = surface_utils.collect_triangles(stage, [prim_path], up=up)
    if triangles.count:
        return np.concatenate([triangles.v0, triangles.v1, triangles.v2])
    rng = world_range(stage.GetPrimAtPath(prim_path), bbox_cache(include_render=True))
    if rng is None:
        msg = f"Prototype {prim_path} has no geometry, so it cannot rest on a surface."
        raise ValueError(msg)
    return np.array([list(rng.GetCorner(i)) for i in range(8)])
