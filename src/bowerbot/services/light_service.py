# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Light service — orchestrates scene-level + asset-level light operations."""

from __future__ import annotations

import logging
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


def list_light_type_properties(
    _state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every UsdLux input the given light type declares."""
    light_type = LightType(params["light_type"])
    return light_utils.list_light_type_properties(light_type).model_dump()


def create_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create a scene-level or asset-level light."""
    light_type = LightType(params["light_type"])
    safe_name = safe_prim_name(params["light_name"])
    attributes = dict(params.get("attributes") or {})
    light_link_includes = params.get("light_link_includes") or []
    rotate = (
        float(params.get("rotate_x", 0.0)),
        float(params.get("rotate_y", 0.0)),
        float(params.get("rotate_z", 0.0)),
    )
    tx = float(params.get("translate_x", 0.0))
    ty = float(params.get("translate_y", 0.0))
    tz = float(params.get("translate_z", 0.0))

    asset_prim_path = params.get("asset_prim_path")
    if asset_prim_path:
        asset_dir, ref_prim_path = resolve_asset_dir_for_prim(
            state.stage, asset_prim_path,
        )
        if asset_dir is None or ref_prim_path is None:
            msg = (
                f"Cannot find ASWF asset folder for {asset_prim_path}. "
                f"Asset-level lights only work on ASWF folder assets."
            )
            raise ValueError(msg)

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

        light = LightParams(
            light_type=light_type,
            translate=(tx, ty, tz),
            rotate=rotate,
            texture=light_utils.stage_asset_texture(
                asset_dir, params.get("texture"),
            ),
            light_link_includes=light_link_includes,
            attributes=attributes,
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

    prim_path = stage_utils.unique_prim_path(
        state.stage, SceneNamespace.LIGHTING, safe_name,
    )
    light = LightParams(
        light_type=light_type,
        translate=(tx, ty, tz),
        rotate=rotate,
        texture=texture_utils.stage_scene_texture(
            state.project.path if state.project else None,
            params.get("texture"),
        ),
        light_link_includes=light_link_includes,
        attributes=attributes,
    )
    light_utils.create_light(state.stage, prim_path, light)
    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Created %s at %s", light_type.value, prim_path)
    return {
        "prim_path": prim_path,
        "light_type": light_type.value,
        "position": {"x": tx, "y": ty, "z": tz},
        "message": f"Created {light_type.value} at {prim_path}",
    }


def update_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Update a light's xform / HDRI texture; writes to scene.usda."""
    prim_path = params["prim_path"]
    asset_dir, _ = resolve_asset_dir_for_prim(state.stage, prim_path)

    translate = geometry_utils.unpack_vec3(
        params, "translate_x", "translate_y", "translate_z",
    )
    rotate = geometry_utils.unpack_vec3(
        params, "rotate_x", "rotate_y", "rotate_z",
    )
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

    light_utils.update_light(
        state.stage,
        prim_path,
        translate=translate,
        rotate=rotate,
        texture=texture_utils.stage_scene_texture(
            state.project.path if state.project else None, texture,
        ),
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

    texture_file = light_utils.get_light_texture(state.stage, prim_path)
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
