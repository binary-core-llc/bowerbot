# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Camera tools — schema discovery + create / update / remove scene cameras."""

from __future__ import annotations

from typing import Any

from bowerbot.services import camera_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage


def list_camera_properties(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Return every attribute the Camera prim schema declares."""
    try:
        data = camera_service.list_camera_properties(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def create_camera(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Create a scene-level camera."""
    if (err := require_stage(state)):
        return err
    try:
        data = camera_service.create_camera(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def update_camera(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Reposition or re-aim an existing scene camera."""
    if (err := require_stage(state)):
        return err
    try:
        data = camera_service.update_camera(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def remove_camera(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove a scene camera."""
    if (err := require_stage(state)):
        return err
    try:
        data = camera_service.remove_camera(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


_LOOK_AT = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 3,
    "maxItems": 3,
    "description": (
        "[x, y, z] point in scene units the camera should face. BowerBot "
        "computes the rotation (up-axis aware). Use INSTEAD of "
        "rotate_x/y/z."
    ),
}


TOOLS: list[Tool] = [
    Tool(
        name="list_camera_properties",
        description=(
            "Live UsdGeom schema view of every attribute the Camera prim "
            "declares: name, type, default, documentation, and "
            "allowed_tokens (e.g. projection: perspective/orthographic). "
            "Call this BEFORE create_camera to discover the attribute "
            "names and defaults (focalLength, fStop, focusDistance, "
            "clippingRange, horizontalAperture, ...). Pass any subset of "
            "those names back in create_camera's attributes dict."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    Tool(
        name="create_camera",
        description=(
            "Create a USD camera in /Scene/Cameras. Aim it with EXACTLY "
            "ONE of look_at (a point the camera faces; BowerBot computes "
            "the rotation for the scene's up axis) or rotate_x/y/z degrees "
            "(USD cameras face local -Z). Camera attributes are passed via "
            "the attributes dict using their exact UsdGeom names; call "
            "list_camera_properties FIRST to discover them. Units: "
            "focalLength and the apertures are millimeter-style values "
            "identical in every scene (never unit-scaled; default 50 = "
            "50mm lens); clippingRange and focusDistance are in scene "
            "units (a clippingRange sized for the scene's units is "
            "authored by default). Orthographic framing: the visible "
            "width is horizontalAperture * 0.1 scene units (aperture 200 "
            "frames a 20-unit-wide plan view); focalLength has no effect "
            "in ortho. Depth of field needs fStop > 0 plus focusDistance. "
            "Returns the prim_path, position, and resolved rotation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "camera_name": {
                    "type": "string",
                    "description": (
                        "Human-readable name (e.g. 'Hero_Cam', 'TopDown')."
                    ),
                },
                "translate_x": {
                    "type": "number",
                    "description": "X position in scene units.",
                    "default": 0.0,
                },
                "translate_y": {
                    "type": "number",
                    "description": "Y position in scene units.",
                    "default": 0.0,
                },
                "translate_z": {
                    "type": "number",
                    "description": "Z position in scene units.",
                    "default": 0.0,
                },
                "look_at": _LOOK_AT,
                "rotate_x": {
                    "type": "number",
                    "description": "Rotation around X in degrees.",
                },
                "rotate_y": {
                    "type": "number",
                    "description": "Rotation around Y in degrees.",
                },
                "rotate_z": {
                    "type": "number",
                    "description": "Rotation around Z in degrees.",
                },
                "attributes": {
                    "type": "object",
                    "description": (
                        "Camera attributes by exact UsdGeom name (e.g. "
                        "'focalLength', 'fStop', 'focusDistance', "
                        "'projection', 'clippingRange'). Use "
                        "list_camera_properties to discover names and "
                        "defaults. Unknown names are refused."
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="update_camera",
        description=(
            "Reposition or re-aim an existing scene camera. Pass new "
            "translate values, and EXACTLY ONE of look_at (re-aim at a "
            "point; uses the new position if given, else the camera's "
            "current position) or rotate_x/y/z degrees. For any other "
            "camera attribute (focalLength, fStop, projection, ...) use "
            "set_prim_attribute on the camera prim."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Full prim path of the camera (e.g. "
                        "'/Scene/Cameras/Hero_Cam'). Use list_scene to "
                        "find it."
                    ),
                },
                "translate_x": {
                    "type": "number",
                    "description": "New X position in scene units.",
                },
                "translate_y": {
                    "type": "number",
                    "description": "New Y position in scene units.",
                },
                "translate_z": {
                    "type": "number",
                    "description": "New Z position in scene units.",
                },
                "look_at": _LOOK_AT,
                "rotate_x": {
                    "type": "number",
                    "description": "New rotation around X in degrees.",
                },
                "rotate_y": {
                    "type": "number",
                    "description": "New rotation around Y in degrees.",
                },
                "rotate_z": {
                    "type": "number",
                    "description": "New rotation around Z in degrees.",
                },
            },
            "required": ["prim_path"],
        },
    ),
    Tool(
        name="remove_camera",
        description=(
            "Remove a camera from the scene. Reports variant sets that "
            "may have lost their purpose after the removal."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Full prim path of the camera to remove. Use "
                        "list_scene to find it."
                    ),
                },
            },
            "required": ["prim_path"],
        },
    ),
]


HANDLERS = {
    "list_camera_properties": list_camera_properties,
    "create_camera": create_camera,
    "update_camera": update_camera,
    "remove_camera": remove_camera,
}
