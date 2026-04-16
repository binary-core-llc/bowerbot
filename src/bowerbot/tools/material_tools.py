# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Material tools — create, bind, list, and remove materials."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from bowerbot.schemas import ASWFLayerNames, ProceduralMaterialParams
from bowerbot.services import material_service, stage_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage, resolve_assets_dir
from bowerbot.utils.usd_utils import resolve_asset_dir_for_prim

logger = logging.getLogger(__name__)


def create_material(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Create a procedural MaterialX material and bind it to a prim."""
    if (err := require_stage(state)):
        return err

    prim_path = params["prim_path"]
    material_name = params["material_name"]

    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(
        state.stage, prim_path,
    )
    if asset_dir is None or ref_prim_path is None:
        return ToolResult(
            success=False,
            error=(
                f"Cannot find ASWF asset folder for {prim_path}. "
                "Procedural materials only work on assets placed as ASWF "
                "folders (not USDZ)."
            ),
        )

    asset_local_path = _to_asset_local(prim_path, ref_prim_path)

    material_params = ProceduralMaterialParams(
        material_name=material_name,
        base_color=(
            float(params.get("base_color_r", 0.8)),
            float(params.get("base_color_g", 0.8)),
            float(params.get("base_color_b", 0.8)),
        ),
        metalness=float(params.get("metalness", 0.0)),
        roughness=float(params.get("roughness", 0.5)),
        opacity=float(params.get("opacity", 1.0)),
    )

    try:
        material_prim_path = material_service.create_procedural_material(
            asset_dir=asset_dir,
            prim_path=asset_local_path,
            params=material_params,
        )
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))

    state.stage = stage_service.open_stage(state.stage_path)
    logger.info(
        "Created procedural material %s on %s in %s/",
        material_prim_path, prim_path, asset_dir.name,
    )
    return ToolResult(
        success=True,
        data={
            "prim_path": prim_path,
            "material": material_prim_path,
            "asset_folder": asset_dir.name,
            "message": (
                f"Created procedural material '{material_name}' and "
                f"bound to {prim_path} in {asset_dir.name}/{ASWFLayerNames.MTL}"
            ),
        },
    )


def bind_material(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Copy a material from a file into the asset and bind it to a prim."""
    if (err := require_stage(state)):
        return err

    prim_path = params["prim_path"]
    material_file = Path(params["material_file"])
    material_prim_path = params.get("material_prim_path")

    if not material_file.exists():
        return ToolResult(
            success=False, error=f"Material file not found: {material_file}",
        )

    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(
        state.stage, prim_path,
    )
    if asset_dir is None or ref_prim_path is None:
        return ToolResult(
            success=False,
            error=(
                f"Cannot find ASWF asset folder for {prim_path}. "
                "Material binding only works on assets placed as ASWF "
                "folders (not USDZ)."
            ),
        )

    asset_local_path = _to_asset_local(prim_path, ref_prim_path)

    try:
        material_prim_path = material_service.add_material(
            asset_dir=asset_dir,
            material_file=material_file,
            prim_path=asset_local_path,
            material_prim_path=material_prim_path,
        )
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))

    state.stage = stage_service.open_stage(state.stage_path)
    logger.info(
        "Bound %s to %s in %s/",
        material_prim_path, prim_path, asset_dir.name,
    )
    return ToolResult(
        success=True,
        data={
            "prim_path": prim_path,
            "material": material_prim_path,
            "asset_folder": asset_dir.name,
            "message": (
                f"Bound {material_prim_path} to {prim_path} in "
                f"{asset_dir.name}/{ASWFLayerNames.MTL}"
            ),
        },
    )


