# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage tools — create, list, reorganize prims in the active scene."""

from __future__ import annotations

import logging
from typing import Any

from bowerbot.services import stage_service
from bowerbot.services.geometry_service import suggest_grid_layout
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage, resolve_project_dir
from bowerbot.utils.naming import safe_file_name

logger = logging.getLogger(__name__)


def create_stage(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Create (or reopen) the scene stage for the bound project."""
    filename = params["filename"]
    safe_name = safe_file_name(filename) or "scene"
    logger.debug("create_stage filename=%s", safe_name)

    project_dir = resolve_project_dir(state)
    if state.project is None:
        return ToolResult(success=False, error="No project open.")

    state.stage_path = state.project.scene_path
    if state.stage_path.exists():
        state.stage = stage_service.open_stage(state.stage_path)
        state.object_count = len(stage_service.list_prims(state.stage))
        logger.info("Reopened existing stage: %s", state.stage_path)
        return ToolResult(
            success=True,
            data={
                "stage_path": str(state.stage_path),
                "object_count": state.object_count,
                "message": (
                    f"Stage already exists at {state.stage_path} with "
                    f"{state.object_count} object(s). Reopened."
                ),
            },
        )

    state.object_count = 0
    state.stage = stage_service.create_stage(state.stage_path)
    stage_service.save(state.stage)
    state.touch_project()

    logger.info("Created stage: %s (project dir %s)", state.stage_path, project_dir)
    return ToolResult(
        success=True,
        data={
            "stage_path": str(state.stage_path),
            "message": (
                f"Stage created at {state.stage_path} with standard hierarchy."
            ),
        },
    )


def list_scene(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Return every placed object and light in the scene."""
    del params
    if (err := require_stage(state)):
        return err

    objects = stage_service.list_prims(state.stage)
    return ToolResult(
        success=True,
        data={
            "object_count": len(objects),
            "objects": objects,
            "message": f"Scene has {len(objects)} object(s).",
        },
    )


def rename_prim(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Move/rename a prim to a new path in the scene hierarchy."""
    if (err := require_stage(state)):
        return err

    old_path = params["old_path"]
    new_path = params["new_path"]

    try:
        success = stage_service.rename_prim(state.stage, old_path, new_path)
    except (RuntimeError, ValueError) as e:
        return ToolResult(success=False, error=str(e))

    if not success:
        return ToolResult(
            success=False, error=f"Failed to rename {old_path} to {new_path}",
        )

    state.stage = stage_service.open_stage(state.stage_path)
    logger.info("Renamed %s -> %s", old_path, new_path)
    return ToolResult(
        success=True,
        data={
            "old_path": old_path,
            "new_path": new_path,
            "message": f"Renamed {old_path} -> {new_path}",
        },
    )


def remove_prim(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove an object from the scene by prim path."""
    if (err := require_stage(state)):
        return err

    prim_path = params["prim_path"]
    try:
        success = stage_service.remove_prim(state.stage, prim_path)
    except (RuntimeError, ValueError) as e:
        return ToolResult(success=False, error=str(e))

    if not success:
        return ToolResult(
            success=False, error=f"Failed to remove {prim_path}",
        )

    state.object_count = max(0, state.object_count - 1)
    state.touch_project()
    logger.info("Removed %s", prim_path)
    return ToolResult(
        success=True,
        data={
            "prim_path": prim_path,
            "message": f"Removed {prim_path}",
        },
    )


def move_asset(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Move an existing prim to a new position/rotation."""
    if (err := require_stage(state)):
        return err

    prim_path = params["prim_path"]
    tx = float(params["translate_x"])
    ty = float(params["translate_y"])
    tz = float(params["translate_z"])
    ry = float(params.get("rotate_y", 0.0))

    try:
        stage_service.set_transform(
            state.stage, prim_path,
            translate=(tx, ty, tz), rotate=(0.0, ry, 0.0),
        )
    except (RuntimeError, ValueError) as e:
        return ToolResult(success=False, error=str(e))

    stage_service.save(state.stage)
    state.touch_project()

    logger.info("Moved %s to (%s, %s, %s)", prim_path, tx, ty, tz)
    return ToolResult(
        success=True,
        data={
            "prim_path": prim_path,
            "position": {"x": tx, "y": ty, "z": tz},
            "rotation_y": ry,
            "message": f"Moved {prim_path} to ({tx}, {ty}, {tz})",
        },
    )


def list_prim_children(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List geometry parts under a prim path (useful before material binds)."""
    if (err := require_stage(state)):
        return err

    prim_path = params["prim_path"]
    children = stage_service.list_prim_children(state.stage, prim_path)

    if not children:
        return ToolResult(
            success=True,
            data={
                "prim_path": prim_path,
                "part_count": 0,
                "parts": [],
                "message": f"No geometry parts found under {prim_path}.",
            },
        )

    return ToolResult(
        success=True,
        data={
            "prim_path": prim_path,
            "part_count": len(children),
            "parts": children,
            "message": (
                f"Found {len(children)} geometry part(s) under {prim_path}. "
                "Use the prim_path of a specific part with bind_material."
            ),
        },
    )


def compute_grid_layout(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Compute evenly spaced positions for N objects in a grid."""
    count = int(params["count"])
    spacing = float(params.get("spacing", 2.0))

    placements = suggest_grid_layout(
        count,
        spacing=spacing,
        room_bounds=state.scene_defaults.default_room_bounds,
    )
    positions = [
        {"x": round(p.translate[0], 2), "z": round(p.translate[2], 2)}
        for p in placements
    ]
    return ToolResult(
        success=True,
        data={
            "count": count,
            "spacing": spacing,
            "positions": positions,
            "message": f"Computed {count} positions in grid with {spacing}m spacing.",
        },
    )


TOOLS: list[Tool] = [
    Tool(
        name="create_stage",
        description=(
            "Create a new empty USD stage with standard BowerBot hierarchy. "
            "Call this FIRST before placing any assets. "
            "Creates: /Scene/Architecture, /Scene/Furniture, /Scene/Products, "
            "/Scene/Lighting, /Scene/Props"
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Name for the scene file (without extension). "
                        "Example: 'retail_store'"
                    ),
                },
            },
            "required": ["filename"],
        },
    ),
    Tool(
        name="list_scene",
        description=(
            "List all objects currently in the scene with their prim paths, "
            "asset names, and positions. Use this to show the user what's "
            "in the scene so they can request changes."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    Tool(
        name="rename_prim",
        description=(
            "Move/rename a prim to a new path in the scene hierarchy. "
            "This changes the USD prim path, letting the user reorganize "
            "the scene structure. The new path can be any valid USD path."
        ),
        parameters={
            "type": "object",
            "properties": {
                "old_path": {
                    "type": "string",
                    "description": "Current prim path (e.g. '/Scene/Products/mug_01')",
                },
                "new_path": {
                    "type": "string",
                    "description": "New prim path (e.g. '/Scene/MyDisplay/CoffeeMug')",
                },
            },
            "required": ["old_path", "new_path"],
        },
    ),
    Tool(
        name="remove_prim",
        description="Remove an object from the scene by its prim path.",
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": "Prim path to remove (e.g. '/Scene/Furniture/Table_01')",
                },
            },
            "required": ["prim_path"],
        },
    ),
    Tool(
        name="move_asset",
        description=(
            "Move an existing object to a new position. "
            "Use this instead of place_asset when repositioning "
            "an object that is already in the scene."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Prim path of the object to move "
                        "(e.g. '/Scene/Products/Mug_01'). "
                        "Use list_scene to find prim paths."
                    ),
                },
                "translate_x": {"type": "number", "description": "New X position in meters."},
                "translate_y": {"type": "number", "description": "New Y position in meters."},
                "translate_z": {"type": "number", "description": "New Z position in meters."},
                "rotate_y": {
                    "type": "number",
                    "description": "Rotation around Y axis in degrees.",
                    "default": 0.0,
                },
            },
            "required": [
                "prim_path", "translate_x", "translate_y", "translate_z",
            ],
        },
    ),
    Tool(
        name="list_prim_children",
        description=(
            "List all geometry parts inside a referenced asset. "
            "Use this BEFORE bind_material to discover the internal "
            "parts (table top, legs, frame, etc.) so you can target "
            "the exact mesh for material binding. Returns each part's "
            "name, type, and current material."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Prim path of the asset to inspect "
                        "(e.g. '/Scene/Furniture/Table_01')."
                    ),
                },
            },
            "required": ["prim_path"],
        },
    ),
    Tool(
        name="compute_grid_layout",
        description=(
            "Compute evenly spaced positions for N objects in a grid, "
            "centered in the room. Returns a list of (x, z) positions. "
            "Use this to plan furniture layouts before calling place_asset."
        ),
        parameters={
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of objects to arrange.",
                },
                "spacing": {
                    "type": "number",
                    "description": "Distance between objects in meters.",
                    "default": 2.0,
                },
            },
            "required": ["count"],
        },
    ),
]


HANDLERS = {
    "create_stage": create_stage,
    "list_scene": list_scene,
    "rename_prim": rename_prim,
    "remove_prim": remove_prim,
    "move_asset": move_asset,
    "list_prim_children": list_prim_children,
    "compute_grid_layout": compute_grid_layout,
}
