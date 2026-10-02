# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""What an asset's ``mtl.usda`` holds: listing its materials, removing unused ones."""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Sdf
from pxr import Usd
from pxr import UsdShade

from bowerbot import constants
from bowerbot.utils import authoring
from bowerbot.utils import usd

logger = logging.getLogger(__name__)


def list_with_bindings(asset_dir: Path) -> list[dict]:
    """List the materials that give *asset_dir* its look, and the prims each is bound to.

    A material with no shader output describes no look and is left out.
    """
    mtl_path = asset_dir / constants.ASWFLayerNames.MTL
    if not mtl_path.exists():
        return []

    root_file = authoring.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        return []

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return []

    materials: dict[str, list[str]] = {}
    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Material) and UsdShade.Material(prim).GetOutputs():
            materials[str(prim.GetPath())] = []

    for prim in stage.Traverse():
        bound_mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        if bound_mat:
            mat_path = str(bound_mat.GetPath())
            if mat_path in materials:
                materials[mat_path].append(str(prim.GetPath()))

    return [
        {
            "material_path": mat_path,
            "material_name": Sdf.Path(mat_path).name,
            "bound_prims": bound_prims,
        }
        for mat_path, bound_prims in materials.items()
    ]


def remove_unused(asset_dir: Path) -> list[str]:
    """Delete material definitions in *asset_dir*'s ``mtl.usda`` with no bindings.

    Bindings are resolved through the composed root stage so opinions
    authored on ``over`` prims count. When ``mtl.usda`` becomes empty,
    it is removed and the root references are rebuilt.
    """
    mtl_path = asset_dir / constants.ASWFLayerNames.MTL
    if not mtl_path.exists():
        return []

    root_file = authoring.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        return []

    root_stage = Usd.Stage.Open(str(root_file))
    if root_stage is None:
        return []

    bound_materials: set[str] = set()
    for prim in root_stage.Traverse():
        bound_mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        if bound_mat:
            bound_materials.add(str(bound_mat.GetPath()))
    bound_materials |= _collect_variant_binding_targets(asset_dir)

    mtl_layer = Sdf.Layer.FindOrOpen(str(mtl_path))
    if mtl_layer is None:
        return []

    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    mtl_scope_path = Sdf.Path(f"/{default_prim_name}/mtl")
    mtl_scope = mtl_layer.GetPrimAtPath(mtl_scope_path)
    removed: list[str] = []
    if mtl_scope:
        to_remove = [
            child.path for child in mtl_scope.nameChildren
            if str(child.path) not in bound_materials
        ]
        variants_path = asset_dir / constants.ASWFLayerNames.VARIANTS
        variants_layer = (
            Sdf.Layer.FindOrOpen(str(variants_path))
            if variants_path.exists() else None
        )
        for path in to_remove:
            removed.append(path.name)
            edit = Sdf.BatchNamespaceEdit()
            edit.Add(path, Sdf.Path.emptyPath)
            mtl_layer.Apply(edit)
            if variants_layer is not None:
                usd.namespace.clear_orphan_variant_overs(variants_layer, str(path))
                variants_layer.Save()

    mtl_layer.Save()
    if removed and variants_layer is not None:
        authoring.asset_variants.cleanup_if_empty(asset_dir)

    authoring.asset_folder.remove_empty_layer(
        mtl_path, asset_dir, lambda p: p.IsA(UsdShade.Material),
    )

    if removed:
        logger.info(
            "Cleaned %d unused material(s) from %s",
            len(removed), asset_dir.name,
        )
    return sorted(removed)


# ── Helpers ──


def _collect_variant_binding_targets(asset_dir: Path) -> set[str]:
    """Every ``material:binding`` target authored under any variant."""
    variants_path = asset_dir / constants.ASWFLayerNames.VARIANTS
    if not variants_path.exists():
        return set()
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return set()

    targets: set[str] = set()

    def visit(path: Sdf.Path) -> None:
        prim_spec = layer.GetPrimAtPath(path)
        if prim_spec is None:
            return
        rel = prim_spec.relationships.get("material:binding")
        if rel is None:
            return
        targets.update(
            str(t) for t in rel.targetPathList.GetAddedOrExplicitItems()
        )

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return targets
