# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Light tools — schema discovery + create / update / remove lights."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import LightType, PositionMode
from bowerbot.services import light_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage


def list_light_type_properties(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Return every UsdLux input the given light type declares."""
    try:
        data = light_service.list_light_type_properties(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def create_light(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Create a scene-level or asset-level light."""
    if (err := require_stage(state)):
        return err
    try:
        data = light_service.create_light(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def update_light(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Update an existing scene-level or asset-level light."""
    if (err := require_stage(state)):
        return err
    try:
        data = light_service.update_light(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def remove_light(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove a scene-level or asset-level light."""
    if (err := require_stage(state)):
        return err
    try:
        data = light_service.remove_light(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


TOOLS: list[Tool] = [
    Tool(
        name="list_light_type_properties",
        description=(
            "Live UsdLux schema view of every inputs:* attribute the given "
            "light type declares: name, type, default, documentation, and "
            "allowed_tokens (valid values for enum-typed inputs such as "
            "inputs:texture:format). "
            "Call this BEFORE create_light to discover the attribute names "
            "and default values that the type supports (e.g. inputs:intensity, "
            "inputs:radius for SphereLight, inputs:width/inputs:height for "
            "RectLight). Pass any subset of those names back in create_light's "
            "attributes dict."
        ),
        parameters={
            "type": "object",
            "properties": {
                "light_type": {
                    "type": "string",
                    "enum": [t.value for t in LightType],
                    "description": (
                        "Light type to introspect. DistantLight = sun/"
                        "directional, DomeLight = environment/HDRI, "
                        "SphereLight = point, RectLight = area, "
                        "DiskLight = round area, CylinderLight = tube."
                    ),
                },
            },
            "required": ["light_type"],
        },
    ),
    Tool(
        name="create_light",
        description=(
            "Create a USD light. By default creates a scene-level light in "
            "/Scene/Lighting. If asset_prim_path is provided, creates an "
            "asset-level light in that asset's lgt.usda (e.g. a lamp's bulb "
            "light). UsdLux inputs (intensity, color, radius, width, height, "
            "angle, colorTemperature, etc.) are passed via the attributes "
            "dict using their full inputs:* names. Call "
            "list_light_type_properties FIRST to discover the attribute names "
            "and defaults for the chosen light type. For asset lights, use "
            "position_mode to choose between absolute asset-local coordinates "
            "(e.g. from list_prim_children bounds) or bounds_offset "
            "(relative to the asset's surfaces)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "light_type": {
                    "type": "string",
                    "enum": [t.value for t in LightType],
                    "description": (
                        "Type of light. DistantLight = sun/directional, "
                        "DomeLight = environment/HDRI, SphereLight = point, "
                        "RectLight = area, DiskLight = round area, "
                        "CylinderLight = tube."
                    ),
                },
                "light_name": {
                    "type": "string",
                    "description": "Human-readable name (e.g. 'Key_Light', 'Sun').",
                },
                "asset_prim_path": {
                    "type": "string",
                    "description": (
                        "Optional: prim path of an asset in the scene to "
                        "attach the light to. If provided, the light is "
                        "created in the asset's lgt.usda. If omitted, the "
                        "light is created as a scene-level light."
                    ),
                },
                "position_mode": {
                    "type": "string",
                    "enum": [m.value for m in PositionMode],
                    "description": (
                        "Asset-level lights only. How to interpret translate "
                        "values: 'absolute' = world-space coordinates (as "
                        "returned by list_scene / list_prim_children) — "
                        "BowerBot converts to the asset's internal "
                        "coordinate frame automatically; 'bounds_offset' = "
                        "offsets from the asset's bounding box surfaces "
                        "(e.g. a bulb 0.5m above a lamp)."
                    ),
                    "default": PositionMode.BOUNDS_OFFSET.value,
                },
                "translate_x": {
                    "type": "number",
                    "description": "X position in meters.",
                    "default": 0.0,
                },
                "translate_y": {
                    "type": "number",
                    "description": "Y position in meters.",
                    "default": 0.0,
                },
                "translate_z": {
                    "type": "number",
                    "description": "Z position in meters.",
                    "default": 0.0,
                },
                "rotate_x": {
                    "type": "number",
                    "description": "Rotation around X axis in degrees.",
                    "default": 0.0,
                },
                "rotate_y": {
                    "type": "number",
                    "description": "Rotation around Y axis in degrees.",
                    "default": 0.0,
                },
                "rotate_z": {
                    "type": "number",
                    "description": "Rotation around Z axis in degrees.",
                    "default": 0.0,
                },
                "texture": {
                    "type": "string",
                    "description": (
                        "DomeLight / RectLight only. Absolute path to an "
                        "HDRI or texture file on disk. BowerBot copies the "
                        "file into the project's textures/ (scene light) or "
                        "the asset's maps/ (asset light) and authors the "
                        "relative reference into inputs:texture:file. "
                        "Pre-staged relative paths (e.g. ./textures/foo.hdr) "
                        "are accepted unchanged."
                    ),
                },
                "attributes": {
                    "type": "object",
                    "description": (
                        "Free dict of UsdLux inputs:* attributes to author, "
                        "keyed by full attribute name "
                        "(e.g. 'inputs:intensity', 'inputs:color', "
                        "'inputs:radius'). Use list_light_type_properties to "
                        "discover supported names and defaults. Spatial "
                        "inputs (radius, width, height, length) are given in "
                        "meters; BowerBot converts to the asset's native "
                        "units for asset lights."
                    ),
                    "additionalProperties": True,
                },
                "light_link_includes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of prim paths the light should "
                        "illuminate. Default empty = light affects every "
                        "prim (standard USD behavior). Populated = the "
                        "light only affects the listed prims and their "
                        "descendants. Authored as a UsdLux light:link "
                        "collection."
                    ),
                },
            },
            "required": ["light_type", "light_name"],
        },
    ),
    Tool(
        name="update_light",
        description=(
            "Update an existing light's position, rotation, or HDRI "
            "texture. Position/rotation work for both scene-level and "
            "asset-level lights. Only the things this tool covers go here: "
            "xform ops (translate/rotate, including bounds_offset for asset "
            "lights) and texture (file copied into <project>/textures/, "
            "scene-level lights only; to change an asset-level light's HDRI, "
            "recreate it with create_light). For any UsdLux attribute "
            "(intensity, exposure, "
            "color, radius, angle, width, height, length, colorTemperature, "
            "diffuse, specular, normalize, etc.), use set_prim_attribute on "
            "the light prim directly."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Full prim path of the light to update (scene or "
                        "asset). Use list_scene to find it."
                    ),
                },
                "position_mode": {
                    "type": "string",
                    "enum": [m.value for m in PositionMode],
                    "description": (
                        "Asset-level lights only. How to interpret "
                        "translate values: 'absolute' = world-space "
                        "coordinates (BowerBot converts to asset-internal "
                        "frame); 'bounds_offset' = offsets from the "
                        "asset's bounding box surfaces."
                    ),
                    "default": PositionMode.BOUNDS_OFFSET.value,
                },
                "translate_x": {"type": "number", "description": "New X position."},
                "translate_y": {"type": "number", "description": "New Y position."},
                "translate_z": {"type": "number", "description": "New Z position."},
                "rotate_x": {"type": "number", "description": "New X rotation."},
                "rotate_y": {"type": "number", "description": "New Y rotation."},
                "rotate_z": {"type": "number", "description": "New Z rotation."},
                "texture": {
                    "type": "string",
                    "description": (
                        "DomeLight / RectLight only. Path to an HDRI or "
                        "texture file, copied into <project>/textures/ and "
                        "set as inputs:texture:file. Applies to scene-level "
                        "lights; to change an asset-level light's HDRI, "
                        "recreate it with create_light."
                    ),
                },
            },
            "required": ["prim_path"],
        },
    ),
    Tool(
        name="remove_light",
        description=(
            "Remove a light from the scene. Works for both scene-level and "
            "asset-level lights. For asset lights, removes from the asset's "
            "lgt.usda."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Full prim path of the light to remove. Use "
                        "list_scene to find it."
                    ),
                },
            },
            "required": ["prim_path"],
        },
    ),
]


HANDLERS = {
    "list_light_type_properties": list_light_type_properties,
    "create_light": create_light,
    "update_light": update_light,
    "remove_light": remove_light,
}
