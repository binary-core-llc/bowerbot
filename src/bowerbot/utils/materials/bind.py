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
from bowerbot.utils import usd

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

    source_layer = Sdf.Layer.FindOrOpen(str(material_file))
    if source_layer is None:
        msg = f"Cannot open material file: {material_file}"
        raise RuntimeError(msg)

    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    require_target(asset_dir, prim_path)
    mtl_layer = authoring.asset_folder.open_scope_layer(
        asset_dir, constants.ASWFLayerNames.MTL,
        constants.AssetFolderNamespace.MATERIALS_SCOPE, "Scope",
    )

    mat_name = Sdf.Path(material_prim_path).name
    dest_mat_path = Sdf.Path(f"/{default_prim_name}/mtl/{mat_name}")
    Sdf.CopySpec(
        source_layer, Sdf.Path(material_prim_path),
        mtl_layer, dest_mat_path,
    )

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


def require_target(asset_dir: Path, prim_path: str) -> None:
    """Refuse a material for a prim the asset does not have."""
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    stage = Usd.Stage.Open(str(root_file)) if root_file is not None else None
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    local_path = authoring.asset_folder.to_layer_local_path(prim_path, default_prim_name)
    prim = stage.GetPrimAtPath(local_path) if stage is not None else None
    if prim is None or not prim.IsValid():
        raise ValueError(f"Prim not found in asset {asset_dir.name}: {prim_path}")


def unbind(asset_dir: Path, prim_path: str) -> bool:
    """Remove a prim's look binding from the asset's files, then the materials left unused.

    Returns False when the prim had no binding of its own.
    """
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    stage = Usd.Stage.Open(str(root_file)) if root_file is not None else None
    if stage is None:
        return False

    edited: dict[str, Sdf.Layer] = {}
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    local_path = authoring.asset_folder.to_layer_local_path(prim_path, default_prim_name)
    prim = stage.GetPrimAtPath(local_path)
    if prim.IsValid():
        folder = asset_dir.resolve()
        # Only the bindings that give the prim its look: USD's own material purposes.
        # A binding for another purpose (physics) belongs to the tools of that domain.
        binding_api = UsdShade.MaterialBindingAPI(prim)
        binding_specs = [
            (spec.layer, spec.owner.path, spec.name)
            for purpose in UsdShade.MaterialBindingAPI.GetMaterialPurposes()
            for rel in (
                binding_api.GetDirectBindingRel(purpose),
                *binding_api.GetCollectionBindingRels(purpose),
            )
            if rel
            for spec in rel.GetPropertyStack(Usd.TimeCode.Default())
        ]
        prim_specs = [(spec.layer, spec.path) for spec in prim.GetPrimStack()]
        del binding_api, prim, stage

        api_name = Usd.SchemaRegistry().GetAPISchemaTypeName(UsdShade.MaterialBindingAPI)
        for layer, owner_path, name in binding_specs:
            if folder not in Path(layer.realPath).resolve().parents:
                continue
            owner = layer.GetPrimAtPath(owner_path)
            owner.RemoveProperty(owner.relationships[name])
            edited[layer.identifier] = layer
        for layer, spec_path in prim_specs:
            if layer.identifier not in edited:
                continue
            spec = layer.GetPrimAtPath(spec_path)
            if spec is not None:
                still_binds = any(
                    name.startswith(UsdShade.Tokens.materialBinding)
                    for name in spec.relationships.keys()
                )
                if not still_binds:
                    usd.attributes.drop_api_schema(spec, api_name)
                usd.namespace.prune_empty_overrides(layer, str(spec_path))
        for layer in edited.values():
            layer.Save()

    materials.layer.remove_unused(asset_dir)
    return bool(edited)


def refuse_shared_modification(
    stage: Usd.Stage, asset_dir: Path, params: dict, *, op_label: str,
) -> None:
    """Refuse a material write to an asset folder two or more placements share, unless confirmed."""
    authoring.placement.refuse_shared_modification(
        stage, asset_dir,
        confirmed=bool(params.get("confirm_shared_modification", False)),
        op_label=op_label,
        per_instance=(
            "For per-instance materials (different material per "
            "instance), use place_asset to make each instance independent, "
            "then bind a material on each."
        ),
        shared="this material",
    )


def find_first_material(file_path: Path) -> str | None:
    """Return the prim path of the first Material in *file_path*, or ``None``."""
    stage = Usd.Stage.Open(str(file_path))
    if stage is None:
        return None
    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Material):
            return str(prim.GetPath())
    return None
