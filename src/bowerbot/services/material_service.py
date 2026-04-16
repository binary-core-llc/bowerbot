# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Material service — manage materials inside ASWF asset folders.

* **add_material** — copy an external material into ``mtl.usda`` and
  bind it to a prim.
* **create_procedural_material** — write a MaterialX
  ``standard_surface`` directly into ``mtl.usda`` (no textures) and
  bind it.
* **remove_material_binding** — clear a binding and garbage-collect
  unused definitions + the layer when empty.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdShade

from bowerbot.schemas import (
    ASWFLayerNames,
    MaterialXShaders,
    ProceduralMaterialParams,
)
from bowerbot.services.asset_service import (
    ensure_layer_scope,
    ensure_root_reference,
    find_root_file,
    remove_empty_layer,
    resolve_default_prim_name,
    to_layer_local_path,
)

logger = logging.getLogger(__name__)


def add_material(
    asset_dir: Path,
    material_file: Path,
    prim_path: str,
    material_prim_path: str | None = None,
) -> str:
    """Copy a material into ``mtl.usda`` and bind it to *prim_path*.

    Creates ``mtl.usda`` if it doesn't exist and updates the root
    file to reference it.
    """
    mtl_path = asset_dir / ASWFLayerNames.MTL

    if not material_prim_path:
        material_prim_path = _find_first_material(material_file)
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

    default_prim_name = resolve_default_prim_name(asset_dir)
    ensure_layer_scope(mtl_layer, default_prim_name, "mtl", "Scope")

    mat_name = Sdf.Path(material_prim_path).name
    dest_mat_path = Sdf.Path(f"/{default_prim_name}/mtl/{mat_name}")
    Sdf.CopySpec(
        source_layer, Sdf.Path(material_prim_path),
        mtl_layer, dest_mat_path,
    )

    mtl_layer.defaultPrim = default_prim_name
    mtl_layer.Save()

    local_prim_path = to_layer_local_path(prim_path, default_prim_name)
    composed_mat_path = f"/{default_prim_name}/mtl/{mat_name}"

    stage = Usd.Stage.Open(str(mtl_path))
    if stage is not None:
        prim = stage.OverridePrim(local_prim_path)
        mat_prim = stage.GetPrimAtPath(composed_mat_path)
        if mat_prim.IsValid():
            material = UsdShade.Material(mat_prim)
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
        stage.Save()

    ensure_root_reference(asset_dir, ASWFLayerNames.MTL)

    logger.info(
        "Added material %s -> %s in %s",
        composed_mat_path, prim_path, asset_dir.name,
    )
    return composed_mat_path


def create_procedural_material(
    asset_dir: Path,
    prim_path: str,
    params: ProceduralMaterialParams,
) -> str:
    """Create and bind a MaterialX ``standard_surface`` material.

    Writes a parameter-only material (no textures) into the asset's
    ``mtl.usda`` and binds it to *prim_path*.
    """
    mtl_path = asset_dir / ASWFLayerNames.MTL
    default_prim_name = resolve_default_prim_name(asset_dir)

    mtl_layer = (
        Sdf.Layer.FindOrOpen(str(mtl_path))
        if mtl_path.exists()
        else Sdf.Layer.CreateNew(str(mtl_path))
    )

    ensure_layer_scope(mtl_layer, default_prim_name, "mtl", "Scope")
    mtl_layer.defaultPrim = default_prim_name
    mtl_layer.Save()

    stage = Usd.Stage.Open(str(mtl_path))
    if stage is None:
        msg = f"Cannot open mtl layer: {mtl_path}"
        raise RuntimeError(msg)

    mat_prim_path = f"/{default_prim_name}/mtl/{params.material_name}"
    shader_prim_path = (
        f"{mat_prim_path}/{MaterialXShaders.STANDARD_SURFACE_PRIM}"
    )

    material = UsdShade.Material.Define(stage, mat_prim_path)
    shader = UsdShade.Shader.Define(stage, shader_prim_path)

    shader.CreateIdAttr(MaterialXShaders.STANDARD_SURFACE)
    shader.CreateInput(
        "base_color", Sdf.ValueTypeNames.Color3f,
    ).Set(Gf.Vec3f(*params.base_color))
    shader.CreateInput(
        "metalness", Sdf.ValueTypeNames.Float,
    ).Set(params.metalness)
    shader.CreateInput(
        "specular_roughness", Sdf.ValueTypeNames.Float,
    ).Set(params.roughness)

    if params.opacity < 1.0:
        shader.CreateInput(
            "opacity", Sdf.ValueTypeNames.Float,
        ).Set(params.opacity)

    surface_output = shader.CreateOutput(
        "out", Sdf.ValueTypeNames.Token,
    )
    material.CreateSurfaceOutput(
        MaterialXShaders.OUTPUT_QUALIFIER,
    ).ConnectToSource(surface_output)

    local_prim_path = to_layer_local_path(prim_path, default_prim_name)
    target_prim = stage.OverridePrim(local_prim_path)
    UsdShade.MaterialBindingAPI.Apply(target_prim).Bind(material)

    stage.Save()
    ensure_root_reference(asset_dir, ASWFLayerNames.MTL)

    logger.info(
        "Created procedural material %s -> %s in %s",
        mat_prim_path, prim_path, asset_dir.name,
    )
    return mat_prim_path


