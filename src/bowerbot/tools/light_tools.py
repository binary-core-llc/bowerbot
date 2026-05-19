# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Light tools — create / update / remove scene + asset lights."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import LightType, PositionMode
from bowerbot.services import light_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage


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
        name="create_light",
        description=(
            "Create a USD light. By default creates a scene-level light in "
            "/Scene/Lighting. If asset_prim_path is provided, creates an "
            "asset-level light in that asset's lgt.usda (e.g. a lamp's bulb "
            "light). For asset lights, use position_mode to choose between "
            "absolute asset-local coordinates (e.g. from list_prim_children "
            "bounds) or bounds_offset (relative to the asset's surfaces)."
        ),
        parameters={
            "type": "object",
            "properties": {
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
                "intensity": {
                    "type": "number",
                    "description": (
                        "Light intensity. Default: 1000 for most lights, "
                        "1.0 for DomeLight."
                    ),
                    "default": 1000.0,
                },
                "exposure": {
                    "type": "number",
                    "description": (
                        "Power-of-2 multiplier on intensity (camera stops). "
                        "Final brightness = intensity * 2^exposure. +1 "
                        "doubles, -1 halves. Default: 0."
                    ),
                    "default": 0.0,
                },
                "color_r": {
                    "type": "number",
                    "description": "Red channel (0-1). Default: 1.0.",
                    "default": 1.0,
                },
                "color_g": {
                    "type": "number",
                    "description": "Green channel (0-1). Default: 1.0.",
                    "default": 1.0,
                },
                "color_b": {
                    "type": "number",
                    "description": "Blue channel (0-1). Default: 1.0.",
                    "default": 1.0,
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
                "angle": {
                    "type": "number",
                    "description": (
                        "DistantLight only: angular size in degrees. "
                        "0.53 = realistic sun."
                    ),
                },
                "texture": {
                    "type": "string",
                    "description": "DomeLight only: path to HDRI texture file.",
                },
                "radius": {
                    "type": "number",
                    "description": (
                        "SphereLight/DiskLight/CylinderLight: light "
                        "radius in meters."
                    ),
                },
                "width": {
                    "type": "number",
                    "description": "RectLight only: width in meters.",
                },
                "height": {
                    "type": "number",
                    "description": "RectLight only: height in meters.",
                },
                "length": {
                    "type": "number",
                    "description": "CylinderLight only: length in meters.",
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
                        "collection. Use this for 'this rim light only on "
                        "the hero prop' or product-shot rigs."
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
            "texture. Works for both scene-level and asset-level lights. "
            "Only the things this tool covers go here: xform ops "
            "(translate/rotate, including bounds_offset for asset lights) "
            "and texture (file copy into <project>/textures/ or the "
            "asset's maps/). For scalar attribute tweaks like intensity, "
            "exposure, color, radius, angle, width, height, length, "
            "colorTemperature, treatAsLine, etc., use set_prim_attribute "
            "on the light prim directly."
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
                        "DomeLight only. Path to an HDRI file. Scene-level "
                        "DomeLights have the file copied into "
                        "<project>/textures/; asset-level DomeLights have "
                        "it copied into the asset's maps/. The light's "
                        "inputs:texture:file is set to the relative path."
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
    "create_light": create_light,
    "update_light": update_light,
    "remove_light": remove_light,
}
