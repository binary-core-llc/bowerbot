# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage service — orchestrates scene-level operations for the stage tools."""

from __future__ import annotations

import logging
from typing import Any

from pxr import Sdf

from bowerbot.schemas import LayoutDefaults, PositionMode, SceneNamespace
from bowerbot.state import SceneState
from bowerbot.utils import (
    assets,
    inspection_utils,
    stage_utils,
    texture_utils,
)
from bowerbot.utils.core import attributes, instancers
from bowerbot.utils.core.asset_folder import (
    nested_container_path,
    parse_nested_contents_path,
    resolve_asset_dir_for_prim,
)
from bowerbot.utils.core.integrity import (
    clear_scene_prim,
    composed_prim_paths,
    drop_refs_to_vanished,
    remove_empty_groups,
    remove_scene_prim,
    rewrite_refs,
)
from bowerbot.utils.core.metrics import axis_index
from bowerbot.utils.core.naming import clean_prim_path, safe_file_name
from bowerbot.utils.core.references import (
    enclosing_placement,
    newly_unused,
    placement_of,
    unreferenced_assets,
    unused_assets_note,
    unused_files_note,
    unused_scene_textures,
)
from bowerbot.utils.core.transforms import (
    asset_axes_rotation,
    read_translate_rotate,
    resolve_position_in_asset,
    scene_axes_rotation,
    scene_correction,
    set_transform,
    world_position,
)
from bowerbot.utils.core.values import read_axes, unpack_vec3
from bowerbot.utils.layout_utils import suggest_grid_layout

logger = logging.getLogger(__name__)


