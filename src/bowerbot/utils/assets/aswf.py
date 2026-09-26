# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""ASWF wrapping — turning loose files into ASWF asset folders with root metadata."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom

from bowerbot.schemas import (
    AssetFormat,
    ASWFLayerNames,
)
from bowerbot.utils.assets.freeze import bake_root_transforms, root_transform_is_identity
from bowerbot.utils.core.metrics import read_stage_metadata

logger = logging.getLogger(__name__)


def create_asset_folder(
    output_dir: Path,
    asset_name: str,
    geometry_file: Path,
) -> Path:
    """Create an ASWF asset folder with root + ``geo.usda``."""
    asset_dir = output_dir / asset_name
    asset_dir.mkdir(parents=True, exist_ok=True)

    mpu, up = read_stage_metadata(geometry_file)

    geo_path = asset_dir / ASWFLayerNames.GEO
    if not geo_path.exists():
        _create_geo_layer(geo_path, geometry_file)

    root_path = asset_dir / f"{asset_name}.usda"
    if not root_path.exists():
        _create_root_file(root_path, mpu, up)

    logger.info("Created ASWF asset folder: %s", asset_dir)
    return root_path


def ensure_aswf_compliance(
    geometry_file: Path,
    *,
    fix_root_prim: bool = False,
    fix_root_transforms: bool = False,
) -> None:
    """Validate and (optionally) repair a geometry file for ASWF compliance."""
    layer = Sdf.Layer.FindOrOpen(str(geometry_file))
    if layer is None:
        msg = f"Cannot open geometry file: {geometry_file.name}"
        raise ValueError(msg)

    root_prims = list(layer.rootPrims)

    if not root_prims:
        msg = (
            f"Asset '{geometry_file.name}' contains no geometry. "
            f"Export it from your DCC with geometry under a root prim."
        )
        raise ValueError(msg)

    if not layer.defaultPrim:
        if len(root_prims) == 1:
            layer.defaultPrim = root_prims[0].name
            layer.Save()
            logger.info(
                "Auto-set defaultPrim to '%s' in %s",
                root_prims[0].name, geometry_file.name,
            )
        else:
            prim_names = ", ".join(p.name for p in root_prims)
            msg = (
                f"Asset '{geometry_file.name}' has multiple root prims "
                f"({prim_names}) and no defaultPrim. Export it from your "
                f"DCC with a single root Xform."
            )
            raise ValueError(msg)

    root_spec = layer.GetPrimAtPath(Sdf.Path(f"/{layer.defaultPrim}"))
    if root_spec is None:
        msg = (
            f"Asset '{geometry_file.name}' has defaultPrim "
            f"'{layer.defaultPrim}' but that prim does not exist."
        )
        raise ValueError(msg)

    if root_spec.typeName not in ("Xform", ""):
        if not fix_root_prim:
            msg = (
                f"Asset '{geometry_file.name}' has a {root_spec.typeName} "
                f"as its root prim instead of an Xform. Per ASWF USD "
                f"guidelines, the root prim should be an Xform with "
                f"geometry as children. Ask the user if they want to "
                f"fix this automatically, then call place_asset again "
                f"with fix_root_prim set to true."
            )
            raise ValueError(msg)
        _wrap_root_prim(geometry_file)
        logger.info(
            "Wrapped %s root prim in Xform for ASWF compliance",
            geometry_file.name,
        )

    if not root_transform_is_identity(geometry_file):
        if not fix_root_transforms:
            msg = (
                f"Asset '{geometry_file.name}' has non-identity transforms "
                f"baked on its root prim (translate/rotate/scale/pivot from "
                f"an unfrozen DCC export). Production USD assets must have "
                f"identity root transforms or nested placement breaks. Ask "
                f"the user if they want BowerBot to bake the transforms into "
                f"vertex data automatically — this only modifies the project "
                f"copy, the user's original source file is untouched. If they "
                f"confirm, call place_asset again with fix_root_transforms=true. "
                f"Alternatively, advise them to re-export from their DCC with "
                f"transforms frozen ('Bake Transforms' in Maya USD export, "
                f"'Pre-freeze' in Houdini)."
            )
            raise ValueError(msg)
        bake_root_transforms(geometry_file)
        logger.info("Baked root transforms in %s", geometry_file.name)


def normalize_root_metadata(root_file: Path, asset_name: str) -> None:
    """Ensure the intaken asset's root prim has Kind + assetInfo + class inherit."""
    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return
    root_prim = stage.GetDefaultPrim()
    if not root_prim or not root_prim.IsValid():
        return

    apply_aswf_root_metadata(
        root_prim,
        asset_name=asset_name,
        asset_identifier=f"./{root_file.name}",
    )
    _apply_aswf_class_inherits(stage, root_prim.GetName())
    stage.Save()


