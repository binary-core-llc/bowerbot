# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage service — orchestrates scene-level operations for the stage tools."""

from __future__ import annotations

import logging
from typing import Any

from bowerbot import scene_state
from bowerbot.utils import authoring
from bowerbot.utils import inspection
from bowerbot.utils import layout
from bowerbot.utils import usd

logger = logging.getLogger(__name__)


def create_stage(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create or reopen the project's scene file."""
    if state.project is None:
        msg = "No project open."
        raise RuntimeError(msg)

    safe_name = authoring.naming.safe_file_name(params["filename"]) or "scene"
    logger.debug("create_stage filename=%s", safe_name)

    state.stage_path = state.project.scene_path
    if state.stage_path.exists():
        state.stage = authoring.stage.open_stage(state.stage_path)
        state.object_count = len(inspection.scene.list_prims(state.stage))
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
    state.stage = authoring.stage.create_stage(
        state.stage_path,
        up_axis=state.up_axis.value, meters_per_unit=state.meters_per_unit,
    )
    authoring.stage.save_stage(state.stage)
    state.touch_project()

    logger.info("Created stage: %s", state.stage_path)
    return {
        "stage_path": str(state.stage_path),
        "message": (
            f"Stage created at {state.stage_path} with an empty /Scene root prim."
        ),
    }


def list_scene(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List the scene contents: every managed object, each tagged with its kind."""
    del params
    objects = inspection.scene.list_prims(state.stage)
    return {
        "object_count": len(objects),
        "objects": objects,
        "message": f"Scene has {len(objects)} object(s).",
    }


def rename_prim(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Move/rename a prim, rewriting every rel target across the scene."""
    old_path = params["old_path"]
    new_path = params["new_path"]

    if authoring.placement.parse_nested_contents_path(old_path) is not None:
        msg = (
            f"Cannot rename {old_path}: it lives inside a referenced "
            "asset's contents.usda. Renaming at scene level would "
            "create a per-instance override. Edit the asset folder "
            "directly if you really need to rename a nested prim."
        )
        raise ValueError(msg)

    success = usd.namespace.rename_prim(state.stage, old_path, new_path)
    if not success:
        msg = f"Failed to rename {old_path} to {new_path}"
        raise RuntimeError(msg)

    state.stage = authoring.stage.open_stage(state.stage_path)
    rewrites = usd.namespace.rewrite_refs(
        state.stage, {old_path: new_path},
    )
    logger.info("Renamed %s -> %s", old_path, new_path)
    return {
        "old_path": old_path,
        "new_path": new_path,
        "rewritten_refs": rewrites,
        "message": f"Renamed {old_path} -> {new_path}",
    }


def remove_prim(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove an object from the scene, scrubbing every rel that targeted it."""
    prim_path = params["prim_path"]

    nested = authoring.placement.parse_nested_contents_path(prim_path)
    if nested is not None:
        container_dir, _ = authoring.placement.resolve_asset_dir_for_prim(state.stage, prim_path)
        if container_dir is None:
            msg = f"Failed to resolve container for nested prim {prim_path}"
            raise RuntimeError(msg)
        group, prim_name = nested
        success = authoring.placement.remove_nested_asset_reference(
            container_dir, group, prim_name,
        )
        if not success:
            msg = f"Failed to remove nested {prim_path}"
            raise RuntimeError(msg)
        state.stage = authoring.stage.open_stage(state.stage_path)
    else:
        success = usd.namespace.remove_prim(state.stage, prim_path)
        if not success:
            msg = f"Failed to remove {prim_path}"
            raise RuntimeError(msg)

    scrubbed = usd.namespace.scrub_dangling_refs(state.stage)

    state.object_count = max(0, state.object_count - 1)
    state.touch_project()
    logger.info("Removed %s", prim_path)
    return {
        "prim_path": prim_path,
        "scrubbed_dangling_refs": scrubbed,
        "message": f"Removed {prim_path}",
    }


def move_asset(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Move an existing prim. Axes omitted from params keep their current value."""
    prim_path = params["prim_path"]
    prim = state.stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")

    cur_tx, cur_ty, cur_tz, cur_ry = usd.transforms.read_translate_and_rotate_y(prim)
    tx = float(params["translate_x"]) if params.get("translate_x") is not None else cur_tx
    ty = float(params["translate_y"]) if params.get("translate_y") is not None else cur_ty
    tz = float(params["translate_z"]) if params.get("translate_z") is not None else cur_tz
    ry = float(params["rotate_y"]) if params.get("rotate_y") is not None else cur_ry

    nested = authoring.placement.parse_nested_contents_path(prim_path)
    if nested is not None:
        container_dir, _ = authoring.placement.resolve_asset_dir_for_prim(state.stage, prim_path)
        if container_dir is None:
            msg = f"Failed to resolve container for nested prim {prim_path}"
            raise RuntimeError(msg)
        group, prim_name = nested

        container_prim_path = prim_path.split("/asset/contents/")[0]
        local = authoring.placement.world_to_local_point(
            state.stage, container_prim_path, tx, ty, tz,
        )
        if local is None:
            msg = f"Failed to compute world-to-local for {container_prim_path}"
            raise RuntimeError(msg)

        success = authoring.placement.update_nested_asset_transform(
            container_dir, group, prim_name,
            translate=local,
            rotate=(0.0, ry, 0.0),
            project_mpu=state.meters_per_unit,
        )
        if not success:
            msg = f"Failed to update nested transform for {prim_path}"
            raise RuntimeError(msg)
        state.stage = authoring.stage.open_stage(state.stage_path)
    else:
        usd.transforms.set_transform(
            state.stage, prim_path,
            translate=(tx, ty, tz), rotate=(0.0, ry, 0.0),
        )
        authoring.stage.save_stage(state.stage)

    state.touch_project()

    logger.info("Moved %s to (%s, %s, %s)", prim_path, tx, ty, tz)
    return {
        "prim_path": prim_path,
        "position": {"x": tx, "y": ty, "z": tz},
        "rotation_y": ry,
        "message": f"Moved {prim_path} to ({tx}, {ty}, {tz})",
    }


def list_prim_attributes(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """List every attribute on a prim with type + current value + authored flag."""
    prim_path = params["prim_path"]
    attributes = usd.attributes.list_prim_attributes(state.stage, prim_path)
    return {
        "prim_path": prim_path,
        "attributes": attributes,
        "message": (
            f"{len(attributes)} attribute(s) on {prim_path}."
        ),
    }


def set_prim_attribute(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author or clear an attribute opinion on a prim, in scene.usda."""
    prim_path = params["prim_path"]
    attribute_name = params["attribute_name"]
    value = params.get("value")

    usd.attributes.set_prim_attribute(
        state.stage, prim_path, attribute_name, value,
    )
    authoring.stage.save_stage(state.stage)
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


def save_scene_snapshot(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Flatten the composed scene into a named, self-contained snapshot file."""
    if state.stage_path is None:
        raise ValueError("No scene is open.")
    name = params["name"]
    force = bool(params.get("force", False))
    state.stage.Save()
    snapshot_path = authoring.stage.save_scene_snapshot(
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


def list_scene_snapshots(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every snapshot .usda file alongside scene.usda."""
    del params
    if state.stage_path is None:
        raise ValueError("No scene is open.")
    snapshots = authoring.stage.list_scene_snapshots(state.stage_path)
    return {
        "scene_path": str(state.stage_path),
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
        "message": f"Found {len(snapshots)} snapshot(s) alongside scene.usda.",
    }


def delete_scene_snapshot(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Delete a named snapshot file."""
    if state.stage_path is None:
        raise ValueError("No scene is open.")
    name = params["name"]
    removed = authoring.stage.delete_scene_snapshot(state.stage_path, name)
    state.touch_project()
    return {
        "snapshot_path": str(removed),
        "snapshot_name": removed.stem,
        "message": f"Deleted snapshot {removed.name}",
    }


def list_prim_children(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List geometry parts under a prim path."""
    prim_path = params["prim_path"]
    children = inspection.parts.list_bindable_parts(state.stage, prim_path)
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


def compute_grid_layout(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Compute evenly spaced positions for N objects in a grid."""
    count = int(params["count"])
    spacing = float(params.get("spacing", 2.0))

    placements = layout.grid.suggest(
        count,
        spacing=spacing,
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
