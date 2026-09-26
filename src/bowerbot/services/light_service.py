# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Light service — orchestrates scene-level + asset-level light operations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Sdf

from bowerbot.schemas import (
    ASWFLayerNames,
    LightParams,
    LightRules,
    LightType,
    PositionMode,
    SceneNamespace,
)
from bowerbot.state import SceneState
from bowerbot.utils import light_utils, stage_utils, texture_utils, variants
from bowerbot.utils.core.asset_folder import (
    resolve_asset_dir_for_prim,
    resolve_default_prim_name,
)
from bowerbot.utils.core.integrity import (
    asset_local_targets,
    composed_prim_paths,
    drop_refs_to_vanished,
    remove_scene_prim,
    require_prims,
)
from bowerbot.utils.core.naming import clean_prim_name, unique_prim_path
from bowerbot.utils.core.transforms import (
    orientation_in_asset,
    orientation_in_scene,
    read_translate_rotate,
    resolve_position_in_asset,
    scene_correction,
    world_position,
)
from bowerbot.utils.core.values import read_axes, unpack_vec3

logger = logging.getLogger(__name__)


def list_light_type_properties(
    _state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every UsdLux input the given light type declares."""
    light_type = LightType(params["light_type"])
    return light_utils.list_light_type_properties(light_type).model_dump()


def create_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create a scene-level or asset-level light."""
    stage = state.require_stage()
    light_type = LightType(params["light_type"])
    safe_name = clean_prim_name(params["light_name"], "Light")
    attributes = dict(params.get("attributes") or {})
    light_utils.refuse_unknown_light_attributes(light_type, attributes)
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
        if light_type in LightRules.SCENE_ONLY_TYPES:
            msg = (
                f"{light_type.value} is a scene-level environment light and "
                f"cannot be nested in an asset. Create it without "
                f"asset_prim_path."
            )
            raise ValueError(msg)
        asset_dir, ref_prim_path = resolve_asset_dir_for_prim(
            stage, asset_prim_path,
        )
        if asset_dir is None or ref_prim_path is None:
            msg = (
                f"Cannot find ASWF asset folder for {asset_prim_path}. "
                f"Asset-level lights only work on ASWF folder assets."
            )
            raise ValueError(msg)
        light_link_includes = asset_local_targets(
            stage, light_link_includes, ref_prim_path,
            resolve_default_prim_name(asset_dir), "light_link_includes",
        )

        tx, ty, tz = resolve_position_in_asset(
            stage, asset_prim_path, asset_dir,
            PositionMode(params.get("position_mode", PositionMode.BOUNDS_OFFSET.value)),
            read_axes(params, "translate_x", "translate_y", "translate_z"),
        )

        light = LightParams(
            light_type=light_type,
            translate=(tx, ty, tz),
            rotate=orientation_in_asset(rotate, scene_correction(stage, asset_dir)),
            texture=light_utils.stage_asset_texture(
                asset_dir, params.get("texture"),
                library_dir=state.library_dir, project_dir=state.project_dir,
            ),
            light_link_includes=light_link_includes,
            attributes=attributes,
        )
        composed_path = light_utils.add_light_to_folder(
            asset_dir=asset_dir, light_name=safe_name, light=light,
        )

        stage = state.reopen_stage()

        asset_local_tail = composed_path.lstrip("/").split("/", 1)[1]
        scene_light_path = f"{ref_prim_path}/{asset_local_tail}"
        wx, wy, wz = world_position(stage.GetPrimAtPath(scene_light_path))
        logger.info(
            "Created asset light %s in %s/lgt.usda",
            light_type.value, asset_dir.name,
        )
        return {
            "prim_path": scene_light_path,
            "light_type": light_type.value,
            "asset_folder": asset_dir.name,
            "position": {"x": round(wx, 4), "y": round(wy, 4), "z": round(wz, 4)},
            "message": (
                f"Created {light_type.value} in {asset_dir.name}/lgt.usda. "
                f"To update this light, use prim_path: {scene_light_path}"
            ),
        }

    require_prims(stage, light_link_includes, "light_link_includes")
    prim_path = unique_prim_path(
        stage, SceneNamespace.LIGHTING, safe_name,
    )
    light = LightParams(
        light_type=light_type,
        translate=(tx, ty, tz),
        rotate=rotate,
        texture=texture_utils.stage_scene_texture(
            params.get("texture"),
            library_dir=state.library_dir,
            project_dir=state.project_dir,
        ),
        light_link_includes=light_link_includes,
        attributes=attributes,
    )
    light_utils.create_light(stage, prim_path, light)
    stage_utils.save_stage(stage)
    state.touch_project()

    logger.info("Created %s at %s", light_type.value, prim_path)
    return {
        "prim_path": prim_path,
        "light_type": light_type.value,
        "position": {"x": tx, "y": ty, "z": tz},
        "message": f"Created {light_type.value} at {prim_path}",
    }


def update_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Update a light's xform / HDRI texture in its asset or in scene.usda.

    Translate and rotate axes left out keep their current values.
    """
    stage = state.require_stage()
    prim_path = params["prim_path"]
    prim = light_utils.require_light(stage, prim_path)
    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(stage, prim_path)
    texture = params.get("texture")

    if asset_dir is not None and ref_prim_path is not None:
        light_name = prim_path.rstrip("/").split("/")[-1]
        current_translate, current_rotate = light_utils.light_xform_in_folder(
            asset_dir, light_name,
        )
        correction = scene_correction(stage, asset_dir)
        rotate = unpack_vec3(
            params, "rotate_x", "rotate_y", "rotate_z",
            orientation_in_scene(current_rotate, correction),
        )
        given = read_axes(params, "translate_x", "translate_y", "translate_z")
        translate = None
        if any(axis is not None for axis in given):
            translate = resolve_position_in_asset(
                stage, ref_prim_path, asset_dir,
                PositionMode(params.get("position_mode", PositionMode.BOUNDS_OFFSET.value)),
                given,
                current_local=current_translate,
                current_world=world_position(prim),
            )
        light_utils.update_light_in_folder(
            asset_dir,
            light_name,
            translate=translate,
            rotate=None if rotate is None else orientation_in_asset(rotate, correction),
            texture=light_utils.stage_asset_texture(
                asset_dir, texture,
                library_dir=state.library_dir, project_dir=state.project_dir,
            ),
        )
        state.reopen_stage()
    else:
        current_translate, current_rotate = read_translate_rotate(prim)
        light_utils.update_light(
            stage,
            prim_path,
            translate=unpack_vec3(
                params, "translate_x", "translate_y", "translate_z", current_translate,
            ),
            rotate=unpack_vec3(params, "rotate_x", "rotate_y", "rotate_z", current_rotate),
            texture=texture_utils.stage_scene_texture(
                texture, library_dir=state.library_dir, project_dir=state.project_dir,
            ),
        )
        stage_utils.save_stage(stage)

    state.touch_project()
    logger.info("Updated light at %s", prim_path)
    return {
        "prim_path": prim_path,
        "message": f"Updated light at {prim_path}",
    }


def remove_light(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove a scene-level or asset-level light."""
    stage = state.require_stage()
    prim_path = params["prim_path"]
    light_utils.require_light(stage, prim_path)
    asset_dir, _ = resolve_asset_dir_for_prim(stage, prim_path)

    if asset_dir is not None:
        light_name = prim_path.rstrip("/").split("/")[-1]
        before = composed_prim_paths(stage)
        if not light_utils.remove_light_from_folder(asset_dir, light_name):
            msg = (
                f"{prim_path} is not a light in {asset_dir.name}'s "
                f"{ASWFLayerNames.LGT}, so it can't be removed: it comes "
                "from the asset's own files."
            )
            raise ValueError(msg)
        scrubbed = drop_refs_to_vanished(state.reopen_stage(), before)
        logger.info("Removed asset light %s from %s", light_name, asset_dir.name)
        return {
            "prim_path": prim_path,
            "asset_folder": asset_dir.name,
            "scrubbed_dangling_refs": scrubbed,
            "suspect_variant_sets": variants.suspects.suspect_variant_sets_in_asset(
                asset_dir,
            ),
            "message": f"Removed asset light {light_name} from {asset_dir.name}",
        }

    texture_file = light_utils.get_light_texture(stage, prim_path)
    carrier_path = str(Sdf.Path(prim_path).GetParentPath())
    scrubbed = remove_scene_prim(stage, prim_path)
    state.touch_project()

    logger.info("Removed scene light at %s", prim_path)
    data: dict[str, Any] = {
        "prim_path": prim_path,
        "scrubbed_dangling_refs": scrubbed,
        "suspect_variant_sets": variants.suspects.suspect_variant_sets_on_scene_carrier(
            stage, carrier_path,
        ),
        "message": f"Removed light at {prim_path}",
    }
    if texture_file:
        data["texture_file"] = texture_file
        data["texture_name"] = Path(texture_file).name
    return data
