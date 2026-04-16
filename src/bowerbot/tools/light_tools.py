# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Light tools — create/update/remove scene-level and asset-level lights."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from bowerbot.schemas import (
    ASWFLayerNames,
    LightParams,
    LightType,
    PositionMode,
)
from bowerbot.services import light_service, stage_service
from bowerbot.services.geometry_service import (
    get_geometry_bounds,
    get_mpu,
    resolve_asset_position,
)
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage, resolve_project_dir
from bowerbot.utils.file_utils import copy_texture_to_project
from bowerbot.utils.naming import safe_prim_name
from bowerbot.utils.usd_utils import resolve_asset_dir_for_prim

logger = logging.getLogger(__name__)


def create_light(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Create either a scene-level or asset-level light."""
    if (err := require_stage(state)):
        return err

    if params.get("asset_prim_path"):
        return _create_asset_light(state, params)
    return _create_scene_light(state, params)


def update_light(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Update attributes of a scene-level or asset-level light."""
    if (err := require_stage(state)):
        return err

    prim_path = params["prim_path"]
    asset_dir, _ = resolve_asset_dir_for_prim(state.stage, prim_path)

    translate = _unpack_vec3(params, "translate_x", "translate_y", "translate_z")
    rotate = _unpack_vec3(params, "rotate_x", "rotate_y", "rotate_z")
    color = _unpack_vec3(params, "color_r", "color_g", "color_b", default=1.0)

    intensity = _opt_float(params.get("intensity"))
    exposure = _opt_float(params.get("exposure"))
    extras = {
        key: float(params[key])
        for key in ("radius", "angle", "width", "height", "length")
        if params.get(key) is not None
    }

    if asset_dir is not None:
        return _update_asset_light(
            state, asset_dir, prim_path, params,
            translate=translate, rotate=rotate, color=color,
            intensity=intensity, exposure=exposure, extras=extras,
        )

    return _update_scene_light(
        state, prim_path,
        translate=translate, rotate=rotate, color=color,
        intensity=intensity, exposure=exposure, extras=extras,
    )


def remove_light(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove a scene-level or asset-level light."""
    if (err := require_stage(state)):
        return err

    prim_path = params["prim_path"]
    asset_dir, _ = resolve_asset_dir_for_prim(state.stage, prim_path)

    if asset_dir is not None:
        light_name = prim_path.rstrip("/").split("/")[-1]
        try:
            light_service.remove_light(asset_dir, light_name)
        except (ValueError, RuntimeError) as e:
            return ToolResult(success=False, error=str(e))

        state.stage = stage_service.open_stage(state.stage_path)
        logger.info("Removed asset light %s from %s", light_name, asset_dir.name)
        return ToolResult(
            success=True,
            data={
                "prim_path": prim_path,
                "asset_folder": asset_dir.name,
                "message": f"Removed light {light_name} from {asset_dir.name}",
            },
        )

    texture_file = stage_service.get_light_texture(state.stage, prim_path)
    try:
        success = stage_service.remove_prim(state.stage, prim_path)
    except (RuntimeError, ValueError) as e:
        return ToolResult(success=False, error=str(e))

    if not success:
        return ToolResult(
            success=False, error=f"Failed to remove light {prim_path}",
        )

    stage_service.save(state.stage)
    state.touch_project()

    logger.info("Removed scene light at %s", prim_path)
    result_data: dict[str, Any] = {
        "prim_path": prim_path,
        "message": f"Removed light at {prim_path}",
    }
    if texture_file:
        result_data["texture_file"] = texture_file
    return ToolResult(success=True, data=result_data)


def _create_asset_light(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Create a light inside an ASWF asset's ``lgt.usda``."""
    asset_prim_path = params["asset_prim_path"]
    light_type = LightType(params["light_type"])

    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(
        state.stage, asset_prim_path,
    )
    if asset_dir is None or ref_prim_path is None:
        return ToolResult(
            success=False,
            error=(
                f"Cannot find ASWF asset folder for {asset_prim_path}. "
                f"Asset-level lights only work on ASWF folder assets."
            ),
        )

    tx = float(params.get("translate_x", 0.0))
    ty = float(params.get("translate_y", 0.0))
    tz = float(params.get("translate_z", 0.0))

    mode = PositionMode(
        params.get("position_mode", PositionMode.BOUNDS_OFFSET.value),
    )
    tx, ty, tz = resolve_asset_position(
        mode,
        get_geometry_bounds(asset_dir),
        tx, ty, tz,
        has_explicit_y=params.get("translate_y") is not None,
        world_to_local_mat=stage_service.get_container_world_inverse(
            state.stage, asset_prim_path,
        ),
        asset_mpu=get_mpu(asset_dir),
    )

    texture = _stage_asset_texture(asset_dir, params.get("texture"))
    safe_name = safe_prim_name(params["light_name"])

    light = LightParams(
        light_type=light_type,
        intensity=float(params.get("intensity", 1000.0)),
        exposure=float(params.get("exposure", 0.0)),
        color=(
            float(params.get("color_r", 1.0)),
            float(params.get("color_g", 1.0)),
            float(params.get("color_b", 1.0)),
        ),
        translate=(tx, ty, tz),
        rotate=(
            float(params.get("rotate_x", 0.0)),
            float(params.get("rotate_y", 0.0)),
            float(params.get("rotate_z", 0.0)),
        ),
        angle=params.get("angle"),
        texture=texture,
        radius=params.get("radius"),
        width=params.get("width"),
        height=params.get("height"),
        length=params.get("length"),
    )

    try:
        composed_path = light_service.add_light(
            asset_dir=asset_dir, light_name=safe_name, light=light,
        )
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))

    state.stage = stage_service.open_stage(state.stage_path)

    scene_light_path = f"{ref_prim_path}/{composed_path.lstrip('/')}"
    logger.info(
        "Created asset light %s in %s/lgt.usda",
        light_type.value, asset_dir.name,
    )
    return ToolResult(
        success=True,
        data={
            "prim_path": scene_light_path,
            "light_type": light_type.value,
            "asset_folder": asset_dir.name,
            "position": {"x": tx, "y": ty, "z": tz},
            "message": (
                f"Created {light_type.value} in {asset_dir.name}/lgt.usda. "
                f"To update this light, use prim_path: {scene_light_path}"
            ),
        },
    )


