# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage service — orchestrates scene-level operations for the stage tools."""

from __future__ import annotations

import logging
from typing import Any

from bowerbot.state import SceneState
from bowerbot.utils import (
    asset_intake_utils,
    geometry_utils,
    scene_integrity_utils,
    stage_utils,
)
from bowerbot.utils.asset_folder_utils import resolve_asset_dir_for_prim
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
    """Return every placement, light, and physics-infrastructure prim in the scene."""
    del params
    objects = stage_utils.list_prims(state.stage)
    return {
        "object_count": len(objects),
        "objects": objects,
        "message": f"Scene has {len(objects)} object(s).",
    }


def rename_prim(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Move/rename a prim, rewriting every rel target across the scene."""
    old_path = params["old_path"]
    new_path = params["new_path"]

    if _parse_nested_contents_path(old_path) is not None:
        msg = (
            f"Cannot rename {old_path}: it lives inside a referenced "
            "asset's contents.usda. Renaming at scene level would "
            "create a per-instance override. Edit the asset folder "
            "directly if you really need to rename a nested prim."
        )
        raise ValueError(msg)

    success = stage_utils.rename_prim(state.stage, old_path, new_path)
    if not success:
        msg = f"Failed to rename {old_path} to {new_path}"
        raise RuntimeError(msg)

    state.stage = stage_utils.open_stage(state.stage_path)
    rewrites = scene_integrity_utils.rewrite_refs(
        state.stage, {old_path: new_path},
    )
    logger.info("Renamed %s -> %s", old_path, new_path)
    return {
        "old_path": old_path,
        "new_path": new_path,
        "rewritten_refs": rewrites,
        "message": f"Renamed {old_path} -> {new_path}",
    }


def remove_prim(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove an object from the scene, scrubbing every rel that targeted it."""
    prim_path = params["prim_path"]

    nested = _parse_nested_contents_path(prim_path)
    if nested is not None:
        container_dir, _ = resolve_asset_dir_for_prim(state.stage, prim_path)
        if container_dir is None:
            msg = f"Failed to resolve container for nested prim {prim_path}"
            raise RuntimeError(msg)
        group, prim_name = nested
        success = asset_intake_utils.remove_nested_asset_reference(
            container_dir, group, prim_name,
        )
        if not success:
            msg = f"Failed to remove nested {prim_path}"
            raise RuntimeError(msg)
        state.stage = stage_utils.open_stage(state.stage_path)
    else:
        success = stage_utils.remove_prim(state.stage, prim_path)
        if not success:
            msg = f"Failed to remove {prim_path}"
            raise RuntimeError(msg)

    scrubbed = scene_integrity_utils.scrub_dangling_refs(state.stage)

    state.object_count = max(0, state.object_count - 1)
    state.touch_project()
    logger.info("Removed %s", prim_path)
    return {
        "prim_path": prim_path,
        "scrubbed_dangling_refs": scrubbed,
        "message": f"Removed {prim_path}",
    }


def _parse_nested_contents_path(prim_path: str) -> tuple[str, str] | None:
    """If *prim_path* is a nested-asset wrapper, return (group, prim_name)."""
    marker = "/asset/contents/"
    idx = prim_path.find(marker)
    if idx >= 0:
        suffix = prim_path[idx + len(marker):]
        parts = [p for p in suffix.split("/") if p]
        if len(parts) == 2:
            return parts[0], parts[1]
        msg = (
            f"Path {prim_path} is inside a nested asset's contents but "
            f"not at the wrapper level. Only the wrapper "
            f"(.../asset/contents/<group>/<name>) can be edited; deeper "
            f"prims live inside the referenced nested asset and editing "
            f"them at scene level would create per-instance overrides."
        )
        raise ValueError(msg)

    if "/asset/" in prim_path or prim_path.endswith("/asset"):
        msg = (
            f"Path {prim_path} is inside a referenced top-level asset. "
            f"Only the scene-level wrapper (/Scene/<Group>/<Name>) and "
            f"nested wrappers (.../asset/contents/<group>/<name>) can be "
            f"edited; everything else lives inside the referenced asset "
            f"and editing it at scene level would create per-instance "
            f"overrides."
        )
        raise ValueError(msg)

    return None


def move_asset(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Move an existing prim. Axes omitted from params keep their current value."""
    prim_path = params["prim_path"]
    prim = state.stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")

    cur_tx, cur_ty, cur_tz, cur_ry = stage_utils.read_translate_and_rotate_y(prim)
    tx = float(params["translate_x"]) if params.get("translate_x") is not None else cur_tx
    ty = float(params["translate_y"]) if params.get("translate_y") is not None else cur_ty
    tz = float(params["translate_z"]) if params.get("translate_z") is not None else cur_tz
    ry = float(params["rotate_y"]) if params.get("rotate_y") is not None else cur_ry

    nested = _parse_nested_contents_path(prim_path)
    if nested is not None:
        container_dir, _ = resolve_asset_dir_for_prim(state.stage, prim_path)
        if container_dir is None:
            msg = f"Failed to resolve container for nested prim {prim_path}"
            raise RuntimeError(msg)
        group, prim_name = nested

        container_prim_path = prim_path.split("/asset/contents/")[0]
        local = stage_utils.world_to_local_point(
            state.stage, container_prim_path, tx, ty, tz,
        )
        if local is None:
            msg = f"Failed to compute world-to-local for {container_prim_path}"
            raise RuntimeError(msg)

        success = asset_intake_utils.update_nested_asset_transform(
            container_dir, group, prim_name,
            translate=local,
            rotate=(0.0, ry, 0.0),
        )
        if not success:
            msg = f"Failed to update nested transform for {prim_path}"
            raise RuntimeError(msg)
        state.stage = stage_utils.open_stage(state.stage_path)
    else:
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


def list_prim_attributes(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """List every attribute on a prim with type + current value + authored flag."""
    prim_path = params["prim_path"]
    attributes = stage_utils.list_prim_attributes(state.stage, prim_path)
    return {
        "prim_path": prim_path,
        "attributes": attributes,
        "message": (
            f"{len(attributes)} attribute(s) on {prim_path}."
        ),
    }


def set_prim_attribute(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author or clear an attribute opinion on a prim, in scene.usda."""
    prim_path = params["prim_path"]
    attribute_name = params["attribute_name"]
    value = params.get("value")

    stage_utils.set_prim_attribute(
        state.stage, prim_path, attribute_name, value,
    )
    stage_utils.save_stage(state.stage)
    state.touch_project()
    action = "Cleared" if value is None else "Authored"
    logger.info(
        "%s %s.%s in %s", action, prim_path, attribute_name, state.stage_path,
    )
    return {
        "prim_path": prim_path,
        "attribute_name": attribute_name,
        "value": value,
        "message": (
            f"{action} {prim_path}.{attribute_name} in "
            f"{state.stage_path.name}."
        ),
    }


def save_scene_snapshot(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Flatten the composed scene into a named, self-contained snapshot file."""
    if state.stage_path is None:
        raise ValueError("No scene is open.")
    name = params["name"]
    force = bool(params.get("force", False))
    state.stage.Save()
    snapshot_path = stage_utils.save_scene_snapshot(
        state.stage_path, name, force=force,
    )
    state.touch_project()
    return {
        "scene_path": str(state.stage_path),
        "snapshot_path": str(snapshot_path),
        "snapshot_name": snapshot_path.stem,
        "message": (
            f"Saved snapshot '{snapshot_path.stem}' to {snapshot_path.name}. "
            "scene.usda is unchanged; the snapshot is a self-contained "
            "frozen copy."
        ),
    }


def list_scene_snapshots(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every snapshot .usda file alongside scene.usda."""
    del params
    if state.stage_path is None:
        raise ValueError("No scene is open.")
    snapshots = stage_utils.list_scene_snapshots(state.stage_path)
    return {
        "scene_path": str(state.stage_path),
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
        "message": f"Found {len(snapshots)} snapshot(s) alongside scene.usda.",
    }


def delete_scene_snapshot(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Delete a named snapshot file."""
    if state.stage_path is None:
        raise ValueError("No scene is open.")
    name = params["name"]
    removed = stage_utils.delete_scene_snapshot(state.stage_path, name)
    state.touch_project()
    return {
        "snapshot_path": str(removed),
        "snapshot_name": removed.stem,
        "message": f"Deleted snapshot {removed.name}",
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
