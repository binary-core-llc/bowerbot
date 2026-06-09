# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Material tools — create / bind / list / remove / cleanup materials."""

from __future__ import annotations

from typing import Any

from bowerbot.services import material_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage


def create_material(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Author a procedural MaterialX material and bind it to a prim."""
    if (err := require_stage(state)):
        return err
    try:
        data = material_service.create_material(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def bind_material(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Copy a material from a file into the asset and bind it to a prim."""
    if (err := require_stage(state)):
        return err
    try:
        data = material_service.bind_material(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def remove_material(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove a material binding from a prim inside an ASWF asset."""
    if (err := require_stage(state)):
        return err
    try:
        data = material_service.remove_material(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def list_materials(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List every material across the project's asset folders."""
    if (err := require_stage(state)):
        return err
    try:
        data = material_service.list_materials(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def cleanup_unused_materials(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Delete material definitions no prim binds to."""
    if (err := require_stage(state)):
        return err
    try:
        data = material_service.cleanup_unused_materials(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


TOOLS: list[Tool] = [
    Tool(
        name="create_material",
        description=(
            "Create a procedural hybrid material and bind it to a prim. "
            "Use this when no existing material file matches what the user "
            "wants. Authors BOTH a MaterialX ND_standard_surface_surfaceshader "
            "(standard_surface prim) and a UsdPreviewSurface (preview_surface "
            "prim) off the same Material with shared base color, metalness, "
            "roughness, and opacity — no textures needed. Returns the bound "
            "prim_path, the material's asset-local prim path (field "
            "'material'), and asset_folder. To tweak a value afterward, target "
            "the COMPOSED scene shader path "
            "'/Scene/<Group>/<Asset>/asset/mtl/<name>/standard_surface' (and "
            "'/preview_surface') with set_prim_attribute, not the returned "
            "'material' value."
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
                "confirm_shared_modification": {
                    "type": "boolean",
                    "description": (
                        "Must be true to author a material into an asset "
                        "folder that is referenced by 2+ scene instances. "
                        "The material lives in the shared mtl.usda and "
                        "applies to every instance. Default false: refuse "
                        "with an error so the LLM can choose between "
                        "place_asset (per-instance independent material) "
                        "or this flag (deliberate shared material)."
                    ),
                    "default": False,
                },
            },
            "required": ["prim_path", "material_name"],
        },
    ),
    Tool(
        name="bind_material",
        description=(
            "Bind a material to a prim. Copies the material into the asset's "
            "mtl.usda (referenced by the asset root) and binds it to the "
            "target prim. Use this for individual material assignments. "
            "Returns the bound material's composed prim path (field "
            "'material', asset-local /<defaultPrim>/mtl/<name>) and "
            "asset_folder."
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
                "confirm_shared_modification": {
                    "type": "boolean",
                    "description": (
                        "Must be true to bind a material into an asset "
                        "folder that is referenced by 2+ scene instances. "
                        "The binding lives in the shared mtl.usda and "
                        "applies to every instance. Default false: refuse "
                        "with an error so the LLM can choose between "
                        "place_asset (per-instance independent binding) "
                        "or this flag (deliberate shared binding)."
                    ),
                    "default": False,
                },
            },
            "required": ["prim_path", "material_file"],
        },
    ),
    Tool(
        name="list_materials",
        description=(
            "List all materials across the project's ASWF asset folders and "
            "which prims each is bound to. Use this to show current material "
            "assignments. Returns material_count and, per material, "
            "material_path (the composed prim path under the asset), "
            "material_name, asset_folder, and bound_prims."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    Tool(
        name="remove_material",
        description=(
            "Remove a material binding from a prim inside an ASWF asset. "
            "Clears the binding in the asset's mtl.usda and garbage-collects "
            "any now-unused material definitions (dropping the mtl.usda layer "
            "if it becomes empty). Use list_prim_children first to find the "
            "exact mesh prim path."
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
    Tool(
        name="cleanup_unused_materials",
        description=(
            "Delete material definitions from an asset's mtl.usda that no "
            "prim binds to. Use this when the user asks to clean up, prune, "
            "or remove unused / orphaned / leftover materials. If "
            "asset_prim_path is provided, cleans only that asset's folder; "
            "if omitted, sweeps every ASWF asset folder in the project. "
            "Returns the list of removed material names."
        ),
        parameters={
            "type": "object",
            "properties": {
                "asset_prim_path": {
                    "type": "string",
                    "description": (
                        "Optional: prim path of an asset in the scene "
                        "(e.g. '/Scene/Architecture/Building_01'). If "
                        "omitted, every ASWF asset folder in the project "
                        "is cleaned."
                    ),
                },
            },
        },
    ),
]


HANDLERS = {
    "create_material": create_material,
    "bind_material": bind_material,
    "list_materials": list_materials,
    "remove_material": remove_material,
    "cleanup_unused_materials": cleanup_unused_materials,
}
