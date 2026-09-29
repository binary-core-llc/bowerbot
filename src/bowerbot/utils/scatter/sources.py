# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Turning the asset mix into prototypes: resolving each asset and measuring its bounds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from pxr import Gf
from pxr import Usd
from pxr import UsdGeom

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
    stage: Usd.Stage,
    sources: list[tuple[schemas.ScatterAsset, Path]],
    *,
    assets_dir: Path,
    library_dir: Path | None,
    project_dir: Path,
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
                fix_root_prim=fix_prim[path], fix_root_transforms=fix_xform[path],
            )
        except (ValueError, RuntimeError) as e:
            problems.append(f"{path.name}: {e}")
    if problems:
        summary = f"asset intake failed ({len(problems)} asset(s)):"
        raise ValueError("\n".join([summary, *problems]))

    up = usd.metrics.axis_index(UsdGeom.GetStageUpAxis(stage))
    prototypes: list[schemas.ScatterPrototype] = []
    used: set[str] = set()
    for entry, path in sources:
        report = reports[path]
        unit_scale, correction = usd.metrics.asset_conform(stage, report.scene_ref_path)
        bmin, bmax, base_min, base_max, points = _conformed_extents(
            project_dir / report.scene_ref_path, unit_scale, correction, up,
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
    root_file: Path, unit_scale: float, correction: float | None, up: int,
) -> tuple[
    schemas.FloatArray, schemas.FloatArray, schemas.FloatArray, schemas.FloatArray,
    schemas.FloatArray,
]:
    """Conformed bounds, base footprint and vertex sample of an asset."""
    stage = Usd.Stage.Open(str(root_file))
    root = stage.GetDefaultPrim() if stage else None
    if root is None or not root.IsValid():
        msg = f"{root_file.name} has no default prim to measure."
        raise ValueError(msg)
    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render],
    )
    rng = cache.ComputeWorldBound(root).ComputeAlignedRange()
    if rng.IsEmpty():
        msg = f"{root_file.name} has no geometry bounds, so it cannot rest on a surface."
        raise ValueError(msg)
    corners = np.array([list(rng.GetCorner(i)) for i in range(8)])
    triangles = usd.surface.collect_triangles(
        stage, [str(root.GetPath())],
        up=usd.metrics.axis_index(UsdGeom.GetStageUpAxis(stage)),
    )
    points = (
        np.concatenate([
            triangles.v0, triangles.v1, triangles.v2,
            (triangles.v0 + triangles.v1 + triangles.v2) / 3.0,
        ])
        if triangles.count else corners
    )
    if correction is not None:
        rotate = usd.transforms.gf_matrix_to_numpy(
            Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d.XAxis(), correction)),
        )[:3, :3]
        corners = corners @ rotate
        points = points @ rotate
    corners *= unit_scale
    points *= unit_scale
    base_min, base_max = base_footprint(points, up)
    shape = np.unique(points, axis=0)
    if shape.shape[0] > constants.ScatterTuning.SHAPE_POINTS:
        picks = np.linspace(
            0, shape.shape[0] - 1, constants.ScatterTuning.SHAPE_POINTS,
        ).astype(np.int64)
        shape = shape[picks]
    return corners.min(axis=0), corners.max(axis=0), base_min, base_max, shape
