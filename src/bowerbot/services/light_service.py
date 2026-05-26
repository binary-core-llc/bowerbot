# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Light service — orchestrates scene-level + asset-level light operations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Sdf

from bowerbot.schemas import LightParams, LightType, PositionMode, SceneNamespace
from bowerbot.state import SceneState
from bowerbot.utils import (
    geometry_utils,
    light_utils,
    stage_utils,
    texture_utils,
    variant_utils,
)
from bowerbot.utils.asset_folder_utils import resolve_asset_dir_for_prim
from bowerbot.utils.naming_utils import safe_prim_name

logger = logging.getLogger(__name__)


def create_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create a scene-level or asset-level light."""
    if params.get("asset_prim_path"):
        return _create_asset_light(state, params)
    return _create_scene_light(state, params)


def update_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Update a light's xform / HDRI texture; writes to scene.usda."""
    prim_path = params["prim_path"]
    asset_dir, _ = resolve_asset_dir_for_prim(state.stage, prim_path)

    translate = _unpack_vec3(params, "translate_x", "translate_y", "translate_z")
    rotate = _unpack_vec3(params, "rotate_x", "rotate_y", "rotate_z")
    texture = params.get("texture")

    if asset_dir is not None and translate is not None:
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

    stage_utils.update_light(
        state.stage,
        prim_path,
        translate=translate,
        rotate=rotate,
        texture=_stage_scene_texture(state, texture),
    )
    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Updated light at %s", prim_path)
    return {
        "prim_path": prim_path,
        "message": f"Updated light at {prim_path}",
    }


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
            "suspect_variant_sets": variant_utils.suspect_variant_sets_in_asset(
                asset_dir,
            ),
            "message": f"Removed asset light {light_name} from {asset_dir.name}",
        }

    texture_file = stage_utils.get_light_texture(state.stage, prim_path)
    carrier_path = str(Sdf.Path(prim_path).GetParentPath())
    success = stage_utils.remove_prim(state.stage, prim_path)
    if not success:
        msg = f"Failed to remove light {prim_path}"
        raise RuntimeError(msg)

    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Removed scene light at %s", prim_path)
    data: dict[str, Any] = {
        "prim_path": prim_path,
        "suspect_variant_sets": variant_utils.suspect_variant_sets_on_scene_carrier(
            state.stage, carrier_path,
        ),
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
        light_link_includes=params.get("light_link_includes") or [],
    )

    composed_path = light_utils.add_light_to_folder(
        asset_dir=asset_dir, light_name=safe_name, light=light,
    )

    state.stage = stage_utils.open_stage(state.stage_path)

    asset_local_tail = composed_path.lstrip("/").split("/", 1)[1]
    scene_light_path = f"{ref_prim_path}/{asset_local_tail}"
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

    safe_name = safe_prim_name(params["light_name"])
    prim_path = stage_utils.unique_prim_path(
        state.stage, SceneNamespace.LIGHTING, safe_name,
    )

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
        light_link_includes=params.get("light_link_includes") or [],
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
) -> tuple[float, float, float] | None:
    """Read a triple of optional keys; return ``None`` if all are missing."""
    if all(params.get(k) is None for k in (kx, ky, kz)):
        return None
    return (
        float(params.get(kx, 0.0)),
        float(params.get(ky, 0.0)),
        float(params.get(kz, 0.0)),
    )
