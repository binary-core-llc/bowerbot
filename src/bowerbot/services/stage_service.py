# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage service — orchestrates scene-level operations for the stage tools."""

from __future__ import annotations

import logging
from typing import Any

from bowerbot.state import SceneState
from bowerbot.utils import geometry_utils, stage_utils
from bowerbot.utils.naming_utils import safe_file_name

logger = logging.getLogger(__name__)


def create_stage(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create or reopen the project's scene file."""
    if state.project is None:
        msg = "No project open."
        raise RuntimeError(msg)

    safe_name = safe_file_name(params["filename"]) or "scene"
    logger.debug("create_stage filename=%s", safe_name)

    state.stage_path = state.project.scene_path
    if state.stage_path.exists():
        state.stage = stage_utils.open_stage(state.stage_path)
        state.object_count = len(stage_utils.list_prims(state.stage))
        logger.info("Reopened existing stage: %s", state.stage_path)
        return {
            "stage_path": str(state.stage_path),
            "object_count": state.object_count,
            "message": (
                f"Stage already exists at {state.stage_path} with "
                f"{state.object_count} object(s). Reopened."
            ),
        }

    state.object_count = 0
    state.stage = stage_utils.create_stage(state.stage_path)
    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Created stage: %s", state.stage_path)
    return {
        "stage_path": str(state.stage_path),
        "message": (
            f"Stage created at {state.stage_path} with standard hierarchy."
        ),
    }


def list_scene(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Return every placed object and light in the scene."""
    del params
    objects = stage_utils.list_prims(state.stage)
    return {
        "object_count": len(objects),
        "objects": objects,
        "message": f"Scene has {len(objects)} object(s).",
    }


def rename_prim(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Move/rename a prim to a new path in the scene hierarchy."""
    old_path = params["old_path"]
    new_path = params["new_path"]

    success = stage_utils.rename_prim(state.stage, old_path, new_path)
    if not success:
        msg = f"Failed to rename {old_path} to {new_path}"
        raise RuntimeError(msg)

    state.stage = stage_utils.open_stage(state.stage_path)
    logger.info("Renamed %s -> %s", old_path, new_path)
    return {
        "old_path": old_path,
        "new_path": new_path,
        "message": f"Renamed {old_path} -> {new_path}",
    }


def remove_prim(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove an object from the scene by prim path."""
    prim_path = params["prim_path"]
    success = stage_utils.remove_prim(state.stage, prim_path)
    if not success:
        msg = f"Failed to remove {prim_path}"
        raise RuntimeError(msg)

    state.object_count = max(0, state.object_count - 1)
    state.touch_project()
    logger.info("Removed %s", prim_path)
    return {
        "prim_path": prim_path,
        "message": f"Removed {prim_path}",
    }


def move_asset(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Move an existing prim to a new position/rotation."""
    prim_path = params["prim_path"]
    tx = float(params["translate_x"])
    ty = float(params["translate_y"])
    tz = float(params["translate_z"])
    ry = float(params.get("rotate_y", 0.0))

    stage_utils.set_transform(
        state.stage, prim_path,
        translate=(tx, ty, tz), rotate=(0.0, ry, 0.0),
    )
    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Moved %s to (%s, %s, %s)", prim_path, tx, ty, tz)
    return {
        "prim_path": prim_path,
        "position": {"x": tx, "y": ty, "z": tz},
        "rotation_y": ry,
        "message": f"Moved {prim_path} to ({tx}, {ty}, {tz})",
    }


def list_prim_children(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List geometry parts under a prim path."""
    prim_path = params["prim_path"]
    children = stage_utils.list_prim_children(state.stage, prim_path)
    if not children:
        return {
            "prim_path": prim_path,
            "part_count": 0,
            "parts": [],
            "message": f"No geometry parts found under {prim_path}.",
        }
    return {
        "prim_path": prim_path,
        "part_count": len(children),
        "parts": children,
        "message": (
            f"Found {len(children)} geometry part(s) under {prim_path}. "
            "Use the prim_path of a specific part with bind_material."
        ),
    }


def compute_grid_layout(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Compute evenly spaced positions for N objects in a grid."""
    count = int(params["count"])
    spacing = float(params.get("spacing", 2.0))

    placements = geometry_utils.suggest_grid_layout(
        count,
        spacing=spacing,
        room_bounds=state.scene_defaults.default_room_bounds,
    )
    positions = [
        {"x": round(p[0], 2), "z": round(p[2], 2)} for p in placements
    ]
    return {
        "count": count,
        "spacing": spacing,
        "positions": positions,
        "message": f"Computed {count} positions in grid with {spacing}m spacing.",
    }
