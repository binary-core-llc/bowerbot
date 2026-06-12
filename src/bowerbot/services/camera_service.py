# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Camera service — orchestrates scene-level camera operations."""

from __future__ import annotations

import logging
from typing import Any

from pxr import Sdf

from bowerbot.schemas import (
    DEFAULT_CLIPPING_RANGE_METERS,
    CameraParams,
    SceneNamespace,
)
from bowerbot.state import SceneState
from bowerbot.utils import camera_utils, geometry_utils, stage_utils, variant_utils
from bowerbot.utils.naming_utils import safe_prim_name

logger = logging.getLogger(__name__)


def list_camera_properties(
    _state: SceneState, _params: dict[str, Any],
) -> dict[str, Any]:
    """Return every attribute the Camera prim schema declares."""
    return camera_utils.list_camera_properties().model_dump()


def create_camera(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create a scene-level camera, aimed via look_at or explicit rotation."""
    safe_name = safe_prim_name(params["camera_name"])
    attributes = dict(params.get("attributes") or {})
    look_at = params.get("look_at")
    rotate = geometry_utils.unpack_vec3(
        params, "rotate_x", "rotate_y", "rotate_z",
    )
    if look_at is not None and rotate is not None:
        raise ValueError("pass exactly one of 'look_at' or rotate angles.")

    tx = float(params.get("translate_x", 0.0))
    ty = float(params.get("translate_y", 0.0))
    tz = float(params.get("translate_z", 0.0))
    if look_at is not None:
        rotate = camera_utils.look_at_rotation(
            (tx, ty, tz),
            tuple(float(v) for v in look_at),
            state.up_axis.value,
        )
    if rotate is None:
        rotate = (0.0, 0.0, 0.0)

    near, far = DEFAULT_CLIPPING_RANGE_METERS
    attributes.setdefault(
        "clippingRange",
        [near / state.meters_per_unit, far / state.meters_per_unit],
    )

    prim_path = stage_utils.unique_prim_path(
        state.stage, SceneNamespace.CAMERAS, safe_name,
    )
    camera = CameraParams(
        translate=(tx, ty, tz), rotate=rotate, attributes=attributes,
    )
    try:
        camera_utils.create_camera(state.stage, prim_path, camera)
        stage_utils.save_stage(state.stage)
    except Exception:
        state.stage.Reload()
        raise
    state.touch_project()

    logger.info("Created camera at %s", prim_path)
    return {
        "prim_path": prim_path,
        "position": {"x": tx, "y": ty, "z": tz},
        "rotation": {
            "x": round(rotate[0], 4),
            "y": round(rotate[1], 4),
            "z": round(rotate[2], 4),
        },
        "message": f"Created camera at {prim_path}",
    }


def update_camera(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Reposition or re-aim an existing scene camera."""
    prim_path = params["prim_path"]
    translate = geometry_utils.unpack_vec3(
        params, "translate_x", "translate_y", "translate_z",
    )
    rotate = geometry_utils.unpack_vec3(
        params, "rotate_x", "rotate_y", "rotate_z",
    )
    look_at = params.get("look_at")
    if look_at is not None and rotate is not None:
        raise ValueError("pass exactly one of 'look_at' or rotate angles.")

    prim = camera_utils.require_camera(state.stage, prim_path)
    if look_at is not None:
        eye = (
            translate if translate is not None
            else camera_utils.camera_translate(prim)
        )
        rotate = camera_utils.look_at_rotation(
            eye,
            tuple(float(v) for v in look_at),
            state.up_axis.value,
        )

    camera_utils.update_camera(
        state.stage, prim_path, translate=translate, rotate=rotate,
    )
    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Updated camera at %s", prim_path)
    return {
        "prim_path": prim_path,
        "message": f"Updated camera at {prim_path}",
    }


def remove_camera(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove a scene camera."""
    prim_path = params["prim_path"]
    camera_utils.require_camera(state.stage, prim_path)

    carrier_path = str(Sdf.Path(prim_path).GetParentPath())
    success = stage_utils.remove_prim(state.stage, prim_path)
    if not success:
        msg = f"Failed to remove camera {prim_path}"
        raise RuntimeError(msg)

    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Removed camera at %s", prim_path)
    return {
        "prim_path": prim_path,
        "suspect_variant_sets": variant_utils.suspect_variant_sets_on_scene_carrier(
            state.stage, carrier_path,
        ),
        "message": f"Removed camera at {prim_path}",
    }