def _create_geo_layer(geo_dest: Path, geometry_source: Path) -> None:
    """Copy geometry into ``geo.usda`` using Sdf layer copy."""
    source_layer = Sdf.Layer.FindOrOpen(str(geometry_source))
    if source_layer is None:
        msg = f"Cannot open geometry source: {geometry_source}"
        raise RuntimeError(msg)

    dest_layer = Sdf.Layer.CreateNew(str(geo_dest))
    for prim_spec in source_layer.rootPrims:
        Sdf.CopySpec(
            source_layer, prim_spec.path, dest_layer, prim_spec.path,
        )
    dest_layer.defaultPrim = source_layer.defaultPrim
    dest_layer.Save()


def _create_root_file(
    root_path: Path,
    meters_per_unit: float,
    up_axis: str,
) -> None:
    """Write the root .usd that references ``geo.usda``."""
    geo_path = root_path.parent / ASWFLayerNames.GEO
    default_prim_name = root_path.parent.name
    if geo_path.exists():
        geo_layer = Sdf.Layer.FindOrOpen(str(geo_path))
        if geo_layer and geo_layer.defaultPrim:
            default_prim_name = geo_layer.defaultPrim

    stage = Usd.Stage.CreateNew(str(root_path))
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    UsdGeom.SetStageUpAxis(
        stage, UsdGeom.Tokens.y if up_axis == "Y" else UsdGeom.Tokens.z,
    )

    root_prim = stage.DefinePrim(f"/{default_prim_name}", "Xform")
    stage.SetDefaultPrim(root_prim)
    root_prim.GetPayloads().AddPayload(f"./{ASWFLayerNames.GEO}")

    apply_aswf_root_metadata(
        root_prim,
        asset_name=root_path.parent.name,
        asset_identifier=f"./{root_path.name}",
        force=True,
    )
    _apply_aswf_class_inherits(stage, default_prim_name)

    stage.Save()


def _apply_aswf_class_inherits(
    stage: Usd.Stage, default_prim_name: str,
) -> bool:
    """Add a sibling ``class _class_<name>`` and inherit it from the root."""
    class_path = f"/_class_{default_prim_name}"
    class_prim = stage.GetPrimAtPath(class_path)
    if not class_prim or not class_prim.IsValid():
        class_prim = stage.OverridePrim(class_path)
        class_prim.SetSpecifier(Sdf.SpecifierClass)
        class_prim.SetTypeName("Xform")

    root_prim = stage.GetDefaultPrim()
    if not root_prim or not root_prim.IsValid():
        return False
    inherits = root_prim.GetInherits()
    existing = inherits.GetAllDirectInherits()
    if Sdf.Path(class_path) in existing:
        return False
    inherits.AddInherit(class_path)
    return True


def apply_aswf_root_metadata(
    prim: Usd.Prim,
    *,
    asset_name: str,
    asset_identifier: str,
    kind: str = "component",
    version: str = "1.0",
    force: bool = False,
) -> None:
    """Apply ASWF-canonical Kind + assetInfo to an asset root prim.

    When *force* is False, only fills missing fields, preserving any
    metadata already authored upstream (DCC, asset-management system).
    """
    model_api = Usd.ModelAPI(prim)
    if force or not model_api.GetKind():
        model_api.SetKind(kind)

    existing = prim.GetAssetInfo() or {}
    info = dict(existing) if not force else {}
    info.setdefault("identifier", Sdf.AssetPath(asset_identifier))
    info.setdefault("name", asset_name)
    info.setdefault("version", version)
    if force:
        info["identifier"] = Sdf.AssetPath(asset_identifier)
        info["name"] = asset_name
        info["version"] = version
    prim.SetAssetInfo(info)


def _wrap_root_prim(geometry_file: Path) -> None:
    """Wrap a non-Xform root prim under an Xform parent in place."""
    source_layer = Sdf.Layer.FindOrOpen(str(geometry_file))
    if source_layer is None:
        return

    default_prim_name = source_layer.defaultPrim
    if not default_prim_name:
        return

    root_path = Sdf.Path(f"/{default_prim_name}")
    root_spec = source_layer.GetPrimAtPath(root_path)
    if root_spec is None or root_spec.typeName in ("Xform", ""):
        return

    with tempfile.NamedTemporaryFile(suffix=AssetFormat.USDA, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        dest_layer = Sdf.Layer.CreateNew(str(tmp_path))

        Sdf.CreatePrimInLayer(dest_layer, root_path)
        wrapper = dest_layer.GetPrimAtPath(root_path)
        wrapper.specifier = Sdf.SpecifierDef
        wrapper.typeName = "Xform"

        child_path = Sdf.Path(f"/{default_prim_name}/mesh")
        Sdf.CopySpec(source_layer, root_path, dest_layer, child_path)

        dest_layer.defaultPrim = default_prim_name
        dest_layer.Save()

        shutil.move(str(tmp_path), str(geometry_file))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
