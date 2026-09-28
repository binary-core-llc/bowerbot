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
from bowerbot import utils
from bowerbot.utils import authoring
from bowerbot.utils import usd

logger = logging.getLogger(__name__)


# ── place_asset ──


def place_asset(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Bring an asset into the project and add it to the scene."""
    asset_path = utils.asset_folder.resolve_asset_file_path(
        params["asset_file_path"],
        state.project.path if state.project else None,
        state.library_dir,
    )
    asset_name = params["asset_name"]
    group = params["group"]
    tx = float(params["translate_x"])
    ty = float(params["translate_y"])
    tz = float(params["translate_z"])
    ry = float(params.get("rotate_y", 0.0))

    state.object_count += 1
    safe_asset_name = usd.naming.safe_prim_name(asset_name)
    prim_path = f"/Scene/{group}/{safe_asset_name}_{state.object_count:02d}"

    assets_dir = state.resolve_assets_dir()
    try:
        report = utils.intake.prepare_asset(
            asset_path, assets_dir,
            library_dir=state.library_dir,
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
        rotate=(0.0, ry, 0.0),
    )

    utils.stage.add_reference(state.stage, scene_object)
    authoring.stage.save_stage(state.stage)
    state.touch_project()

    logger.info("Placed %s at %s (%s, %s, %s)", asset_name, prim_path, tx, ty, tz)
    return {
        "prim_path": prim_path,
        "asset": asset_name,
        "position": {"x": tx, "y": ty, "z": tz},
        "rotation_y": ry,
        "intake": utils.intake.intake_summary(report),
        "message": utils.intake.placement_message(asset_name, prim_path, report),
    }


# ── place_layout ──


def place_layout(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Place many assets in one transactional batch from inline entries."""
    raw_entries = params.get("placements")
    if not raw_entries:
        raise ValueError("place_layout needs a non-empty 'placements' list.")

    project_dir = state.project.path if state.project else None

    valid, problems = utils.layout.validate_layout_entries(raw_entries)

    items: list[dict[str, Any]] = []
    folder_sources: dict[str, Path] = {}
    for idx, entry in valid:
        try:
            asset_path = utils.layout.resolve_layout_asset(
                entry.asset,
                project_dir=project_dir,
                library_dir=state.library_dir,
            )
            group_path = utils.layout.scene_group_path(entry.group)
        except ValueError as e:
            problems.append(f"placements[{idx}]: {e}")
            continue
        base_name = usd.naming.safe_prim_name(entry.name or asset_path.stem)
        if not usd.naming.is_valid_prim_name(base_name):
            problems.append(
                f"placements[{idx}]: name '{base_name}' is not a valid USD "
                f"prim name (it must start with a letter or underscore); "
                f"set the entry's 'name'.",
            )
            continue
        target = utils.intake.intake_target_name(
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
            "count": utils.layout.count_entry(entry),
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
            reports[path] = utils.intake.prepare_asset(
                path, assets_dir,
                library_dir=state.library_dir,
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
            for transform in utils.layout.expand_entry(item["entry"]):
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
        utils.stage.add_references(state.stage, objects)
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


# ── place_asset_inside ──


def place_asset_inside(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Nest an asset inside an ASWF container's ``contents.usda``."""
    asset_path = utils.asset_folder.resolve_asset_file_path(
        params["asset_file_path"],
        state.project.path if state.project else None,
        state.library_dir,
    )
    asset_name = params["asset_name"]
    container_prim_path = params["container_prim_path"]
    group = params["group"]
    tx = float(params["translate_x"])
    ty = float(params["translate_y"])
    tz = float(params["translate_z"])
    ry = float(params.get("rotate_y", 0.0))

    container_dir, _ = utils.asset_folder.resolve_asset_dir_for_prim(
        state.stage, container_prim_path,
    )
    if container_dir is None:
        msg = (
            f"Cannot find ASWF asset folder for {container_prim_path}. "
            "Nested placement only works when the container is an "
            "ASWF folder asset (not a USDZ)."
        )
        raise ValueError(msg)

    instance_count = utils.stage.count_scene_refs_to_asset_dir(
        state.stage, container_dir,
    )
    confirmed = bool(params.get("confirm_shared_modification", False))
    if instance_count >= 2 and not confirmed:
        msg = (
            f"Container '{container_dir.name}/' is referenced by "
            f"{instance_count} scene instances. Nested placement modifies "
            f"the shared asset folder, which would affect all "
            f"{instance_count} instances. Two ways forward: "
            f"(1) For per-instance placement (different positions per "
            f"instance), use 'place_asset' instead; it places the asset "
            f"as an independent scene-level prim. "
            f"(2) For deliberate shared modification (every instance "
            f"should get the nested asset), retry with "
            f"confirm_shared_modification=true."
        )
        raise ValueError(msg)

    assets_dir = state.resolve_assets_dir()
    report = utils.intake.prepare_asset(
        asset_path, assets_dir,
        library_dir=state.library_dir,
        fix_root_prim=params.get("fix_root_prim", False),
        fix_root_transforms=params.get("fix_root_transforms", False),
    )

    mode = schemas.PositionMode(
        params.get("position_mode", schemas.PositionMode.ABSOLUTE.value),
    )
    tx, ty, tz = utils.geometry.resolve_asset_position(
        mode,
        utils.geometry.get_geometry_bounds(container_dir),
        tx, ty, tz,
        has_explicit_y=params.get("translate_y") is not None,
        world_to_local_mat=utils.stage.get_container_world_inverse(
            state.stage, container_prim_path,
        ),
        asset_mpu=utils.geometry.get_mpu(container_dir),
    )

    ref_asset_path = utils.asset_folder.compute_ref_asset_path(
        report.scene_ref_path, assets_dir, container_dir,
    )

    state.object_count += 1
    safe_asset_name = usd.naming.safe_prim_name(asset_name)
    prim_name = f"{safe_asset_name}_{state.object_count:02d}"

    try:
        utils.intake.add_nested_asset_reference(
            container_dir=container_dir,
            group=group,
            prim_name=prim_name,
            ref_asset_path=ref_asset_path,
            transform=schemas.TransformParams(
                translate=(tx, ty, tz),
                rotate=(0.0, ry, 0.0),
            ),
        )
    except (ValueError, RuntimeError):
        state.object_count -= 1
        raise

    state.stage = authoring.stage.open_stage(state.stage_path)
    state.touch_project()

    composed_path = (
        f"{container_prim_path}/asset/contents/{group}/{prim_name}"
    )
    logger.info(
        "Placed %s inside %s at %s",
        asset_name, container_dir.name, composed_path,
    )
    return {
        "prim_path": composed_path,
        "asset": asset_name,
        "container": container_dir.name,
        "position": {"x": tx, "y": ty, "z": tz},
        "rotation_y": ry,
        "intake": utils.intake.intake_summary(report),
        "message": (
            f"Placed {asset_name} inside {container_dir.name} at {composed_path}"
        ),
    }


# ── list_project_assets ──


def list_project_assets(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every asset in the project's assets dir, with in-scene flags."""
    assets_dir = state.resolve_assets_dir()
    if not assets_dir.exists():
        return {"assets": [], "message": "No assets directory found."}

    referenced = (
        usd.references.get_all_ref_paths(state.stage) if state.stage else set()
    )
    query = (params.get("query") or "").lower()

    results: list[dict[str, Any]] = []
    for entry in sorted(assets_dir.iterdir()):
        if query and query not in entry.name.lower():
            continue
        results.append({
            "name": entry.name,
            "type": "folder" if entry.is_dir() else "file",
            "in_scene": any(entry.name in r for r in referenced),
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
        asset_dir, _ = utils.asset_folder.resolve_asset_dir_for_prim(state.stage, asset_prim_path)
        if asset_dir is None:
            msg = (
                f"Cannot find ASWF asset folder for {asset_prim_path}. "
                "Cleanup only works on ASWF folder assets."
            )
            raise ValueError(msg)

        removed = utils.intake.cleanup_unused_contents_in_folder(asset_dir)
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
    for entry in sorted(assets_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / constants.ASWFLayerNames.CONTENTS).exists():
            continue
        removed = utils.intake.cleanup_unused_contents_in_folder(entry)
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
        results = [utils.intake.freeze_one_asset(assets_dir, name)]
    else:
        results = [
            utils.intake.freeze_one_asset(assets_dir, entry.name)
            for entry in sorted(assets_dir.iterdir())
            if entry.is_dir() and (entry / constants.ASWFLayerNames.GEO).exists()
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

    skip_dir = asset_path if asset_path.is_dir() else None
    referencing = utils.stage.find_asset_references(
        state.project.path, name, skip_dir=skip_dir,
    )
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

    referencing = utils.textures.find_texture_references(project_dir, file_name)
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