def remove_material_binding(asset_dir: Path, prim_path: str) -> None:
    """Remove a material binding from an asset folder's ``mtl.usda``.

    If no bindings remain, deletes the layer and rebuilds the root.
    """
    mtl_path = asset_dir / ASWFLayerNames.MTL
    if not mtl_path.exists():
        return

    default_prim_name = resolve_default_prim_name(asset_dir)
    local_path = to_layer_local_path(prim_path, default_prim_name)

    stage = Usd.Stage.Open(str(mtl_path))
    if stage is None:
        return

    prim = stage.GetPrimAtPath(local_path)
    if prim.IsValid():
        UsdShade.MaterialBindingAPI(prim).UnbindAllBindings()

    stage.Save()
    _cleanup_unused_materials(mtl_path, asset_dir)


def list_materials(asset_dir: Path) -> list[dict]:
    """List all materials and bindings in an asset folder."""
    mtl_path = asset_dir / ASWFLayerNames.MTL
    if not mtl_path.exists():
        return []

    root_file = find_root_file(asset_dir)
    if root_file is None:
        return []

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return []

    materials: dict[str, list[str]] = {}
    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Material):
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


def _find_first_material(file_path: Path) -> str | None:
    """Return the prim path of the first Material in a USD file."""
    stage = Usd.Stage.Open(str(file_path))
    if stage is None:
        return None
    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Material):
            return str(prim.GetPath())
    return None


def _cleanup_unused_materials(mtl_path: Path, asset_dir: Path) -> None:
    """Remove unused material definitions from ``mtl.usda``.

    When the layer becomes empty, deletes the file and rebuilds
    root references.
    """
    default_prim_name = resolve_default_prim_name(asset_dir)

    stage = Usd.Stage.Open(str(mtl_path))
    if stage is None:
        return

    bound_materials: set[str] = set()
    for prim in stage.Traverse():
        bound_mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        if bound_mat:
            bound_materials.add(str(bound_mat.GetPath()))

    mtl_layer = stage.GetRootLayer()
    mtl_scope_path = Sdf.Path(f"/{default_prim_name}/mtl")
    mtl_scope = mtl_layer.GetPrimAtPath(mtl_scope_path)
    if mtl_scope:
        to_remove = [
            child.path for child in mtl_scope.nameChildren
            if str(child.path) not in bound_materials
        ]
        for path in to_remove:
            edit = Sdf.BatchNamespaceEdit()
            edit.Add(path, Sdf.Path.emptyPath)
            mtl_layer.Apply(edit)

    mtl_layer.Save()

    remove_empty_layer(
        mtl_path, asset_dir, lambda p: p.IsA(UsdShade.Material),
    )
