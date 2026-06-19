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
    """List the scene contents: every managed object, each tagged with its kind."""
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


def list_prim_attributes(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List every attribute on a prim with type + current value."""
    if (err := require_stage(state)):
        return err
    try:
        data = stage_service.list_prim_attributes(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def set_prim_attribute(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Author an attribute opinion on a prim (per-instance, scene.usda)."""
    if (err := require_stage(state)):
        return err
    try:
        data = stage_service.set_prim_attribute(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def save_scene_snapshot(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Flatten the composed scene into a named, self-contained snapshot file."""
    if (err := require_stage(state)):
        return err
    try:
        data = stage_service.save_scene_snapshot(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def list_scene_snapshots(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List every snapshot .usda file alongside scene.usda."""
    if (err := require_stage(state)):
        return err
    try:
        data = stage_service.list_scene_snapshots(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def delete_scene_snapshot(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Delete a named snapshot file."""
    if (err := require_stage(state)):
        return err
    try:
        data = stage_service.delete_scene_snapshot(state, params)
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
            "Create or reopen the project's scene file. Creates an empty "
            "/Scene root prim if the scene file is missing, or reopens it "
            "with its current contents (returning the object count) if it "
            "already exists. You normally do NOT need to call this: the "
            "scene is created and opened with the project, and "
            "place_asset/move_asset operate on the already-open stage. "
            "Standard groups (/Scene/Furniture, /Scene/Products, ...) are "
            "created on demand when assets are placed, not by this tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Informational label only. The scene is always "
                        "written to the project's scene.usda regardless of "
                        "this value; it has no effect on the output path."
                    ),
                },
            },
        },
    ),
    Tool(
        name="list_scene",
        description=(
            "List the contents of the scene. Returns object_count and an "
            "objects array; every object BowerBot manages is included, of "
            "any kind, and each entry carries a 'kind' tag plus "
            "kind-specific fields. Kinds include 'asset'/'geometry' "
            "(prim_path, type, asset, position, bounds {min, max}), 'light' "
            "(prim_path, light_type, position, intensity/exposure/color when "
            "authored), 'camera' (prim_path, type, projection, focal_length, "
            "position), and 'physics_scene'/'joint'/'collision_group' "
            "(prim_path, type, plus body0/body1 or name). New object kinds "
            "appear here automatically. Call this to see what is actually "
            "in the scene rather than assuming a kind is absent. Use an "
            "object's bounds to size or place items on a surface without "
            "reading USD files."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    Tool(
        name="rename_prim",
        description=(
            "Move/rename a prim to a new path in the scene hierarchy. "
            "This changes the USD prim path, letting the user reorganize "
            "the scene structure. The new path can be any valid USD path. "
            "Also rewrites every relationship target across the scene that "
            "pointed at the old path (material bindings, joint bodies, "
            "collision-group members) so they follow the prim, and returns "
            "rewritten_refs ({rels_touched: [...]}) listing the rebased "
            "relationships; report any rewrites to the user."
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
        description=(
            "Remove an object from the scene by its prim path. Also scrubs "
            "any relationship targets left dangling by the removal and "
            "returns scrubbed_dangling_refs ({rels_touched: [...]}) listing "
            "what was cleaned up. Handles top-level placements and prims "
            "nested inside a referenced asset's contents.usda."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Prim path to remove (e.g. '/Scene/Furniture/Table_01')."
                    ),
                },
            },
            "required": ["prim_path"],
        },
    ),
    Tool(
        name="move_asset",
        description=(
            "Move an existing object. Any axis (translate_x, translate_y, "
            "translate_z, rotate_y) you omit keeps its current value, so "
            "for single-axis moves pass only the axis the user asked to "
            "change. Use this instead of place_asset when repositioning "
            "an object already in the scene. translate_x/y/z are "
            "world-space meters; for a prim nested inside a referenced "
            "asset's contents (path containing '/asset/contents/'), the "
            "move is converted into the asset's local space and written "
            "into that asset folder's contents.usda, while the returned "
            "'position' still echoes the world-space values you passed."
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
                "translate_x": {
                    "type": "number",
                    "description": "New X in meters. Omit to keep current X.",
                },
                "translate_y": {
                    "type": "number",
                    "description": "New Y in meters. Omit to keep current Y.",
                },
                "translate_z": {
                    "type": "number",
                    "description": "New Z in meters. Omit to keep current Z.",
                },
                "rotate_y": {
                    "type": "number",
                    "description": (
                        "Rotation around Y axis in degrees. Omit to keep "
                        "current rotation."
                    ),
                },
            },
            "required": ["prim_path"],
        },
    ),
    Tool(
        name="list_prim_children",
        description=(
            "List all geometry parts inside a referenced asset. "
            "Use this BEFORE bind_material to discover the internal "
            "parts (table top, legs, frame, etc.) so you can target "
            "the exact mesh for material binding. Returns each part's "
            "prim_path, name, type, is_mesh, is_bindable, current_material, "
            "and world-space bounds {min, max}. Use a part's prim_path with "
            "bind_material."
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
    Tool(
        name="list_prim_attributes",
        description=(
            "List every attribute on a USD prim with type and current "
            "value. Use this to discover what is settable when the user "
            "asks about uncommon parameters (e.g. material specular, "
            "transmission, sheen, coat; light angle, treatAsLine, "
            "colorTemperature; any UsdLux/UsdShade/UsdGeom schema "
            "attribute). After discovery, use set_prim_attribute to "
            "author overrides. Returns each attribute as "
            "{name, type, value, authored}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Exact prim path to inspect (e.g. "
                        "'/Scene/Furniture/Table_01/asset/mtl/walnut/"
                        "standard_surface' or '/Scene/Lighting/Key_01')."
                    ),
                },
            },
            "required": ["prim_path"],
        },
    ),
    Tool(
        name="set_prim_attribute",
        description=(
            "Author or clear an attribute opinion on a prim in scene.usda. "
            "Type is inferred from the prim's schema or the shader "
            "registry (call list_prim_attributes first to see what is "
            "settable). Pass value=null to clear an authored opinion. "
            "Every value change in BowerBot goes through scene.usda: "
            "asset files (mtl.usda, lgt.usda, variants.usda) are only "
            "touched when DEFINING or REMOVING materials/lights/variants "
            "via the dedicated tools (create_material, create_light, "
            "add_asset_material_variant, etc.). To update the same parameter "
            "on multiple placements, call this once per placement. "
            "Works for any UsdLux / UsdShade / UsdGeom attribute (sheen, "
            "coat, specular, colorTemperature, treatAsLine, intensity, "
            "exposure, radius, angle, etc.)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Exact prim path the attribute lives on. For a "
                        "material shader: "
                        "/Scene/<Group>/<Asset>/asset/mtl/<material>/<shader>. "
                        "For an asset light: "
                        "/Scene/<Group>/<Asset>/asset/lgt/<light_name>. "
                        "For a scene light: /Scene/Lighting/<light_name>."
                    ),
                },
                "attribute_name": {
                    "type": "string",
                    "description": (
                        "Attribute name including any namespace prefix "
                        "(e.g. 'inputs:sheen', 'inputs:colorTemperature', "
                        "'xformOp:translate')."
                    ),
                },
                "value": {
                    "type": ["array", "boolean", "number", "string", "null"],
                    "description": (
                        "Value matching the attribute's type (float for "
                        "Float, list of 3 numbers for Color3f / Vec3f, "
                        "string for Token / Asset, bool for Bool). Pass "
                        "the JSON value itself, not a string encoding of "
                        "it. Pass null to clear the authored opinion."
                    ),
                },
            },
            "required": ["prim_path", "attribute_name", "value"],
        },
    ),
    Tool(
        name="save_scene_snapshot",
        description=(
            "Save a named, self-contained frozen copy of the current "
            "scene alongside scene.usda. The snapshot is a flattened, "
            "production-clean .usda file: customLayerData (DCC "
            "camera/render settings) and root-level DCC prims (e.g. "
            "/OmniverseKit_Persp) are stripped. scene.usda is NOT "
            "modified — BowerBot keeps editing it normally. The user "
            "can save multiple named snapshots (e.g. "
            "'kitchen_with_plants', 'kitchen_no_plants') and open any "
            "of them directly in their DCC as a final version. External "
            "asset references (./assets/*) are preserved inside the "
            "snapshot, so asset edits flow through when the snapshot "
            "is reopened. Refuses if a snapshot with the same name "
            "already exists unless force=true."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Snapshot name (without extension). Example: "
                        "'kitchen_with_plants'. Sanitized to alphanumeric + "
                        "underscore + hyphen. Cannot collide with scene.usda."
                    ),
                },
                "force": {
                    "type": "boolean",
                    "description": (
                        "Overwrite an existing snapshot with the same name. "
                        "Default false: refuse so the user can decide."
                    ),
                    "default": False,
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="list_scene_snapshots",
        description=(
            "List every snapshot .usda file alongside scene.usda in the "
            "project's scenes directory. Returns name, path, and size "
            "for each snapshot. Use to show the user which versions "
            "exist before deleting or overwriting."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    Tool(
        name="delete_scene_snapshot",
        description=(
            "Delete a named snapshot file. Refuses to delete scene.usda. "
            "The snapshot is gone permanently — confirm with the user "
            "before calling."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Snapshot name to delete (without extension). Must "
                        "match an existing snapshot from list_scene_snapshots."
                    ),
                },
            },
            "required": ["name"],
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
    "list_prim_attributes": list_prim_attributes,
    "set_prim_attribute": set_prim_attribute,
    "save_scene_snapshot": save_scene_snapshot,
    "list_scene_snapshots": list_scene_snapshots,
    "delete_scene_snapshot": delete_scene_snapshot,
}
