# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset service — orchestrates asset intake and placement for the asset tools."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from bowerbot import constants
from bowerbot import scene_state
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import layout
from bowerbot.utils import usd

logger = logging.getLogger(__name__)


# ── place_asset ──


def place_asset(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Bring an asset into the project and add it to the scene."""
    asset_path = authoring.library.resolve_source_file(
        params["asset_file_path"],
        project_dir=state.project_dir,
        library_dir=state.library_dir,
    )
    asset_name = params["asset_name"]
    group = params["group"]
    tx = float(params["translate_x"])
    ty = float(params["translate_y"])
    tz = float(params["translate_z"])
    turn = float(params.get("rotate_up", 0.0))

    safe_asset_name = usd.naming.clean_prim_name(asset_name, "asset name")
    group_path = authoring.placement.scene_group_path(group)
    state.object_count += 1
    prim_path = f"{group_path}/{safe_asset_name}_{state.object_count:02d}"

    assets_dir = state.resolve_assets_dir()
    try:
        report = authoring.intake.prepare_asset(
            asset_path, assets_dir,
            library_dir=state.library_dir,
            project_mpu=state.meters_per_unit,
            project_up_axis=state.up_axis.value,
            fix_root_prim=params.get("fix_root_prim", False),
            fix_root_transforms=params.get("fix_root_transforms", False),
        )
    except (ValueError, RuntimeError):
        state.object_count -= 1
        raise

    scene_object = schemas.SceneObject(
        prim_path=prim_path,
        asset=schemas.AssetMetadata(
            name=asset_name,
            source_skill="local",
            source_id=str(asset_path),
            file_path=report.scene_ref_path,
        ),
        translate=(tx, ty, tz),
        rotate=usd.transforms.up_turn(turn, state.up_axis.value),
    )

    authoring.placement.add_references(
        state.stage, [scene_object],
        project_mpu=state.meters_per_unit, project_up_axis=state.up_axis.value,
    )
    authoring.stage.save_stage(state.stage)
    state.touch_project()

    logger.info("Placed %s at %s (%s, %s, %s)", asset_name, prim_path, tx, ty, tz)
    return {
        "prim_path": prim_path,
        "asset": asset_name,
        "position": {"x": tx, "y": ty, "z": tz},
        "rotation_up": turn,
        "intake": authoring.intake.intake_summary(report),
        "message": authoring.intake.placement_message(asset_name, prim_path, report),
    }


# ── place_layout ──


def place_layout(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Place many assets in one transactional batch from inline entries."""
    raw_entries = params.get("placements")
    if not raw_entries:
        raise ValueError("place_layout needs a non-empty 'placements' list.")

    project_dir = state.project_dir

    valid, problems = layout.entries.validate(raw_entries)

    items: list[dict[str, Any]] = []
    folder_sources: dict[str, Path] = {}
    for idx, entry in valid:
        try:
            asset_path = authoring.library.resolve_source_file(
                entry.asset,
                project_dir=project_dir,
                library_dir=state.library_dir,
            )
            group_path = authoring.placement.scene_group_path(entry.group)
        except ValueError as e:
            problems.append(f"placements[{idx}]: {e}")
            continue
        try:
            base_name = usd.naming.clean_prim_name(entry.name or asset_path.stem, "name")
        except ValueError as e:
            problems.append(f"placements[{idx}]: {e} Set the entry's 'name'.")
            continue
        target = authoring.intake.intake_target_name(
            asset_path, state.library_dir,
        )
        prior = folder_sources.setdefault(target, asset_path)
        if prior != asset_path:
            problems.append(
                f"placements[{idx}]: '{asset_path}' and '{prior}' would both "
                f"stage to assets/{target}; rename one source.",
            )
            continue
        items.append({
            "entry": entry,
            "asset_path": asset_path,
            "group_path": group_path,
            "base_name": base_name,
            "target": target,
            "count": layout.entries.count(entry),
        })

    placed = sum(item["count"] for item in items)
    if placed > constants.PlacementRules.MAX_LAYOUT_PLACEMENTS:
        problems.append(
            f"layout expands to {placed} placements; the maximum per call "
            f"is {constants.PlacementRules.MAX_LAYOUT_PLACEMENTS}.",
        )
    if problems:
        summary = f"layout validation failed ({len(problems)} problem(s)):"
        raise ValueError("\n".join([summary, *problems]))

    by_asset: dict[str, int] = {}
    groups: set[str] = set()
    for item in items:
        by_asset[item["target"]] = by_asset.get(item["target"], 0) + item["count"]
        groups.add(item["group_path"])
    sources = {
        target: str(path) for target, path in folder_sources.items()
    }

    if params.get("validate_only", False):
        return {
            "valid": True,
            "placements": placed,
            "groups": sorted(groups),
            "by_asset": by_asset,
            "sources": sources,
            "message": (
                f"Layout is valid: {placed} placement(s) across "
                f"{len(groups)} group(s). Nothing was placed."
            ),
        }

    assets_dir = state.resolve_assets_dir()
    fix_prim: dict[Path, bool] = {}
    fix_transforms: dict[Path, bool] = {}
    for item in items:
        path = item["asset_path"]
        fix_prim[path] = fix_prim.get(path, False) or item["entry"].fix_root_prim
        fix_transforms[path] = (
            fix_transforms.get(path, False) or item["entry"].fix_root_transforms
        )

    reports: dict[Path, Any] = {}
    intake_problems: list[str] = []
    for path in folder_sources.values():
        try:
            reports[path] = authoring.intake.prepare_asset(
                path, assets_dir,
                library_dir=state.library_dir,
                project_mpu=state.meters_per_unit,
                project_up_axis=state.up_axis.value,
                fix_root_prim=fix_prim[path],
                fix_root_transforms=fix_transforms[path],
            )
        except (ValueError, RuntimeError) as e:
            intake_problems.append(f"{path.name}: {e}")
    if intake_problems:
        summary = f"asset intake failed ({len(intake_problems)} asset(s)):"
        raise ValueError("\n".join([summary, *intake_problems]))

    object_count_snapshot = state.object_count
    try:
        objects: list[schemas.SceneObject] = []
        for item in items:
            report = reports[item["asset_path"]]
            for transform in layout.entries.expand(item["entry"]):
                state.object_count += 1
                prim_path = (
                    f"{item['group_path']}/"
                    f"{item['base_name']}_{state.object_count:02d}"
                )
                objects.append(schemas.SceneObject(
                    prim_path=prim_path,
                    asset=schemas.AssetMetadata(
                        name=item["base_name"],
                        source_skill="local",
                        source_id=str(item["asset_path"]),
                        file_path=report.scene_ref_path,
                    ),
                    translate=transform.translate,
                    rotate=transform.rotate,
                    scale=transform.scale,
                ))
        authoring.placement.add_references(
            state.stage, objects,
            project_mpu=state.meters_per_unit, project_up_axis=state.up_axis.value,
        )
        authoring.stage.save_stage(state.stage)
    except Exception:
        state.object_count = object_count_snapshot
        state.stage.Reload()
        raise
    state.touch_project()

    logger.info(
        "place_layout placed %d asset(s) across %d group(s)", placed, len(groups),
    )
    return {
        "placed": placed,
        "groups": sorted(groups),
        "by_asset": by_asset,
        "sources": sources,
        "message": (
            f"Placed {placed} asset(s) across {len(groups)} group(s) in one call."
        ),
    }


# ── add_asset_to_asset ──


def add_asset_to_asset(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Add an asset to another asset: a reference in the parent's ``contents.usda``."""
    asset_path = authoring.library.resolve_source_file(
        params["asset_file_path"],
        project_dir=state.project_dir,
        library_dir=state.library_dir,
    )
    asset_name = params["asset_name"]
    safe_asset_name = usd.naming.clean_prim_name(asset_name, "asset name")
    parent_prim_path = params["parent_prim_path"]
    group = params["group"]
    tx = float(params["translate_x"])
    ty = float(params["translate_y"])
    tz = float(params["translate_z"])
    turn = float(params.get("rotate_up", 0.0))

    parent_asset_dir, ref_prim_path = authoring.placement.require_asset_context(
        state.stage, parent_prim_path,
    )

    authoring.placement.refuse_shared_modification(
        state.stage, parent_asset_dir,
        confirmed=bool(params.get("confirm_shared_modification", False)),
        op_label="add_asset_to_asset",
        per_instance=(
            "For per-instance placement (different positions per "
            "instance), use 'place_asset' instead; it places the asset "
            "as an independent scene-level prim."
        ),
        shared="the added asset",
    )

    assets_dir = state.resolve_assets_dir()
    report = authoring.intake.prepare_asset(
        asset_path, assets_dir,
        library_dir=state.library_dir,
        project_mpu=state.meters_per_unit,
        project_up_axis=state.up_axis.value,
        fix_root_prim=params.get("fix_root_prim", False),
        fix_root_transforms=params.get("fix_root_transforms", False),
    )

    mode = schemas.PositionMode(
        params.get("position_mode", schemas.PositionMode.ABSOLUTE.value),
    )
    tx, ty, tz = authoring.placement.resolve_asset_position(
        mode, (tx, ty, tz),
        asset_dir=parent_asset_dir,
        world_to_local_mat=authoring.placement.world_to_frame_matrix(
            state.stage, ref_prim_path,
        ),
        up_given=True,
        project_mpu=state.meters_per_unit,
        project_up_axis=state.up_axis.value,
    )

    ref_asset_path = authoring.placement.compute_ref_asset_path(
        report.scene_ref_path, assets_dir, parent_asset_dir,
    )

    _, parent_up_axis = authoring.asset_folder.asset_metrics(
        parent_asset_dir,
        project_mpu=state.meters_per_unit, project_up_axis=state.up_axis.value,
    )
    state.object_count += 1
    prim_name = f"{safe_asset_name}_{state.object_count:02d}"

    try:
        authoring.placement.add_asset_to_parent(
            parent_asset_dir=parent_asset_dir,
            group=group,
            prim_name=prim_name,
            ref_asset_path=ref_asset_path,
            transform=schemas.TransformParams(
                translate=(tx, ty, tz),
                rotate=usd.transforms.up_turn(turn, parent_up_axis),
            ),
            project_mpu=state.meters_per_unit,
            project_up_axis=state.up_axis.value,
        )
    except (ValueError, RuntimeError):
        state.object_count -= 1
        raise

    state.stage = authoring.stage.open_stage(state.stage_path)
    state.touch_project()

    composed_path = authoring.placement.contents_prim_path(ref_prim_path, group, prim_name)
    wx, wy, wz = (
        round(v, 4) + 0.0
        for v in usd.transforms.world_translation(state.stage.GetPrimAtPath(composed_path))
    )
    logger.info(
        "Added %s to %s at %s",
        asset_name, parent_asset_dir.name, composed_path,
    )
    return {
        "prim_path": composed_path,
        "asset": asset_name,
        "parent": parent_asset_dir.name,
        "position": {"x": wx, "y": wy, "z": wz},
        "rotation_up": turn,
        "intake": authoring.intake.intake_summary(report),
        "message": (
            f"Added {asset_name} to {parent_asset_dir.name} at {composed_path}"
        ),
    }


# ── list_project_assets ──


def list_project_assets(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every asset in the project's assets dir, with in-scene flags."""
    assets_dir = state.resolve_assets_dir()
    if not assets_dir.exists():
        return {"assets": [], "message": "No assets directory found."}

    query = (params.get("query") or "").lower()

    results: list[dict[str, Any]] = []
    for entry in sorted(assets_dir.iterdir()):
        if query and query not in entry.name.lower():
            continue
        results.append({
            "name": entry.name,
            "type": "folder" if entry.is_dir() else "file",
            "in_scene": bool(authoring.asset_folder.find_files_using(assets_dir.parent, entry)),
        })

    unused = [a for a in results if not a["in_scene"]]
    return {
        "total": len(results),
        "unused_count": len(unused),
        "assets": results,
        "message": f"Project has {len(results)} asset(s), {len(unused)} unused.",
    }


# ── delete_project_asset ──


def cleanup_unused_contents(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Drop empty ``contents.usda`` layers, per asset or project-wide."""
    asset_prim_path = params.get("asset_prim_path")

    if asset_prim_path:
        asset_dir, _ = authoring.placement.require_asset_context(state.stage, asset_prim_path)

        removed = authoring.placement.cleanup_unused_contents_in_folder(asset_dir)
        state.stage = authoring.stage.open_stage(state.stage_path)
        logger.info(
            "Cleaned %d empty group(s) from %s/contents",
            len(removed), asset_dir.name,
        )
        return {
            "asset_folder": asset_dir.name,
            "removed_count": len(removed),
            "removed": removed,
            "message": (
                f"Cleaned {len(removed)} empty group(s) from "
                f"{asset_dir.name}/contents.usda."
            ),
        }

    assets_dir = state.resolve_assets_dir()
    per_folder: list[dict[str, Any]] = []
    total = 0
    for entry in authoring.asset_folder.folders_with_layer(
        assets_dir, constants.ASWFLayerNames.CONTENTS,
    ):
        removed = authoring.placement.cleanup_unused_contents_in_folder(entry)
        if removed:
            per_folder.append({"asset_folder": entry.name, "removed": removed})
            total += len(removed)

    state.stage = authoring.stage.open_stage(state.stage_path)
    logger.info(
        "Cleaned %d empty group(s) across %d asset folder(s)",
        total, len(per_folder),
    )
    return {
        "total_removed": total,
        "per_folder": per_folder,
        "message": (
            f"Cleaned {total} empty group(s) across "
            f"{len(per_folder)} asset folder(s)."
        ),
    }


# ── freeze_asset ──


def freeze_asset(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Bake project asset root transforms into vertex data (one or all)."""
    assets_dir = state.resolve_assets_dir()
    name = params.get("name")

    if name:
        results = [authoring.intake.freeze_one_asset(assets_dir, name)]
    else:
        results = [
            authoring.intake.freeze_one_asset(assets_dir, entry.name)
            for entry in authoring.asset_folder.folders_with_layer(
                assets_dir, constants.ASWFLayerNames.GEO,
            )
        ]

    state.touch_project()
    if state.stage is not None:
        state.stage = authoring.stage.open_stage(state.stage_path)

    baked_count = sum(1 for r in results if r["baked"])
    logger.info(
        "Froze %d/%d asset(s) in project", baked_count, len(results),
    )
    return {
        "results": results,
        "baked_count": baked_count,
        "total": len(results),
        "message": (
            f"Baked transforms in {baked_count} of {len(results)} asset(s)."
        ),
    }


# ── delete_project_asset ──


def delete_project_asset(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Delete an asset folder/file from the project (only if unreferenced)."""
    name = params["name"]
    assets_dir = state.resolve_assets_dir()
    asset_path = assets_dir / name

    if not asset_path.exists():
        msg = f"Asset not found: {name}"
        raise ValueError(msg)

    referencing = authoring.asset_folder.find_files_using(state.project.path, asset_path)
    if referencing:
        files_list = ", ".join(referencing)
        msg = (
            f"Asset '{name}' is still referenced by: {files_list}. "
            f"Remove those references first."
        )
        raise ValueError(msg)

    if asset_path.is_dir():
        shutil.rmtree(asset_path)
    else:
        asset_path.unlink()
    logger.info("Deleted project asset: %s", asset_path)

    return {
        "name": name,
        "message": f"Deleted asset '{name}' from project assets.",
    }


# ── delete_project_texture ──


def delete_project_texture(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Delete a texture from the project's ``textures/`` dir (if unreferenced)."""
    file_name = params["file_name"]
    project_dir = state.project.path
    tex_dir = project_dir / constants.ASWFLayerNames.TEXTURES
    tex_file = tex_dir / file_name

    if not tex_file.exists():
        msg = f"Texture file not found: {constants.ASWFLayerNames.TEXTURES}/{file_name}"
        raise ValueError(msg)

    referencing = authoring.asset_folder.find_files_using(project_dir, tex_file)
    if referencing:
        files_list = ", ".join(referencing)
        msg = (
            f"Texture '{file_name}' is still referenced by: {files_list}. "
            f"Remove those references first."
        )
        raise ValueError(msg)

    tex_file.unlink()
    logger.info("Deleted project texture: %s", file_name)

    if tex_dir.exists() and not any(tex_dir.iterdir()):
        tex_dir.rmdir()

    return {
        "file": file_name,
        "message": f"Deleted texture '{file_name}' from project textures.",
    }