def remove_material(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove the material binding on a prim inside an ASWF asset."""
    if (err := require_stage(state)):
        return err

    prim_path = params["prim_path"]
    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(
        state.stage, prim_path,
    )
    if asset_dir is None or ref_prim_path is None:
        return ToolResult(
            success=False,
            error=f"Cannot find ASWF asset folder for {prim_path}.",
        )

    asset_local_path = _to_asset_local(prim_path, ref_prim_path)
    material_service.remove_material_binding(asset_dir, asset_local_path)
    state.stage = stage_service.open_stage(state.stage_path)

    logger.info("Removed material from %s", prim_path)
    return ToolResult(
        success=True,
        data={
            "prim_path": prim_path,
            "asset_folder": asset_dir.name,
            "message": f"Removed material binding from {prim_path}",
        },
    )


def list_materials(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List every material across the project's asset folders."""
    del params
    if (err := require_stage(state)):
        return err

    assets_dir = resolve_assets_dir(state)
    all_materials: list[dict] = []

    for entry in assets_dir.iterdir():
        if not entry.is_dir():
            continue
        if not (entry / ASWFLayerNames.MTL).exists():
            continue
        materials = material_service.list_materials(entry)
        for mat in materials:
            mat["asset_folder"] = entry.name
        all_materials.extend(materials)

    return ToolResult(
        success=True,
        data={
            "material_count": len(all_materials),
            "materials": all_materials,
            "message": f"Scene has {len(all_materials)} material(s).",
        },
    )


def _to_asset_local(prim_path: str, ref_prim_path: str) -> str:
    """Strip the scene-side reference prefix to get an asset-local path."""
    if prim_path.startswith(ref_prim_path):
        remainder = prim_path[len(ref_prim_path):]
        return remainder if remainder else "/"
    return prim_path


TOOLS: list[Tool] = [
    Tool(
        name="create_material",
        description=(
            "Create a procedural MaterialX material and bind it to a prim. "
            "Use this when no existing material file matches what the user "
            "wants. Creates a ND_standard_surface_surfaceshader with base "
            "color, metalness, and roughness — no textures needed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Prim path of the geometry to apply the material "
                        "to. Use list_prim_children to find the exact "
                        "mesh part."
                    ),
                },
                "material_name": {
                    "type": "string",
                    "description": (
                        "Name for the material "
                        "(e.g. 'matte_black', 'brushed_steel')."
                    ),
                },
                "base_color_r": {
                    "type": "number",
                    "description": "Red channel (0.0–1.0).",
                    "default": 0.8,
                },
                "base_color_g": {
                    "type": "number",
                    "description": "Green channel (0.0–1.0).",
                    "default": 0.8,
                },
                "base_color_b": {
                    "type": "number",
                    "description": "Blue channel (0.0–1.0).",
                    "default": 0.8,
                },
                "metalness": {
                    "type": "number",
                    "description": (
                        "0.0 = dielectric (plastic, wood), "
                        "1.0 = metal (steel, gold)."
                    ),
                    "default": 0.0,
                },
                "roughness": {
                    "type": "number",
                    "description": (
                        "0.0 = mirror/glossy, 1.0 = fully rough/matte."
                    ),
                    "default": 0.5,
                },
                "opacity": {
                    "type": "number",
                    "description": (
                        "1.0 = opaque, 0.0 = transparent. Only set below "
                        "1.0 for glass or translucent materials."
                    ),
                    "default": 1.0,
                },
            },
            "required": ["prim_path", "material_name"],
        },
    ),
    Tool(
        name="bind_material",
        description=(
            "Bind a material to a prim. Copies the material file to project "
            "assets, adds it as a sublayer, and binds it to the target prim. "
            "Use this for individual material assignments."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Prim path of the geometry to apply the material "
                        "to (e.g. '/Scene/Furniture/Table_01')."
                    ),
                },
                "material_file": {
                    "type": "string",
                    "description": "Local file path to the material .usda file.",
                },
                "material_prim_path": {
                    "type": "string",
                    "description": (
                        "USD prim path of the material inside the file "
                        "(e.g. '/mtl/wood_varnished'). If omitted, the "
                        "first Material prim found is used."
                    ),
                },
            },
            "required": ["prim_path", "material_file"],
        },
    ),
    Tool(
        name="list_materials",
        description=(
            "List all materials in the scene and which prims they are "
            "bound to. Use this to show current material assignments."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    Tool(
        name="remove_material",
        description=(
            "Remove material binding from a prim. Clears the material "
            "assignment and removes any unused material sublayers from the "
            "scene. Use list_prim_children first to find the exact mesh "
            "prim path."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Prim path to remove the material from "
                        "(e.g. '.../single_table/table/table'). Use "
                        "list_prim_children to find the exact path."
                    ),
                },
            },
            "required": ["prim_path"],
        },
    ),
]


HANDLERS = {
    "create_material": create_material,
    "bind_material": bind_material,
    "list_materials": list_materials,
    "remove_material": remove_material,
}
