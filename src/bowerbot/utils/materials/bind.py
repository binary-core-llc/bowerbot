# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Binding a material from a file, removing a binding, and the shared-asset check."""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Sdf
from pxr import Usd
from pxr import UsdShade

from bowerbot import constants
from bowerbot.utils import authoring
from bowerbot.utils import materials

logger = logging.getLogger(__name__)


def bind_from_file(
    asset_dir: Path,
    material_file: Path,
    prim_path: str,
    material_prim_path: str | None = None,
) -> str:
    """Copy a material into ``mtl.usda`` and bind it to *prim_path*."""
    mtl_path = asset_dir / constants.ASWFLayerNames.MTL

    if not material_prim_path:
        material_prim_path = find_first_material(material_file)
        if not material_prim_path:
            msg = f"No Material prim found in {material_file.name}"
            raise ValueError(msg)

    mtl_layer = (
        Sdf.Layer.FindOrOpen(str(mtl_path))
        if mtl_path.exists()
        else Sdf.Layer.CreateNew(str(mtl_path))
    )

    source_layer = Sdf.Layer.FindOrOpen(str(material_file))
    if source_layer is None:
        msg = f"Cannot open material file: {material_file}"
        raise RuntimeError(msg)

    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    authoring.asset_folder.ensure_layer_scope(mtl_layer, default_prim_name, "mtl", "Scope")

    mat_name = Sdf.Path(material_prim_path).name
    dest_mat_path = Sdf.Path(f"/{default_prim_name}/mtl/{mat_name}")
    Sdf.CopySpec(
        source_layer, Sdf.Path(material_prim_path),
        mtl_layer, dest_mat_path,
    )

    mtl_layer.defaultPrim = default_prim_name
    mtl_layer.Save()

    local_prim_path = authoring.asset_folder.to_layer_local_path(prim_path, default_prim_name)
    composed_mat_path = f"/{default_prim_name}/mtl/{mat_name}"

    stage = Usd.Stage.Open(str(mtl_path))
    if stage is not None:
        prim = stage.OverridePrim(local_prim_path)
        mat_prim = stage.GetPrimAtPath(composed_mat_path)
        if mat_prim.IsValid():
            material = UsdShade.Material(mat_prim)
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
        stage.Save()

    authoring.asset_folder.ensure_root_reference(asset_dir, constants.ASWFLayerNames.MTL)

    logger.info(
        "Added material %s -> %s in %s",
        composed_mat_path, prim_path, asset_dir.name,
    )
    return composed_mat_path


def unbind(asset_dir: Path, prim_path: str) -> None:
    """Clear a binding and garbage-collect unused materials + the layer."""
    mtl_path = asset_dir / constants.ASWFLayerNames.MTL
    if not mtl_path.exists():
        return

    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    local_path = authoring.asset_folder.to_layer_local_path(prim_path, default_prim_name)

    stage = Usd.Stage.Open(str(mtl_path))
    if stage is None:
        return

    prim = stage.GetPrimAtPath(local_path)
    if prim.IsValid():
        UsdShade.MaterialBindingAPI(prim).UnbindAllBindings()

    stage.Save()
    materials.layer.remove_unused(asset_dir)


def refuse_shared_modification(
    stage: Usd.Stage, asset_dir: Path, params: dict, *, op_label: str,
) -> None:
    """Refuse if *asset_dir* is referenced by 2+ scene instances and not confirmed."""
    instance_count = authoring.placement.count_scene_refs_to_asset_dir(stage, asset_dir)
    confirmed = bool(params.get("confirm_shared_modification", False))
    if instance_count >= 2 and not confirmed:
        msg = (
            f"Asset folder '{asset_dir.name}/' is referenced by "
            f"{instance_count} scene instances. {op_label} writes to the "
            f"shared {constants.ASWFLayerNames.MTL}, so the binding would apply to "
            f"all {instance_count} instances. Two ways forward: "
            f"(1) For per-instance materials (different material per "
            f"instance), use place_asset to make each instance independent, "
            f"then bind a material on each. "
            f"(2) For deliberate shared modification (every instance "
            f"should get this material), retry with "
            f"confirm_shared_modification=true."
        )
        raise ValueError(msg)


def find_first_material(file_path: Path) -> str | None:
    """Return the prim path of the first Material in *file_path*, or ``None``."""
    stage = Usd.Stage.Open(str(file_path))
    if stage is None:
        return None
    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Material):
            return str(prim.GetPath())
    return None
