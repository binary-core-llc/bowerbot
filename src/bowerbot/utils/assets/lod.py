# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""LOD — bring a library geometry file into an asset folder as one of its LOD layers."""

from __future__ import annotations

import math
from pathlib import Path

from pxr import Gf, Usd, UsdGeom, UsdUtils

from bowerbot.schemas import AssetFormat, LodRules
from bowerbot.utils.assets.freeze import freeze_root_transform, root_transform_is_identity
from bowerbot.utils.assets.localize import localize
from bowerbot.utils.core.asset_folder import detect_folder_root, read_stage_metadata_from_dir
from bowerbot.utils.core.metrics import conform_between, read_stage_metadata
from bowerbot.utils.library_utils import asset_location, find_asset, find_package_for


def lod_source(ref: str, asset_dir: Path, library_dir: Path | None) -> Path | None:
    """The library file an LOD reference names, or ``None`` for a file of *asset_dir* itself.

    *ref* is a file in the asset folder (``./geo_low.usda``), a loose library
    file's name as ``search_assets`` reports it, or a library location
    (``chair/geo_low.usda``). A whole library asset (a folder's root file, or
    a ``.usdz``) is refused: it is a separate asset, which a model-selection
    variant references instead.
    """
    if ref.startswith("./") or (asset_dir / ref).is_file():
        return None
    source = find_asset(ref, library_dir=library_dir, project_assets_dir=None)
    package = find_package_for(source, library_dir) if library_dir is not None else None
    package_root = detect_folder_root(package).root if package is not None else None
    if source.suffix.lower() == AssetFormat.USDZ or (
        package_root is not None and Path(package_root).resolve() == source.resolve()
    ):
        folder = asset_location(source.parent, library_dir=library_dir, project_dir=None)
        msg = (
            f"'{ref}' is a whole asset, not a geometry file. Use it as its own "
            f"variant with add_scene_model_selection_variant, or pass the geometry "
            f"file inside it (e.g. '{folder}/geo.usda')."
        )
        raise ValueError(msg)
    return source


def add_lod_file(
    asset_dir: Path, source: Path, variant_name: str, *, conform_units: bool,
) -> str:
    """Copy *source* into *asset_dir* as ``geo_<variant>`` with what it uses; return its path.

    The copy must carry the asset's units and up axis, since switching a variant
    converts nothing. When they differ, *conform_units* puts the conversion
    (scale, then the up-axis turn) in front of each part's own transform, as
    ``xformOp:transform:conform``, and states the asset's units on the copy;
    without it the file is refused. The library file is never touched.
    """
    suffix = source.suffix.lower()
    target = asset_dir / f"{LodRules.FILE_PREFIX}{variant_name}{suffix}"
    if target.exists():
        msg = (
            f"{asset_dir.name}/{target.name} already exists. Pass './{target.name}' to "
            f"use it, or pick another variant name."
        )
        raise ValueError(msg)
    _require_placeable_root(source)

    asset_mpu, asset_up = read_stage_metadata_from_dir(asset_dir)
    source_mpu, source_up = read_stage_metadata(source)
    unit_scale, correction = conform_between(asset_mpu, asset_up, source_mpu, source_up)
    converts = not math.isclose(unit_scale, 1.0) or correction is not None
    if converts and not conform_units:
        msg = (
            f"{source.name} is {source_up}-up at {source_mpu} meters per unit; "
            f"{asset_dir.name} is {asset_up}-up at {asset_mpu}. A variant switch "
            f"converts nothing, so it would show at the wrong size or orientation. "
            f"Retry with conform_units=true to convert the project's copy (the "
            f"library file stays as it is), or re-export it to match."
        )
        raise ValueError(msg)

    localize(source, source.parent, target)
    if converts:
        # The conversion goes on the copy's root, then moves onto the parts the
        # way a freeze does, so every part converts exactly and the root stays identity.
        _conform_root(target, unit_scale, correction)
        freeze_root_transform(target, op_suffix=LodRules.CONFORM_OP_SUFFIX)
    stage = Usd.Stage.Open(str(target))
    UsdGeom.SetStageMetersPerUnit(stage, asset_mpu)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z if asset_up == "Z" else UsdGeom.Tokens.y)
    stage.GetRootLayer().Save()
    return f"./{target.name}"


def library_alternates(asset_dir: Path, library_dir: Path | None) -> list[str]:
    """Library locations of the geometry files the asset's library folder has but doesn't use.

    Empty when the asset did not come from a library folder (a loose file), or
    when its name matches more than one library asset.
    """
    if library_dir is None:
        return []
    try:
        root = find_asset(asset_dir.name, library_dir=library_dir, project_assets_dir=None)
    except ValueError:
        return []
    package = find_package_for(root, library_dir)
    if package is None:
        return []
    layers, _, _ = UsdUtils.ComputeAllDependencies(str(root))
    used = {Path(layer.realPath).resolve() for layer in layers}
    return [
        asset_location(path, library_dir=library_dir, project_dir=None)
        for path in sorted(package.rglob("*"))
        if path.is_file() and path.suffix.lower() in AssetFormat.layer_formats()
        and path.resolve() not in used
    ]


def _require_placeable_root(source: Path) -> None:
    """Refuse a file whose default prim couldn't sit on an asset's root prim."""
    stage = Usd.Stage.Open(str(source))
    root = stage.GetDefaultPrim() if stage is not None else None
    if root is None or not root.IsValid() or not root.IsA(UsdGeom.Xform):
        msg = (
            f"{source.name} can't be an LOD: its default prim must be an Xform "
            f"holding the parts, since it lands on the asset's root prim."
        )
        raise ValueError(msg)
    if not root_transform_is_identity(source):
        msg = (
            f"{source.name} can't be an LOD: its default prim has a transform of its "
            f"own, which would move the asset's root. Freeze it in your DCC and re-export."
        )
        raise ValueError(msg)


def _conform_root(target: Path, unit_scale: float, correction: float | None) -> None:
    """Author the unit scale, then the up-axis turn, on the copy's (identity) root prim."""
    stage = Usd.Stage.Open(str(target))
    root = UsdGeom.Xformable(stage.GetDefaultPrim())
    if correction is not None:
        root.AddRotateXOp(opSuffix=LodRules.CONFORM_OP_SUFFIX).Set(correction)
    if not math.isclose(unit_scale, 1.0):
        root.AddScaleOp(opSuffix=LodRules.CONFORM_OP_SUFFIX).Set(
            Gf.Vec3f(unit_scale, unit_scale, unit_scale),
        )
    stage.GetRootLayer().Save()
