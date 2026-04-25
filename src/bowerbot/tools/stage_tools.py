# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage tools — create, list, reorganize prims in the active scene."""

from __future__ import annotations

from typing import Any

from bowerbot.services import stage_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_project, require_stage


def create_stage(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Create or reopen the project's scene file."""
    if (err := require_project(state)):
        return err
    try:
        data = stage_service.create_stage(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def list_scene(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Return every placed object and light in the scene."""
    if (err := require_stage(state)):
        return err
    try:
        data = stage_service.list_scene(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def rename_prim(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Move/rename a prim to a new path in the scene hierarchy."""
    if (err := require_stage(state)):
        return err
    try:
        data = stage_service.rename_prim(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def remove_prim(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove an object from the scene by prim path."""
    if (err := require_stage(state)):
        return err
    try:
        data = stage_service.remove_prim(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def move_asset(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Move an existing prim to a new position/rotation."""
    if (err := require_stage(state)):
        return err
    try:
        data = stage_service.move_asset(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def list_prim_children(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List geometry parts under a prim path."""
    if (err := require_stage(state)):
        return err
    try:
        data = stage_service.list_prim_children(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def compute_grid_layout(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Compute evenly spaced positions for N objects in a grid."""
    try:
        data = stage_service.compute_grid_layout(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


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
