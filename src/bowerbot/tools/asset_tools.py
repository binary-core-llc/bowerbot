# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset tools — place referenced assets and manage the project assets/ dir."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import PositionMode
from bowerbot.services import asset_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_project, require_stage


def place_asset(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Add an asset reference to the scene at the given group/position."""
    if (err := require_stage(state)):
        return err
    try:
        data = asset_service.place_asset(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def place_asset_inside(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Nest an asset inside an ASWF container's ``contents.usda``."""
    if (err := require_stage(state)):
        return err
    try:
        data = asset_service.place_asset_inside(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def list_project_assets(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List every asset in the project directory, with in-scene flags."""
    if (err := require_project(state)):
        return err
    try:
        data = asset_service.list_project_assets(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def delete_project_asset(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Delete an asset folder/file from the project, if unreferenced."""
    if (err := require_project(state)):
        return err
    try:
        data = asset_service.delete_project_asset(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def delete_project_texture(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Delete a texture from the project's ``textures/`` dir, if unreferenced."""
    if (err := require_project(state)):
        return err
    try:
        data = asset_service.delete_project_texture(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


TOOLS: list[Tool] = [
    Tool(
        name="place_asset",
        description=(
            "Place a 3D asset into the current scene. The asset is added as a "
            "USD reference at the specified prim path with the given transform. "
            "Use the standard hierarchy: Furniture, Products, Lighting, Props."
        ),
        parameters={
            "type": "object",
            "properties": {
                "asset_file_path": {
                    "type": "string",
                    "description": "Local file path to the .usda/.usdc/.usdz asset.",
                },
                "asset_name": {
                    "type": "string",
                    "description": "Human-readable name for this asset instance.",
                },
                "group": {
                    "type": "string",
                    "enum": [
                        "Architecture", "Furniture", "Products", "Lighting", "Props",
                    ],
                    "description": "Which scene group to place the asset in.",
                },
                "translate_x": {
                    "type": "number",
                    "description": "X position in meters. 0 = left edge of room.",
                },
                "translate_y": {
                    "type": "number",
                    "description": (
                        "Y position in meters. 0 = floor, 2.7 = typical ceiling."
                    ),
                },
                "translate_z": {
                    "type": "number",
                    "description": "Z position in meters. 0 = back wall.",
                },
                "rotate_y": {
                    "type": "number",
                    "description": (
                        "Rotation around Y axis in degrees. 0 = facing forward."
                    ),
                    "default": 0.0,
                },
                "fix_root_prim": {
                    "type": "boolean",
                    "description": (
                        "If true, automatically wraps a non-Xform root "
                        "prim under an Xform to comply with ASWF "
                        "guidelines. Only use when the user confirms "
                        "they want the fix."
                    ),
                    "default": False,
                },
            },
            "required": [
                "asset_file_path", "asset_name", "group",
                "translate_x", "translate_y", "translate_z",
            ],
        },
    ),
    Tool(
        name="place_asset_inside",
        description=(
            "Place a 3D asset NESTED INSIDE another asset (the container). "
            "The asset becomes part of the container — if the container is "
            "duplicated or reused, the nested asset comes along. Use this for "
            "permanent fixtures (e.g. a built-in counter inside a building). "
            "For independent, moveable scene items, use place_asset instead. "
            "Translate values are in the container's coordinate space — use "
            "position_mode='absolute' with coordinates from list_prim_children "
            "bounds, or 'bounds_offset' for offsets from the container's surfaces."
        ),
        parameters={
            "type": "object",
            "properties": {
                "asset_file_path": {
                    "type": "string",
                    "description": "Local file path to the .usda/.usdc/.usdz asset.",
                },
                "asset_name": {
                    "type": "string",
                    "description": "Human-readable name for this asset instance.",
                },
                "container_prim_path": {
                    "type": "string",
                    "description": (
                        "Prim path of the ASWF container asset in the scene "
                        "(e.g. '/Scene/Architecture/Building_01'). The nested "
                        "asset will be written into this container's contents.usda."
                    ),
                },
                "group": {
                    "type": "string",
                    "enum": [
                        "Architecture", "Furniture", "Products", "Lighting", "Props",
                    ],
                    "description": "Logical grouping inside the container's contents.",
                },
                "translate_x": {
                    "type": "number",
                    "description": "X position in meters (container-local).",
                },
                "translate_y": {
                    "type": "number",
                    "description": "Y position in meters (container-local).",
                },
                "translate_z": {
                    "type": "number",
                    "description": "Z position in meters (container-local).",
                },
                "rotate_y": {
                    "type": "number",
                    "description": "Rotation around Y axis in degrees.",
                    "default": 0.0,
                },
                "position_mode": {
                    "type": "string",
                    "enum": [m.value for m in PositionMode],
                    "description": (
                        "How to interpret translate values: 'absolute' = "
                        "world-space coordinates (as returned by list_scene / "
                        "list_prim_children) — BowerBot converts to the "
                        "container's internal coordinate frame; 'bounds_offset' "
                        "= offsets from the container's bounding box surfaces."
                    ),
                    "default": PositionMode.ABSOLUTE.value,
                },
                "fix_root_prim": {
                    "type": "boolean",
                    "description": (
                        "If true, auto-wraps non-Xform root prims in the "
                        "asset being placed."
                    ),
                    "default": False,
                },
            },
            "required": [
                "asset_file_path", "asset_name", "container_prim_path", "group",
                "translate_x", "translate_y", "translate_z",
            ],
        },
    ),
    Tool(
        name="list_project_assets",
        description=(
            "List asset folders in the current project's assets directory. "
            "Shows which ones are referenced in the scene and which are "
            "unused. Use this to find asset folders that can be cleaned up. "
            "Optionally filter by name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional keyword to filter by asset name.",
                },
            },
        },
    ),
    Tool(
        name="delete_project_asset",
        description=(
            "Delete an asset from the project's assets directory. Works for "
            "both ASWF asset folders and standalone files (e.g. USDZ). Use "
            "this after removing an asset from the scene when the user "
            "confirms they want to delete the files too. BowerBot scans all "
            "USD files in the project to ensure the asset is not referenced "
            "elsewhere before deleting."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Name of the asset to delete. For ASWF folders, the "
                        "folder name (e.g. 'single_table'). For files, the "
                        "filename (e.g. 'cafe_table.usdz')."
                    ),
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="delete_project_texture",
        description=(
            "Delete a texture file from the project's textures/ directory. "
            "Scans all USD files in the project to ensure the texture is "
            "not referenced elsewhere before deleting."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": (
                        "Name of the texture file to delete (e.g. 'studio.exr')."
                    ),
                },
            },
            "required": ["file_name"],
        },
    ),
]


HANDLERS = {
    "place_asset": place_asset,
    "place_asset_inside": place_asset_inside,
    "list_project_assets": list_project_assets,
    "delete_project_asset": delete_project_asset,
    "delete_project_texture": delete_project_texture,
}
