# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Authoring a procedural material: MaterialX ``standard_surface`` plus UsdPreviewSurface."""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Gf
from pxr import Sdf
from pxr import Usd
from pxr import UsdShade

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring

logger = logging.getLogger(__name__)


def create(
    asset_dir: Path,
    prim_path: str,
    params: schemas.ProceduralMaterialParams,
) -> str:
    """Author a MaterialX ``standard_surface`` material and bind it."""
    mtl_path = asset_dir / constants.ASWFLayerNames.MTL
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)

    mtl_layer = (
        Sdf.Layer.FindOrOpen(str(mtl_path))
        if mtl_path.exists()
        else Sdf.Layer.CreateNew(str(mtl_path))
    )

    authoring.asset_folder.ensure_layer_scope(mtl_layer, default_prim_name, "mtl", "Scope")
    mtl_layer.defaultPrim = default_prim_name
    mtl_layer.Save()

    stage = Usd.Stage.Open(str(mtl_path))
    if stage is None:
        msg = f"Cannot open mtl layer: {mtl_path}"
        raise RuntimeError(msg)

    mat_prim_path = f"/{default_prim_name}/mtl/{params.material_name}"
    material = UsdShade.Material.Define(stage, mat_prim_path)

    _author_materialx_standard_surface(stage, mat_prim_path, material, params)
    _author_usd_preview_surface(stage, mat_prim_path, material, params)

    local_prim_path = authoring.asset_folder.to_layer_local_path(prim_path, default_prim_name)
    target_prim = stage.OverridePrim(local_prim_path)
    UsdShade.MaterialBindingAPI.Apply(target_prim).Bind(material)

    stage.Save()
    authoring.asset_folder.ensure_root_reference(asset_dir, constants.ASWFLayerNames.MTL)

    logger.info(
        "Created procedural material %s -> %s in %s",
        mat_prim_path, prim_path, asset_dir.name,
    )
    return mat_prim_path


# ── Helpers ──


def _author_materialx_standard_surface(
    stage: Usd.Stage,
    mat_prim_path: str,
    material: UsdShade.Material,
    params: schemas.ProceduralMaterialParams,
) -> None:
    """Author the MaterialX ``standard_surface`` branch on *material*."""
    shader_path = f"{mat_prim_path}/{constants.MaterialXShaders.STANDARD_SURFACE_PRIM}"
    shader = UsdShade.Shader.Define(stage, shader_path)
    shader.CreateIdAttr(constants.MaterialXShaders.STANDARD_SURFACE)
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

    out = shader.CreateOutput("out", Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput(
        constants.MaterialXShaders.OUTPUT_QUALIFIER,
    ).ConnectToSource(out)


def _author_usd_preview_surface(
    stage: Usd.Stage,
    mat_prim_path: str,
    material: UsdShade.Material,
    params: schemas.ProceduralMaterialParams,
) -> None:
    """Author the UsdPreviewSurface branch on *material* for cross-DCC compat."""
    shader_path = f"{mat_prim_path}/{constants.PreviewSurfaceShader.SURFACE_PRIM}"
    shader = UsdShade.Shader.Define(stage, shader_path)
    shader.CreateIdAttr(constants.PreviewSurfaceShader.SURFACE_ID)
    shader.CreateInput(
        "diffuseColor", Sdf.ValueTypeNames.Color3f,
    ).Set(Gf.Vec3f(*params.base_color))
    shader.CreateInput(
        "metallic", Sdf.ValueTypeNames.Float,
    ).Set(params.metalness)
    shader.CreateInput(
        "roughness", Sdf.ValueTypeNames.Float,
    ).Set(params.roughness)
    if params.opacity < 1.0:
        shader.CreateInput(
            "opacity", Sdf.ValueTypeNames.Float,
        ).Set(params.opacity)

    out = shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(out)