def create_stage(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create or reopen the project's scene file."""
    project = state.require_project()

    safe_name = safe_file_name(params.get("filename", "")) or "scene"
    logger.debug("create_stage filename=%s", safe_name)

    state.stage_path = project.scene_path
    if state.stage_path.exists():
        state.stage = stage_utils.open_stage(state.stage_path)
        state.object_count = len(inspection_utils.list_prims(state.stage))
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
    state.stage = stage_utils.create_stage(
        state.stage_path,
        up_axis=project.meta.up_axis.value,
        meters_per_unit=project.meta.meters_per_unit,
    )
    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Created stage: %s", state.stage_path)
    return {
        "stage_path": str(state.stage_path),
        "message": (
            f"Stage created at {state.stage_path} with an empty /Scene root prim."
        ),
    }


def list_scene(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List the scene contents: every managed object, each tagged with its kind."""
    stage = state.require_stage()
    del params
    objects = inspection_utils.list_prims(stage)
    return {
        "object_count": len(objects),
        "objects": objects,
        "message": f"Scene has {len(objects)} object(s).",
    }


def rename_prim(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Move/rename a prim, rewriting every rel target across the scene."""
    stage = state.require_stage()
    old_path = params["old_path"]
    new_path = clean_prim_path(params["new_path"], "New path")
    root = SceneNamespace.ROOT
    if old_path == root:
        msg = f"{root} is the scene's root; rename the prims under it instead."
        raise ValueError(msg)
    if not new_path.startswith(f"{root}/"):
        msg = f"{new_path} is outside {root}; renamed prims must stay in the scene."
        raise ValueError(msg)
    if stage.GetPrimAtPath(new_path).IsValid():
        msg = f"Cannot rename {old_path} to {new_path}: a prim already exists there."
        raise ValueError(msg)
    if Sdf.Path(new_path).HasPrefix(Sdf.Path(old_path)):
        msg = f"Cannot move {old_path} inside itself ({new_path})."
        raise ValueError(msg)

    owner = instancers.prototype_owner(stage, old_path) or instancers.prototypes_below(
        stage, old_path,
    )
    if owner is not None and not Sdf.Path(new_path).HasPrefix(Sdf.Path(owner)):
        msg = (
            f"Cannot move {old_path} out of the scatter {owner}: its prototypes stay "
            f"inside it (outside, a prototype also draws on its own). Rename it in place."
        )
        raise ValueError(msg)

    if parse_nested_contents_path(old_path) is not None:
        msg = (
            f"Cannot rename {old_path}: it lives inside a referenced "
            "asset's contents.usda. Renaming at scene level would "
            "create a per-instance override. Edit the asset folder "
            "directly if you really need to rename a nested prim."
        )
        raise ValueError(msg)

    success = stage_utils.rename_prim(stage, old_path, new_path)
    if not success:
        msg = f"Failed to rename {old_path} to {new_path}"
        raise RuntimeError(msg)

    stage = state.reopen_stage()
    rewrites = rewrite_refs(
        stage, {old_path: new_path},
    )
    remove_empty_groups(stage, str(Sdf.Path(old_path).GetParentPath()))
    stage_utils.save_stage(stage)
    logger.info("Renamed %s -> %s", old_path, new_path)
    return {
        "old_path": old_path,
        "new_path": new_path,
        "rewritten_refs": rewrites,
        "message": f"Renamed {old_path} -> {new_path}",
    }


def remove_prim(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove an object from the scene, scrubbing every rel that targeted it."""
    stage = state.require_stage()
    prim_path = params["prim_path"]
    project = state.require_project()
    project_dir = project.path
    unused_before = unused_scene_textures(project_dir)
    assets_before = unreferenced_assets(project_dir, project.assets_dir)

    nested = parse_nested_contents_path(prim_path)
    if nested is not None:
        container_dir, _ = resolve_asset_dir_for_prim(stage, nested_container_path(prim_path))
        if container_dir is None:
            msg = f"Failed to resolve container for nested prim {prim_path}"
            raise RuntimeError(msg)
        group, prim_name = nested
        before = composed_prim_paths(stage)
        success = assets.nested.remove_nested_asset_reference(
            container_dir, group, prim_name,
        )
        if not success:
            msg = f"Failed to remove nested {prim_path}"
            raise RuntimeError(msg)
        scrubbed = drop_refs_to_vanished(state.reopen_stage(), before)
        message = f"Removed {prim_path}"
    elif prim_path == SceneNamespace.ROOT:
        scrubbed = clear_scene_prim(stage, prim_path)
        message = f"Cleared {prim_path}: everything under it was removed; the scene root stays"
    elif instancers.prototype_owner(stage, prim_path) is not None:
        result = instancers.remove_prototype(stage, prim_path)
        scrubbed = {"rels_touched": result["rels_touched"]}
        message = (
            f"Removed {result['scatter']}: {prim_path} was its only prototype"
            if result["removed_scatter"] else
            f"Removed the prototype {prim_path} and its {result['removed_instances']} "
            f"piece(s) from {result['scatter']}; the other pieces stay"
        )
    elif (owner := instancers.prototypes_below(stage, prim_path)) is not None:
        msg = (
            f"{prim_path} holds the prototypes of the scatter {owner}. Remove the "
            f"scatter ({owner}), or one prototype and its pieces."
        )
        raise ValueError(msg)
    else:
        scrubbed = remove_scene_prim(stage, prim_path)
        message = f"Removed {prim_path}"

    state.touch_project()
    unused = newly_unused(project_dir, unused_before, unused_scene_textures(project_dir))
    unused_assets = sorted(unreferenced_assets(project_dir, project.assets_dir) - assets_before)
    logger.info("Removed %s", prim_path)
    return {
        "prim_path": prim_path,
        "scrubbed_dangling_refs": scrubbed,
        "unused_files": unused,
        "unused_assets": unused_assets,
        "message": message + "." + unused_files_note(unused) + unused_assets_note(unused_assets),
    }


def move_asset(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Move an existing prim. Axes omitted from params keep their current value."""
    stage = state.require_stage()
    prim_path = params["prim_path"]
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")
    if enclosing_placement(stage, prim_path) is not None:
        prim_path = placement_of(stage, prim_path)
        prim = stage.GetPrimAtPath(prim_path)
    instancers.require_not_prototype(stage, prim_path)
    current_translate, current_rotate = read_translate_rotate(prim)

    nested = parse_nested_contents_path(prim_path)
    if nested is not None:
        container_path = nested_container_path(prim_path)
        container_dir, _ = resolve_asset_dir_for_prim(stage, container_path)
        if container_dir is None:
            msg = f"Failed to resolve container for nested prim {prim_path}"
            raise RuntimeError(msg)
        group, prim_name = nested
        correction = scene_correction(stage, container_dir)
        rotate = unpack_vec3(
            params, "rotate_x", "rotate_y", "rotate_z",
            scene_axes_rotation(current_rotate, correction),
        ) or scene_axes_rotation(current_rotate, correction)
        local = resolve_position_in_asset(
            stage, container_path, container_dir,
            PositionMode.ABSOLUTE,
            read_axes(params, "translate_x", "translate_y", "translate_z"),
            current_world=world_position(prim),
        )
        success = assets.nested.update_nested_asset_transform(
            container_dir, group, prim_name,
            translate=local,
            rotate=asset_axes_rotation(rotate, correction),
        )
        if not success:
            msg = f"Failed to update nested transform for {prim_path}"
            raise RuntimeError(msg)
        stage = state.reopen_stage()
    else:
        rotate = unpack_vec3(
            params, "rotate_x", "rotate_y", "rotate_z", current_rotate,
        ) or current_rotate
        translate = unpack_vec3(
            params, "translate_x", "translate_y", "translate_z", current_translate,
        ) or current_translate
        set_transform(stage, prim_path, translate=translate, rotate=rotate)
        stage_utils.save_stage(stage)

    state.touch_project()
    x, y, z = (round(v, 4) for v in world_position(stage.GetPrimAtPath(prim_path)))
    logger.info("Moved %s to (%s, %s, %s)", prim_path, x, y, z)
    return {
        "prim_path": prim_path,
        "position": {"x": x, "y": y, "z": z},
        "rotation": dict(zip("xyz", rotate, strict=True)),
        "message": f"Moved {prim_path} to ({x}, {y}, {z})",
    }


def list_prim_attributes(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """List every attribute on a prim with type + current value + authored flag."""
    stage = state.require_stage()
    prim_path = params["prim_path"]
    prim_attributes = attributes.list_prim_attributes(stage, prim_path)
    return {
        "prim_path": prim_path,
        "attributes": prim_attributes,
        "message": (
            f"{len(prim_attributes)} attribute(s) on {prim_path}."
        ),
    }


def set_prim_attribute(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author or clear an attribute opinion on a prim, in scene.usda.

    A texture file is copied into the project's ``textures/`` first. A value
    on one network of a BowerBot hybrid material goes to its twin input too.
    """
    stage = state.require_stage()
    stage_path = state.require_stage_path()
    prim_path = params["prim_path"]
    attribute_name = params["attribute_name"]
    value = params.get("value")

    project_dir = state.require_project().path
    unused_before = unused_scene_textures(project_dir)
    twin = attributes.twin_shader_input(stage, prim_path, attribute_name)
    targets = [(prim_path, attribute_name), *([twin] if twin else [])]
    for path, name in targets:
        attributes.check_attribute_value(stage, path, name, value)
        instancers.check_instancer_value(stage, path, name, value)
    asset_typed = attributes.attribute_type(stage, prim_path, attribute_name)
    if isinstance(value, str) and asset_typed == Sdf.ValueTypeNames.Asset:
        value = texture_utils.stage_asset_value(value, project_dir, state.library_dir)
    for path, name in targets:
        attributes.set_prim_attribute(stage, path, name, value)
    stage_utils.save_stage(stage)
    state.touch_project()
    unused = newly_unused(project_dir, unused_before, unused_scene_textures(project_dir))
    action = "Cleared" if value is None else "Authored"
    logger.info(
        "%s %s.%s in %s", action, prim_path, attribute_name, stage_path,
    )
    also = f" and its twin {twin[0]}.{twin[1]}" if twin else ""
    return {
        "prim_path": prim_path,
        "attribute_name": attribute_name,
        "value": value,
        "twin": {"prim_path": twin[0], "attribute_name": twin[1]} if twin else None,
        "unused_files": unused,
        "message": (
            f"{action} {prim_path}.{attribute_name}{also} in "
            f"{stage_path.name}." + unused_files_note(unused)
        ),
    }


def save_scene_snapshot(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Flatten the composed scene into a named, self-contained snapshot file."""
    stage = state.require_stage()
    stage_path = state.require_stage_path()
    name = params["name"]
    force = bool(params.get("force", False))
    stage.Save()
    snapshot_path = stage_utils.save_scene_snapshot(
        stage_path, name, force=force,
    )
    state.touch_project()
    return {
        "scene_path": str(stage_path),
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
    stage_path = state.require_stage_path()
    del params
    snapshots = stage_utils.list_scene_snapshots(stage_path)
    return {
        "scene_path": str(stage_path),
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
        "message": f"Found {len(snapshots)} snapshot(s) alongside scene.usda.",
    }


def delete_scene_snapshot(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Delete a named snapshot file, reporting textures and assets only it used."""
    stage_path = state.require_stage_path()
    project = state.require_project()
    name = params["name"]
    unused_before = unused_scene_textures(project.path)
    assets_before = unreferenced_assets(project.path, project.assets_dir)
    removed = stage_utils.delete_scene_snapshot(stage_path, name)
    state.touch_project()
    unused = newly_unused(project.path, unused_before, unused_scene_textures(project.path))
    unused_assets = sorted(unreferenced_assets(project.path, project.assets_dir) - assets_before)
    return {
        "snapshot_path": str(removed),
        "snapshot_name": removed.stem,
        "unused_files": unused,
        "unused_assets": unused_assets,
        "message": (
            f"Deleted snapshot {removed.name}." + unused_files_note(unused)
            + unused_assets_note(unused_assets)
        ),
    }


def list_prim_children(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List geometry parts under a prim path."""
    stage = state.require_stage()
    prim_path = params["prim_path"]
    children = stage_utils.list_prim_children(stage, prim_path)
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
    """Compute evenly spaced positions for N objects on the scene's ground plane."""
    count = int(params["count"])
    units_per_meter = 1.0 / state.meters_per_unit if state.meters_per_unit > 0 else 1.0
    spacing = float(params.get("spacing", LayoutDefaults.GRID_SPACING_METERS * units_per_meter))

    placements = suggest_grid_layout(
        count,
        spacing=spacing,
        width=LayoutDefaults.ROOM_WIDTH_METERS * units_per_meter,
        depth=LayoutDefaults.ROOM_DEPTH_METERS * units_per_meter,
        up=axis_index(state.up_axis.value),
    )
    positions = [
        {"x": round(x, 4), "y": round(y, 4), "z": round(z, 4)} for x, y, z in placements
    ]
    return {
        "count": count,
        "spacing": spacing,
        "up_axis": state.up_axis.value,
        "positions": positions,
        "message": (
            f"Computed {count} positions on the ground plane ({state.up_axis.value}-up), "
            f"{spacing} scene units apart."
        ),
    }
