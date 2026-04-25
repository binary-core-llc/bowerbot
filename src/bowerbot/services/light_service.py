# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Light service — orchestrates scene-level + asset-level light operations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from bowerbot.schemas import LightParams, LightType, PositionMode
from bowerbot.state import SceneState
from bowerbot.utils import geometry_utils, light_utils, stage_utils, texture_utils
from bowerbot.utils.asset_folder_utils import resolve_asset_dir_for_prim
from bowerbot.utils.naming_utils import safe_prim_name

logger = logging.getLogger(__name__)


def create_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create a scene-level or asset-level light."""
    if params.get("asset_prim_path"):
        return _create_asset_light(state, params)
    return _create_scene_light(state, params)


def update_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Update a scene-level or asset-level light."""
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


def remove_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove a scene-level or asset-level light."""
    prim_path = params["prim_path"]
    asset_dir, _ = resolve_asset_dir_for_prim(state.stage, prim_path)

    if asset_dir is not None:
        light_name = prim_path.rstrip("/").split("/")[-1]
        light_utils.remove_light_from_folder(asset_dir, light_name)
        state.stage = stage_utils.open_stage(state.stage_path)
        logger.info("Removed asset light %s from %s", light_name, asset_dir.name)
        return {
            "prim_path": prim_path,
            "asset_folder": asset_dir.name,
            "message": f"Removed light {light_name} from {asset_dir.name}",
        }

    texture_file = stage_utils.get_light_texture(state.stage, prim_path)
    success = stage_utils.remove_prim(state.stage, prim_path)
    if not success:
        msg = f"Failed to remove light {prim_path}"
        raise RuntimeError(msg)

    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Removed scene light at %s", prim_path)
    data: dict[str, Any] = {
        "prim_path": prim_path,
        "message": f"Removed light at {prim_path}",
    }
    if texture_file:
        data["texture_file"] = texture_file
    return data


# ── Internal: create ──


def _create_asset_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Author a light inside an ASWF asset's ``lgt.usda``."""
    asset_prim_path = params["asset_prim_path"]
    light_type = LightType(params["light_type"])

    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(
        state.stage, asset_prim_path,
    )
    if asset_dir is None or ref_prim_path is None:
        msg = (
            f"Cannot find ASWF asset folder for {asset_prim_path}. "
            f"Asset-level lights only work on ASWF folder assets."
        )
        raise ValueError(msg)

    tx = float(params.get("translate_x", 0.0))
    ty = float(params.get("translate_y", 0.0))
    tz = float(params.get("translate_z", 0.0))

    mode = PositionMode(
        params.get("position_mode", PositionMode.BOUNDS_OFFSET.value),
    )
    tx, ty, tz = geometry_utils.resolve_asset_position(
        mode,
        geometry_utils.get_geometry_bounds(asset_dir),
        tx, ty, tz,
        has_explicit_y=params.get("translate_y") is not None,
        world_to_local_mat=stage_utils.get_container_world_inverse(
            state.stage, asset_prim_path,
        ),
        asset_mpu=geometry_utils.get_mpu(asset_dir),
    )

    texture = light_utils.stage_asset_texture(asset_dir, params.get("texture"))
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

    composed_path = light_utils.add_light_to_folder(
        asset_dir=asset_dir, light_name=safe_name, light=light,
    )

    state.stage = stage_utils.open_stage(state.stage_path)

    scene_light_path = f"{ref_prim_path}/{composed_path.lstrip('/')}"
    logger.info(
        "Created asset light %s in %s/lgt.usda",
        light_type.value, asset_dir.name,
    )
    return {
        "prim_path": scene_light_path,
        "light_type": light_type.value,
        "asset_folder": asset_dir.name,
        "position": {"x": tx, "y": ty, "z": tz},
        "message": (
            f"Created {light_type.value} in {asset_dir.name}/lgt.usda. "
            f"To update this light, use prim_path: {scene_light_path}"
        ),
    }


def _create_scene_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Author a light at ``/Scene/Lighting/<name>``."""
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

    stage_utils.create_light(state.stage, prim_path, light_params)
    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Created %s at %s", light_type.value, prim_path)
    return {
        "prim_path": prim_path,
        "light_type": light_type.value,
        "position": {"x": tx, "y": ty, "z": tz},
        "intensity": light_params.intensity,
        "message": f"Created {light_type.value} at {prim_path}",
    }


# ── Internal: update ──


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
) -> dict[str, Any]:
    """Update a light authored inside an asset folder."""
    light_name = prim_path.rstrip("/").split("/")[-1]

    if translate is not None:
        mode = PositionMode(
            params.get("position_mode", PositionMode.BOUNDS_OFFSET.value),
        )
        translate = geometry_utils.resolve_asset_position(
            mode,
            geometry_utils.get_geometry_bounds(asset_dir),
            *translate,
            has_explicit_y=params.get("translate_y") is not None,
            world_to_local_mat=stage_utils.get_container_world_inverse(
                state.stage, prim_path,
            ),
            asset_mpu=geometry_utils.get_mpu(asset_dir),
        )

    light_utils.update_light_in_folder(
        asset_dir=asset_dir,
        light_name=light_name,
        translate=translate,
        rotate=rotate,
        intensity=intensity,
        exposure=exposure,
        color=color,
        **extras,
    )

    state.stage = stage_utils.open_stage(state.stage_path)
    logger.info("Updated asset light at %s", prim_path)
    return {
        "prim_path": prim_path,
        "asset_folder": asset_dir.name,
        "message": f"Updated asset light at {prim_path}",
    }


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
) -> dict[str, Any]:
    """Update a scene-level light."""
    stage_utils.update_light(
        state.stage,
        prim_path,
        intensity=intensity,
        exposure=exposure,
        color=color,
        translate=translate,
        rotate=rotate,
        **extras,
    )
    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Updated scene light at %s", prim_path)
    return {
        "prim_path": prim_path,
        "message": f"Updated scene light at {prim_path}",
    }


# ── Internal: helpers ──


def _stage_scene_texture(
    state: SceneState, texture: str | None,
) -> str | None:
    """Copy a scene-level texture into ``<project>/textures/``."""
    if texture is None:
        return None
    source = Path(texture)
    if not source.exists():
        return texture
    if state.project is None:
        msg = "No project set; cannot copy scene-level texture."
        raise RuntimeError(msg)
    return texture_utils.copy_texture_to_project(source, state.project.path)


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
