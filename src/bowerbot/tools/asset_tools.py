# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset tools — place referenced assets and manage the project assets/ dir."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import MAX_LAYOUT_PLACEMENTS, LayoutPattern, PositionMode
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


def place_layout(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Place many assets in one batch from enumerated or parametric layout entries."""
    if (err := require_stage(state)):
        return err
    try:
        data = asset_service.place_layout(state, params)
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


def cleanup_unused_contents(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Drop empty contents.usda layers from asset folders, per asset or project-wide."""
    if (err := require_project(state)):
        return err
    try:
        data = asset_service.cleanup_unused_contents(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def freeze_asset(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Bake an existing project asset's root transforms into vertex data."""
    if (err := require_project(state)):
        return err
    try:
        data = asset_service.freeze_asset(state, params)
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
            "Use the standard hierarchy: Architecture, Furniture, Products, "
            "Lighting, Props. Returns the prim_path, position, and an intake "
            "summary (asset_folder, whether the root was renamed to the ASWF "
            "canonical name, files_copied, localized dependencies, compliance "
            "warnings)."
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
                "fix_root_transforms": {
                    "type": "boolean",
                    "description": (
                        "If true, bake non-identity root transforms "
                        "(translate/rotate/scale/pivot from an unfrozen "
                        "DCC export) into vertex data on intake. Only use "
                        "when the user confirms they want the fix; "
                        "otherwise re-export with transforms frozen."
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
        name="place_layout",
        description=(
            "Place MANY assets into the scene in a single call, the batch form "
            "of place_asset. Provide EXACTLY ONE of 'placements' (inline "
            "entries) or 'layout_file' (path to a JSON file with the same "
            "entries: {\"version\": 1, \"placements\": [...]}; absolute or "
            "project-relative). Use inline for small or parametric layouts; "
            "use layout_file beyond a few dozen entries (e.g. a layout "
            "extracted from an existing scene by a script or exported from a "
            "DCC). Each entry references one asset and positions it many "
            "times, via an enumerated 'transforms' list or a parametric "
            "'pattern' (grid or linear). Entry asset paths resolve in order: "
            "absolute, layout-file dir, project dir, library dir; they must "
            "name the asset's root FILE. Authoring matches place_asset "
            "(grouped /asset reference wrappers, conformed to the scene "
            "up-axis and units) in one stage write; the whole plan is "
            "validated first and ALL problems are reported at once, nothing "
            "is placed unless every entry is valid. Pass validate_only=true "
            "to lint a layout (especially a layout_file) without placing "
            "anything. Put a logical 'group' on each entry (e.g. 'Boxes', "
            "'Building/Racks') so the set can be inspected or removed as a "
            "unit. Returns the total placed, the groups written, a per-asset "
            "count, and the resolved source per asset; use list_scene or "
            "list_prim_children on a group to read individual prim paths."
        ),
        parameters={
            "type": "object",
            "properties": {
                "placements": {
                    "type": "array",
                    "description": (
                        "Each entry places one asset at many transforms; at "
                        f"most {MAX_LAYOUT_PLACEMENTS} placements per call."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "asset": {
                                "type": "string",
                                "description": (
                                    "Path to the asset's root FILE, absolute "
                                    "or relative to the layout-file/project/"
                                    "library dirs (e.g. "
                                    "'SM_floor02/SM_floor02.usda')."
                                ),
                            },
                            "group": {
                                "type": "string",
                                "description": (
                                    "Scene group to place into, e.g. 'Boxes' or "
                                    "'Building/Racks'. Nested groups use '/'. Becomes "
                                    "a /Scene/<group> scope."
                                ),
                            },
                            "name": {
                                "type": "string",
                                "description": (
                                    "Optional base name for the placed prims "
                                    "(default: the asset file name)."
                                ),
                            },
                            "fix_root_prim": {
                                "type": "boolean",
                                "description": (
                                    "Wrap a non-Xform root under an Xform on "
                                    "intake (ASWF compliance fix). Only with "
                                    "user confirmation."
                                ),
                                "default": False,
                            },
                            "fix_root_transforms": {
                                "type": "boolean",
                                "description": (
                                    "Bake non-identity root transforms into "
                                    "vertex data on intake. Only with user "
                                    "confirmation."
                                ),
                                "default": False,
                            },
                            "rotate": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": (
                                    "Optional [rx, ry, rz] degrees default for "
                                    "placements that do not set their own."
                                ),
                            },
                            "scale": {
                                "description": (
                                    "Optional scale default for placements that "
                                    "do not set their own: a uniform number or "
                                    "[sx, sy, sz]."
                                ),
                            },
                            "transforms": {
                                "type": "array",
                                "description": (
                                    "Enumerated placements; use this OR 'pattern'. "
                                    "Each item is { translate: [x, y, z] in scene "
                                    "units, rotate?: [rx, ry, rz], scale?: number "
                                    "or [sx, sy, sz] }."
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "translate": {
                                            "type": "array",
                                            "items": {"type": "number"},
                                        },
                                        "rotate": {
                                            "type": "array",
                                            "items": {"type": "number"},
                                        },
                                        "scale": {},
                                    },
                                    "required": ["translate"],
                                },
                            },
                            "pattern": {
                                "type": "object",
                                "description": (
                                    "Parametric placements; use this OR 'transforms'."
                                ),
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": [p.value for p in LayoutPattern],
                                        "description": (
                                            "'grid' repeats along X/Y(/Z); 'linear' "
                                            "repeats along one direction step."
                                        ),
                                    },
                                    "origin": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "description": (
                                            "[x, y, z] of the first placement, in "
                                            "scene units."
                                        ),
                                    },
                                    "count": {
                                        "description": (
                                            "grid: [nx, ny] or [nx, ny, nz]. "
                                            "linear: a single integer n."
                                        ),
                                    },
                                    "spacing": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "description": (
                                            "Step in scene units between placements. "
                                            "grid: [sx, sy] or [sx, sy, sz] (a 3-axis "
                                            "count needs a 3-axis spacing). linear: "
                                            "[sx, sy, sz] direction step."
                                        ),
                                    },
                                },
                                "required": ["type", "origin", "count", "spacing"],
                            },
                        },
                        "required": ["asset", "group"],
                    },
                },
                "layout_file": {
                    "type": "string",
                    "description": (
                        "Path to a layout JSON file: {\"version\": 1, "
                        "\"placements\": [...]} with the same entries as the "
                        "inline form. Absolute or project-relative. Use "
                        "INSTEAD of 'placements' for bulk layouts."
                    ),
                },
                "validate_only": {
                    "type": "boolean",
                    "description": (
                        "If true, lint the layout without placing anything: "
                        "reports every shape and asset-resolution problem, or "
                        "the would-be placement summary. Intake-time issues "
                        "(e.g. ASWF compliance) only surface on the real run."
                    ),
                    "default": False,
                },
            },
        },
    ),
    Tool(
        name="place_asset_inside",
        description=(
            "Place a 3D asset NESTED INSIDE another asset (the container). "
            "The asset becomes part of the container's asset folder; if the "
            "container is referenced by multiple scene instances, ALL of them "
            "will see the nested asset. Use this for permanent fixtures every "
            "instance should share (e.g. a built-in counter inside a building). "
            "For independent, per-instance items (e.g. one pillow on each of "
            "four sofa instances), use place_asset instead. If the container "
            "is shared by 2+ scene instances, this tool will refuse the call "
            "with a clear error unless confirm_shared_modification=true is "
            "passed. Translate values are in the container's coordinate space; "
            "use position_mode='absolute' with coordinates from list_prim_children "
            "bounds, or 'bounds_offset' where X/Z are offsets from the container's "
            "bounding-box CENTER and Y is an offset from its TOP surface (or BOTTOM "
            "for negative Y; default 0.5 m above the top if Y is omitted). Returns "
            "the composed prim_path, the resolved container-local position, and an "
            "intake summary (asset_folder, renamed root, files_copied, localized "
            "dependencies, compliance warnings)."
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
                        "= X and Z are offsets from the container's bounding-box "
                        "CENTER, Y is an offset from the TOP surface (or BOTTOM "
                        "for negative Y); if translate_y is omitted the asset is "
                        "placed 0.5 m above the top surface."
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
                "fix_root_transforms": {
                    "type": "boolean",
                    "description": (
                        "If true, bake non-identity root transforms into "
                        "vertex data on intake (Maya/Houdini freeze)."
                    ),
                    "default": False,
                },
                "confirm_shared_modification": {
                    "type": "boolean",
                    "description": (
                        "Must be true to place into a container whose asset "
                        "folder is referenced by 2+ scene instances. The "
                        "placement modifies the shared asset and propagates "
                        "to every instance. Default false: refuse with an "
                        "error so the LLM can choose between place_asset "
                        "(per-instance) or this flag (deliberate shared)."
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
    Tool(
        name="freeze_asset",
        description=(
            "Bake project assets' root transforms (translate/rotate/scale/"
            "pivot) into vertex data, leaving the root prim with identity "
            "transforms. Use this to clean up assets imported from DCC "
            "exports without 'Bake Transforms' enabled — required for "
            "nested placement to work correctly. If 'name' is provided, "
            "freezes that one asset; if omitted, freezes every asset in "
            "the project's assets/ directory."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Optional: name of a single asset folder to "
                        "freeze (e.g. 'single_sofa'). If omitted, every "
                        "asset folder in the project is frozen."
                    ),
                },
            },
        },
    ),
    Tool(
        name="cleanup_unused_contents",
        description=(
            "Drop empty contents.usda layers from asset folders. Use this "
            "when the user asks to clean up, prune, or remove leftover / "
            "orphaned / empty nested-asset scaffolding (e.g. an empty "
            "Props scope left after removing all nested pillows). If "
            "asset_prim_path is provided, cleans only that asset's folder; "
            "if omitted, sweeps every ASWF asset folder in the project. "
            "Returns the list of removed group-scope names per folder."
        ),
        parameters={
            "type": "object",
            "properties": {
                "asset_prim_path": {
                    "type": "string",
                    "description": (
                        "Optional: prim path of an asset in the scene "
                        "(e.g. '/Scene/Furniture/Single_Sofa_01_41'). If "
                        "omitted, every ASWF asset folder in the project "
                        "is cleaned."
                    ),
                },
            },
        },
    ),
]


HANDLERS = {
    "place_asset": place_asset,
    "place_asset_inside": place_asset_inside,
    "place_layout": place_layout,
    "list_project_assets": list_project_assets,
    "delete_project_asset": delete_project_asset,
    "delete_project_texture": delete_project_texture,
    "cleanup_unused_contents": cleanup_unused_contents,
    "freeze_asset": freeze_asset,
}
