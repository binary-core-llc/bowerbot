# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage service — orchestrates scene-level operations for the stage tools."""

from __future__ import annotations

import logging
from typing import Any

from bowerbot import constants
from bowerbot import scene_state
from bowerbot import schemas
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

    if authoring.placement.parse_added_asset_path(old_path) is not None:
        msg = (
            f"Cannot rename {old_path}: it is an asset added to another "
            "asset, kept in that asset's contents.usda. Renaming at scene "
            "level would create a per-instance override. Edit the asset "
            "folder directly if you really need to rename it."
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

    added = authoring.placement.parse_added_asset_path(prim_path)
    if added is not None:
        parent_asset_dir, _ = authoring.placement.resolve_asset_dir_for_prim(state.stage, prim_path)
        if parent_asset_dir is None:
            msg = f"Failed to resolve the parent asset of {prim_path}"
            raise RuntimeError(msg)
        group, prim_name = added
        success = authoring.placement.remove_added_asset(
            parent_asset_dir, group, prim_name,
        )
        if not success:
            msg = f"Failed to remove {prim_path}"
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

    added = authoring.placement.parse_added_asset_path(prim_path)
    up_axis = state.up_axis.value
    cur_tx, cur_ty, cur_tz, cur_turn = usd.transforms.read_translate_and_turn(prim, up_axis)
    if added is not None:
        # An added asset's translate is in its parent asset's frame; axes left out keep
        # where it is in the world.
        cur_tx, cur_ty, cur_tz = usd.transforms.world_translation(prim)
    tx, ty, tz = usd.values.fill_vec3(
        usd.values.unpack_vec3(params, "translate_x", "translate_y", "translate_z"),
        (cur_tx, cur_ty, cur_tz),
    )
    # Without rotate_up the prim keeps the whole rotation it has.
    turn = float(params["rotate_up"]) if params.get("rotate_up") is not None else None

    if added is not None:
        parent_asset_dir, ref_prim_path = authoring.placement.resolve_asset_dir_for_prim(
            state.stage, prim_path,
        )
        if parent_asset_dir is None or ref_prim_path is None:
            msg = f"Failed to resolve the parent asset of {prim_path}"
            raise RuntimeError(msg)
        group, prim_name = added

        world_to_local_mat = authoring.placement.world_to_frame_matrix(
            state.stage, ref_prim_path,
        )
        if world_to_local_mat is None:
            msg = f"Failed to compute world-to-local for {ref_prim_path}"
            raise RuntimeError(msg)
        local = authoring.placement.resolve_asset_position(
            schemas.PositionMode.ABSOLUTE, (tx, ty, tz),
            asset_dir=parent_asset_dir,
            world_to_local_mat=world_to_local_mat,
            up_given=True,
            project_mpu=state.meters_per_unit,
            project_up_axis=state.up_axis.value,
        )

        _, parent_up_axis = authoring.asset_folder.asset_metrics(
            parent_asset_dir,
            project_mpu=state.meters_per_unit, project_up_axis=up_axis,
        )
        success = authoring.placement.move_added_asset(
            parent_asset_dir, group, prim_name,
            translate=local,
            rotate=None if turn is None else usd.transforms.up_turn(turn, parent_up_axis),
        )
        if not success:
            msg = f"Failed to update the transform of {prim_path}"
            raise RuntimeError(msg)
        state.stage = authoring.stage.open_stage(state.stage_path)
        tx, ty, tz = (
            round(v, 4) + 0.0
            for v in usd.transforms.world_translation(state.stage.GetPrimAtPath(prim_path))
        )
    else:
        usd.transforms.set_xform(
            prim,
            translate=(tx, ty, tz),
            rotate=None if turn is None else usd.transforms.up_turn(turn, up_axis),
        )
        authoring.stage.save_stage(state.stage)

    state.touch_project()

    logger.info("Moved %s to (%s, %s, %s)", prim_path, tx, ty, tz)
    return {
        "prim_path": prim_path,
        "position": {"x": tx, "y": ty, "z": tz},
        "rotation_up": cur_turn if turn is None else turn,
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
    """Compute evenly spaced positions for N objects in a grid on the project's floor."""
    count = int(params["count"])
    mpu = state.meters_per_unit
    spacing = float(
        params.get("spacing", constants.PlacementDefaults.GRID_SPACING_METERS / mpu),
    )
    up = usd.metrics.axis_index(state.up_axis.value)

    placements = layout.grid.suggest(
        count,
        spacing=spacing,
        room_size=(
            constants.PlacementDefaults.GRID_ROOM_METERS[0] / mpu,
            constants.PlacementDefaults.GRID_ROOM_METERS[1] / mpu,
        ),
        up=up,
    )
    first, second = usd.metrics.horizontal_axes(up)
    names = "xyz"
    positions = [
        {names[first]: round(p[first], 2), names[second]: round(p[second], 2)}
        for p in placements
    ]
    return {
        "count": count,
        "spacing": spacing,
        "positions": positions,
        "message": (
            f"Computed {count} positions on the {names[first]}-{names[second]} floor "
            f"plane, {spacing} project units apart."
        ),
    }
