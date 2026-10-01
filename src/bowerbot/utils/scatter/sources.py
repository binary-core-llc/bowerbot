# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Turning the asset mix into prototypes: resolving each asset and measuring its bounds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from pxr import Gf
from pxr import Usd

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import usd


def resolve_asset_sources(
    assets: list[schemas.ScatterAsset],
    *,
    project_dir: Path | None,
    library_dir: Path | None,
) -> list[tuple[schemas.ScatterAsset, Path]]:
    """Resolve every asset in the mix to a root file, reporting all problems at once."""
    problems: list[str] = []
    resolved: list[tuple[schemas.ScatterAsset, Path]] = []
    targets: dict[str, Path] = {}
    for idx, entry in enumerate(assets):
        try:
            path = authoring.library.resolve_layout_asset(
                entry.asset, project_dir=project_dir, library_dir=library_dir,
            )
        except ValueError as e:
            problems.append(f"assets[{idx}]: {e}")
            continue
        target = authoring.intake.intake_target_name(path, library_dir)
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
    sources: list[tuple[schemas.ScatterAsset, Path]],
    *,
    assets_dir: Path,
    library_dir: Path | None,
    project_dir: Path,
    project_mpu: float,
    project_up_axis: str,
) -> list[schemas.ScatterPrototype]:
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
            reports[path] = authoring.intake.prepare_asset(
                path, assets_dir, library_dir=library_dir,
                project_mpu=project_mpu, project_up_axis=project_up_axis,
                fix_root_prim=fix_prim[path], fix_root_transforms=fix_xform[path],
            )
        except (ValueError, RuntimeError) as e:
            problems.append(f"{path.name}: {e}")
    if problems:
        summary = f"asset intake failed ({len(problems)} asset(s)):"
        raise ValueError("\n".join([summary, *problems]))

    up = usd.metrics.axis_index(project_up_axis)
    prototypes: list[schemas.ScatterPrototype] = []
    used: set[str] = set()
    for entry, path in sources:
        report = reports[path]
        root_file = project_dir / report.scene_ref_path
        asset_mpu, asset_up_axis = usd.metrics.file_metrics(
            root_file, default_mpu=project_mpu, default_up_axis=project_up_axis,
        )
        conform = usd.metrics.conform_matrix(*usd.metrics.conform(
            asset_mpu, asset_up_axis,
            parent_mpu=project_mpu, parent_up_axis=project_up_axis,
        ))
        bmin, bmax, base_min, base_max, points = _conformed_extents(
            root_file, conform, up=up, asset_up=usd.metrics.axis_index(asset_up_axis),
        )
        base = usd.naming.safe_prim_name(Path(report.asset_folder_name).stem) or "proto"
        if not usd.naming.is_valid_prim_name(base):
            base = f"proto_{base}"
        name = base
        n = 2
        while name in used:
            name = f"{base}_{n}"
            n += 1
        used.add(name)
        prototypes.append(schemas.ScatterPrototype(
            name=name, source=str(path), scene_ref=report.scene_ref_path,
            weight=entry.weight,
            bounds_min=tuple(bmin.tolist()), bounds_max=tuple(bmax.tolist()),
            base_min=tuple(base_min.tolist()), base_max=tuple(base_max.tolist()),
            points=points,
        ))
    return prototypes


def base_footprint(
    points: schemas.FloatArray, up: int,
) -> tuple[schemas.FloatArray, schemas.FloatArray]:
    """Box around the lowest slice of *points*: what meets the ground when upright."""
    bottom = float(points[:, up].min())
    top = float(points[:, up].max())
    cutoff = (
        bottom + constants.ScatterTuning.BASE_SLICE * (top - bottom)
        + constants.SurfaceTuning.EPSILON
    )
    base = points[points[:, up] <= cutoff]
    base_min = base.min(axis=0)
    base_max = base.max(axis=0)
    base_min[up] = base_max[up] = bottom
    return base_min, base_max


# ── Helpers ──


def _conformed_extents(
    root_file: Path, conform: Gf.Matrix4d, *, up: int, asset_up: int,
) -> tuple[
    schemas.FloatArray, schemas.FloatArray, schemas.FloatArray, schemas.FloatArray,
    schemas.FloatArray,
]:
    """Bounds, base footprint and vertex sample of an asset, after its placement *conform*."""
    stage = Usd.Stage.Open(str(root_file))
    root = stage.GetDefaultPrim() if stage else None
    if root is None or not root.IsValid():
        msg = f"{root_file.name} has no default prim to measure."
        raise ValueError(msg)
    rng = usd.bounds.world_range(root, usd.bounds.bounds_cache(include_render=True))
    if rng is None:
        msg = f"{root_file.name} has no geometry bounds, so it cannot rest on a surface."
        raise ValueError(msg)
    corners = usd.bounds.range_corners(rng)
    triangles = usd.surface.collect_triangles(
        stage, [str(root.GetPath())], up=asset_up,
    )
    points = (
        np.concatenate([
            triangles.v0, triangles.v1, triangles.v2,
            (triangles.v0 + triangles.v1 + triangles.v2) / 3.0,
        ])
        if triangles.count else corners
    )
    matrix = usd.transforms.gf_matrix_to_numpy(conform)[:3, :3]
    corners = corners @ matrix
    points = points @ matrix
    base_min, base_max = base_footprint(points, up)
    shape = np.unique(points, axis=0)
    if shape.shape[0] > constants.ScatterTuning.SHAPE_POINTS:
        picks = np.linspace(
            0, shape.shape[0] - 1, constants.ScatterTuning.SHAPE_POINTS,
        ).astype(np.int64)
        shape = shape[picks]
    return corners.min(axis=0), corners.max(axis=0), base_min, base_max, shape