def _create_scene_light(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Create a scene-level light in ``/Scene/Lighting``."""
    light_type = LightType(params["light_type"])
    tx = float(params.get("translate_x", 0.0))
    ty = float(params.get("translate_y", 0.0))
    tz = float(params.get("translate_z", 0.0))

    state.object_count += 1
    safe_name = safe_prim_name(params["light_name"])
    prim_path = f"/Scene/Lighting/{safe_name}_{state.object_count:02d}"

    light_params = LightParams(
        light_type=light_type,
        intensity=float(params.get("intensity", 1000.0)),
        exposure=float(params.get("exposure", 0.0)),
        color=(
            float(params.get("color_r", 1.0)),
            float(params.get("color_g", 1.0)),
            float(params.get("color_b", 1.0)),
        ),
        translate=(tx, ty, tz),
        rotate=(
            float(params.get("rotate_x", 0.0)),
            float(params.get("rotate_y", 0.0)),
            float(params.get("rotate_z", 0.0)),
        ),
        angle=params.get("angle"),
        texture=_stage_scene_texture(state, params.get("texture")),
        radius=params.get("radius"),
        width=params.get("width"),
        height=params.get("height"),
        length=params.get("length"),
    )

    stage_service.create_light(state.stage, prim_path, light_params)
    stage_service.save(state.stage)
    state.touch_project()

    logger.info("Created %s at %s", light_type.value, prim_path)
    return ToolResult(
        success=True,
        data={
            "prim_path": prim_path,
            "light_type": light_type.value,
            "position": {"x": tx, "y": ty, "z": tz},
            "intensity": light_params.intensity,
            "message": f"Created {light_type.value} at {prim_path}",
        },
    )


def _update_asset_light(
    state: SceneState,
    asset_dir: Path,
    prim_path: str,
    params: dict[str, Any],
    *,
    translate: tuple[float, float, float] | None,
    rotate: tuple[float, float, float] | None,
    color: tuple[float, float, float] | None,
    intensity: float | None,
    exposure: float | None,
    extras: dict[str, float],
) -> ToolResult:
    """Update a light inside an asset folder."""
    light_name = prim_path.rstrip("/").split("/")[-1]

    if translate is not None:
        mode = PositionMode(
            params.get("position_mode", PositionMode.BOUNDS_OFFSET.value),
        )
        translate = resolve_asset_position(
            mode,
            get_geometry_bounds(asset_dir),
            *translate,
            has_explicit_y=params.get("translate_y") is not None,
            world_to_local_mat=stage_service.get_container_world_inverse(
                state.stage, prim_path,
            ),
            asset_mpu=get_mpu(asset_dir),
        )

    try:
        light_service.update_light(
            asset_dir=asset_dir,
            light_name=light_name,
            translate=translate,
            rotate=rotate,
            intensity=intensity,
            exposure=exposure,
            color=color,
            **extras,
        )
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))

    state.stage = stage_service.open_stage(state.stage_path)
    logger.info("Updated asset light at %s", prim_path)
    return ToolResult(
        success=True,
        data={
            "prim_path": prim_path,
            "asset_folder": asset_dir.name,
            "message": f"Updated asset light at {prim_path}",
        },
    )


def _update_scene_light(
    state: SceneState,
    prim_path: str,
    *,
    translate: tuple[float, float, float] | None,
    rotate: tuple[float, float, float] | None,
    color: tuple[float, float, float] | None,
    intensity: float | None,
    exposure: float | None,
    extras: dict[str, float],
) -> ToolResult:
    """Update a scene-level light."""
    try:
        stage_service.update_light(
            state.stage,
            prim_path,
            intensity=intensity,
            exposure=exposure,
            color=color,
            translate=translate,
            rotate=rotate,
            **extras,
        )
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))

    stage_service.save(state.stage)
    state.touch_project()

    logger.info("Updated scene light at %s", prim_path)
    return ToolResult(
        success=True,
        data={
            "prim_path": prim_path,
            "message": f"Updated scene light at {prim_path}",
        },
    )


def _stage_asset_texture(
    asset_dir: Path, texture: str | None,
) -> str | None:
    """Copy an HDRI into the asset's ``maps/`` dir and return its ref path."""
    if not texture:
        return texture

    maps_dir = asset_dir / ASWFLayerNames.MAPS
    maps_dir.mkdir(exist_ok=True)
    tex_path = Path(texture)
    if tex_path.exists():
        dest = maps_dir / tex_path.name
        if not dest.exists():
            shutil.copy2(tex_path, dest)
        return f"./{ASWFLayerNames.MAPS}/{tex_path.name}"
    return texture


def _stage_scene_texture(
    state: SceneState, texture: str | None,
) -> str | None:
    """Copy a scene-level texture into ``<project>/textures/``."""
    if texture is None:
        return None
    source = Path(texture)
    if not source.exists():
        return texture
    return copy_texture_to_project(source, resolve_project_dir(state))


def _unpack_vec3(
    params: dict[str, Any],
    kx: str,
    ky: str,
    kz: str,
    *,
    default: float = 0.0,
) -> tuple[float, float, float] | None:
    """Read a triple of optional keys; return ``None`` if all are missing."""
    if all(params.get(k) is None for k in (kx, ky, kz)):
        return None
    return (
        float(params.get(kx, default)),
        float(params.get(ky, default)),
        float(params.get(kz, default)),
    )


def _opt_float(value: Any) -> float | None:
    """Coerce a value to ``float``, preserving ``None``."""
    return float(value) if value is not None else None


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
            },
            "required": ["light_type", "light_name"],
        },
    ),
    Tool(
        name="update_light",
        description=(
            "Update an existing light's parameters. Works for both "
            "scene-level and asset-level lights. Only modifies values you "
            "provide — everything else stays the same. Use this instead of "
            "creating a new light when the user wants to adjust intensity, "
            "color, size, position, or rotation. For asset lights, use "
            "position_mode to choose between absolute coordinates or "
            "bounds_offset (same as create_light)."
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
                "intensity": {"type": "number", "description": "New intensity."},
                "exposure": {
                    "type": "number",
                    "description": (
                        "New exposure (power-of-2 multiplier on intensity)."
                    ),
                },
                "color_r": {"type": "number", "description": "New red (0-1)."},
                "color_g": {"type": "number", "description": "New green (0-1)."},
                "color_b": {"type": "number", "description": "New blue (0-1)."},
                "translate_x": {"type": "number", "description": "New X position."},
                "translate_y": {"type": "number", "description": "New Y position."},
                "translate_z": {"type": "number", "description": "New Z position."},
                "radius": {"type": "number", "description": "New radius."},
                "angle": {"type": "number", "description": "New angle."},
                "width": {"type": "number", "description": "New width."},
                "height": {"type": "number", "description": "New height."},
                "length": {"type": "number", "description": "New length."},
                "rotate_x": {"type": "number", "description": "New X rotation."},
                "rotate_y": {"type": "number", "description": "New Y rotation."},
                "rotate_z": {"type": "number", "description": "New Z rotation."},
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
