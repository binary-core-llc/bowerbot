# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset service — orchestrates asset intake and placement for the asset tools."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from bowerbot.schemas import (
    AssetMetadata,
    AssetScopeNames,
    ASWFLayerNames,
    LayoutRules,
    PositionMode,
    SceneNamespace,
    SceneObject,
    TransformParams,
)
from bowerbot.state import SceneState
from bowerbot.utils import assets, layout_utils, library_utils, stage_utils, texture_utils
from bowerbot.utils.core.asset_folder import (
    compute_ref_asset_path,
    find_root_file,
    require_folder_entry,
    resolve_asset_dir_for_prim,
)
from bowerbot.utils.core.naming import clean_group, clean_prim_name, next_placement_path
from bowerbot.utils.core.references import (
    add_reference,
    add_references,
    assets_used_from,
    count_scene_refs_to_asset_dir,
    enclosing_placement,
    files_named_by,
    files_referencing,
    layer_files,
    placement_of,
    project_asset_references,
)
from bowerbot.utils.core.transforms import (
    asset_axes_rotation,
    resolve_position_in_asset,
    scene_correction,
    world_position,
)
from bowerbot.utils.core.values import read_axes, unpack_vec3

logger = logging.getLogger(__name__)


# ── place_asset ──


def place_asset(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Bring an asset into the project and add it to the scene."""
    stage = state.require_stage()
    asset_path = library_utils.find_asset(
        params["asset"],
        library_dir=state.library_dir,
        project_assets_dir=state.require_project().assets_dir,
    )
    asset_name = params["asset_name"]
    group = params["group"]
    tx = float(params["translate_x"])
    ty = float(params["translate_y"])
    tz = float(params["translate_z"])
    rotate = unpack_vec3(params, "rotate_x", "rotate_y", "rotate_z") or (0.0, 0.0, 0.0)

    prim_path, number = next_placement_path(
        stage, layout_utils.scene_group_path(group), clean_prim_name(asset_name, "Asset"),
        state.object_count,
    )
    counter_before = state.object_count
    state.object_count = number

    assets_dir = state.resolve_assets_dir()
    try:
        report = assets.intake.prepare_asset(
            asset_path, assets_dir,
            library_dir=state.library_dir,
            fix_root_prim=params.get("fix_root_prim", False),
            fix_root_transforms=params.get("fix_root_transforms", False),
        )
    except (ValueError, RuntimeError):
        state.object_count = counter_before
        raise

    scene_object = SceneObject(
        prim_path=prim_path,
        asset=AssetMetadata(
            name=asset_name,
            source_skill="local",
            source_id=str(asset_path),
            file_path=report.scene_ref_path,
        ),
        translate=(tx, ty, tz),
        rotate=rotate,
    )

    add_reference(stage, scene_object)
    stage_utils.save_stage(stage)
    state.touch_project()

    logger.info("Placed %s at %s (%s, %s, %s)", asset_name, prim_path, tx, ty, tz)
    return {
        "prim_path": prim_path,
        "asset": asset_name,
        "position": {"x": tx, "y": ty, "z": tz},
        "rotation": dict(zip("xyz", rotate, strict=True)),
        "intake": assets.intake.intake_summary(report),
        "message": assets.intake.placement_message(asset_name, prim_path, report),
    }


# ── place_layout ──


def place_layout(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Place many assets in one transactional batch from inline entries or a layout file."""
    stage = state.require_stage()
    raw_entries = params.get("placements")
    layout_file = params.get("layout_file")
    if (raw_entries is None) == (layout_file is None):
        msg = "place_layout needs exactly one of 'placements' or 'layout_file'."
        raise ValueError(msg)

    project = state.require_project()
    if layout_file is not None:
        file_path = layout_utils.resolve_layout_file(layout_file, project.path)
        raw_entries = layout_utils.parse_layout_file(file_path)
    if not raw_entries:
        raise ValueError("place_layout needs a non-empty 'placements' list.")

    valid, problems = layout_utils.validate_layout_entries(raw_entries)

    items: list[dict[str, Any]] = []
    folder_sources: dict[str, Path] = {}
    for idx, entry in valid:
        try:
            asset_path = layout_utils.resolve_layout_asset(
                entry.asset,
                project_assets_dir=project.assets_dir,
                library_dir=state.library_dir,
            )
            group_path = layout_utils.scene_group_path(entry.group)
        except ValueError as e:
            problems.append(f"placements[{idx}]: {e}")
            continue
        try:
            base_name = (
                clean_prim_name(entry.name, "Placement") if entry.name
                else clean_prim_name(asset_path.stem, "Placement", fallback="Placement")
            )
        except ValueError as e:
            problems.append(f"placements[{idx}]: {e}")
            continue
        target = assets.intake.intake_target_name(
            asset_path, state.library_dir, project.assets_dir,
        )
        prior = folder_sources.setdefault(target, asset_path)
        if prior != asset_path:
            here, there = (
                library_utils.asset_location(
                    p, library_dir=state.library_dir, project_dir=project.path,
                )
                for p in (asset_path, prior)
            )
            problems.append(
                f"placements[{idx}]: '{here}' and '{there}' would both "
                f"stage to assets/{target}; rename one source.",
            )
            continue
        items.append({
            "entry": entry,
            "asset_path": asset_path,
            "group_path": group_path,
            "base_name": base_name,
            "target": target,
            "count": layout_utils.count_entry(entry),
        })

    placed = sum(item["count"] for item in items)
    if placed > LayoutRules.MAX_PLACEMENTS:
        problems.append(
            f"layout expands to {placed} placements; the maximum per call "
            f"is {LayoutRules.MAX_PLACEMENTS}.",
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
        target: library_utils.asset_location(
            path, library_dir=state.library_dir, project_dir=project.path,
        )
        for target, path in folder_sources.items()
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
            reports[path] = assets.intake.prepare_asset(
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
        objects: list[SceneObject] = []
        for item in items:
            report = reports[item["asset_path"]]
            for transform in layout_utils.expand_entry(item["entry"]):
                prim_path, state.object_count = next_placement_path(
                    stage, item["group_path"], item["base_name"], state.object_count,
                )
                objects.append(SceneObject(
                    prim_path=prim_path,
                    asset=AssetMetadata(
                        name=item["base_name"],
                        source_skill="local",
                        source_id=str(item["asset_path"]),
                        file_path=report.scene_ref_path,
                    ),
                    translate=transform.translate,
                    rotate=transform.rotate,
                    scale=transform.scale,
                ))
        add_references(stage, objects)
        stage_utils.save_stage(stage)
    except Exception:
        state.object_count = object_count_snapshot
        stage.Reload()
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


def place_asset_inside(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Nest an asset inside an ASWF container's ``contents.usda``."""
    stage = state.require_stage()
    asset_path = library_utils.find_asset(
        params["asset"],
        library_dir=state.library_dir,
        project_assets_dir=state.require_project().assets_dir,
    )
    asset_name = params["asset_name"]
    container_prim_path = placement_of(stage, params["container_prim_path"])
    outer = enclosing_placement(stage, container_prim_path)
    if outer is not None:
        msg = (
            f"{container_prim_path} is itself nested inside {outer}; nesting goes "
            f"one level deep. Place into {outer}, or into a scene placement."
        )
        raise ValueError(msg)
    group = clean_group(params["group"])
    rotate = unpack_vec3(params, "rotate_x", "rotate_y", "rotate_z") or (0.0, 0.0, 0.0)

    container_dir, _ = resolve_asset_dir_for_prim(stage, container_prim_path)
    if container_dir is None:
        msg = (
            f"Cannot find ASWF asset folder for {container_prim_path}. "
            "Nested placement only works when the container is an "
            "ASWF folder asset (not a USDZ)."
        )
        raise ValueError(msg)

    instance_count = count_scene_refs_to_asset_dir(
        stage, container_dir,
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
    report = assets.intake.prepare_asset(
        asset_path, assets_dir,
        library_dir=state.library_dir,
        fix_root_prim=params.get("fix_root_prim", False),
        fix_root_transforms=params.get("fix_root_transforms", False),
    )

    local = resolve_position_in_asset(
        stage, container_prim_path, container_dir,
        PositionMode(params.get("position_mode", PositionMode.ABSOLUTE.value)),
        read_axes(params, "translate_x", "translate_y", "translate_z"),
    )

    ref_asset_path = compute_ref_asset_path(
        report.scene_ref_path, assets_dir, container_dir,
    )

    contents_group = (
        f"{container_prim_path}/{SceneNamespace.ASSET_CHILD}/{AssetScopeNames.CONTENTS}/{group}"
    )
    nested_path, number = next_placement_path(
        stage, contents_group, clean_prim_name(asset_name, "Asset"), state.object_count,
    )
    prim_name = nested_path.rsplit("/", 1)[-1]
    counter_before = state.object_count
    state.object_count = number

    try:
        assets.nested.add_nested_asset_reference(
            container_dir=container_dir,
            group=group,
            prim_name=prim_name,
            ref_asset_path=ref_asset_path,
            transform=TransformParams(
                translate=local,
                rotate=asset_axes_rotation(rotate, scene_correction(stage, container_dir)),
            ),
        )
    except (ValueError, RuntimeError):
        state.object_count = counter_before
        raise

    stage = state.reopen_stage()
    state.touch_project()

    composed_path = (
        f"{container_prim_path}/{SceneNamespace.ASSET_CHILD}/{AssetScopeNames.CONTENTS}/{group}/{prim_name}"
    )
    wx, wy, wz = world_position(stage.GetPrimAtPath(composed_path))
    logger.info(
        "Placed %s inside %s at %s",
        asset_name, container_dir.name, composed_path,
    )
    return {
        "prim_path": composed_path,
        "asset": asset_name,
        "container": container_dir.name,
        "position": {"x": round(wx, 4), "y": round(wy, 4), "z": round(wz, 4)},
        "rotation": dict(zip("xyz", rotate, strict=True)),
        "intake": assets.intake.intake_summary(report),
        "message": (
            f"Placed {asset_name} inside {container_dir.name} at {composed_path}"
        ),
    }


# ── list_project_assets ──


def list_project_assets(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every asset in the project's assets dir, with where each one is referenced."""
    project = state.require_project()
    assets_dir = state.resolve_assets_dir()
    if not assets_dir.exists():
        return {"assets": [], "message": "No assets directory found."}

    references = project_asset_references(project.path, assets_dir)
    in_scene = assets_used_from(
        references,
        str(project.scene_path.relative_to(project.path)),
        str(assets_dir.relative_to(project.path)),
    )
    query = (params.get("query") or "").lower()

    results: list[dict[str, Any]] = []
    for entry in sorted(assets_dir.iterdir()):
        if query and query not in entry.name.lower():
            continue
        results.append({
            "name": entry.name,
            "type": "folder" if entry.is_dir() else "file",
            "in_scene": entry.name in in_scene,
            "referenced_by": files_referencing(references, entry.name),
        })

    unused = [a for a in results if not a["referenced_by"]]
    return {
        "total": len(results),
        "unused_count": len(unused),
        "assets": results,
        "message": f"Project has {len(results)} asset(s), {len(unused)} unused.",
    }


# ── delete_project_asset ──


def cleanup_unused_contents(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Drop empty ``contents.usda`` layers, per asset or project-wide."""
    state.require_project()
    stage = state.require_stage()
    asset_prim_path = params.get("asset_prim_path")

    if asset_prim_path:
        asset_dir, _ = resolve_asset_dir_for_prim(stage, asset_prim_path)
        if asset_dir is None:
            msg = (
                f"Cannot find ASWF asset folder for {asset_prim_path}. "
                "Cleanup only works on ASWF folder assets."
            )
            raise ValueError(msg)

        removed = assets.nested.cleanup_unused_contents_in_folder(asset_dir)
        state.reopen_stage()
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
        if not (entry / ASWFLayerNames.CONTENTS).exists():
            continue
        removed = assets.nested.cleanup_unused_contents_in_folder(entry)
        if removed:
            per_folder.append({"asset_folder": entry.name, "removed": removed})
            total += len(removed)

    state.reopen_stage()
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


def freeze_asset(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Move project assets' root transforms onto their parts (one or all)."""
    assets_dir = state.resolve_assets_dir()
    name = params.get("name")

    if name:
        results = [assets.freeze.freeze_one_asset(assets_dir, name)]
    else:
        results = [
            assets.freeze.freeze_one_asset(assets_dir, entry.name)
            for entry in sorted(assets_dir.iterdir())
            if entry.is_dir() and find_root_file(entry) is not None
        ]

    state.touch_project()
    if state.stage is not None:
        state.reopen_stage()

    baked_count = sum(1 for r in results if r["baked"])
    logger.info(
        "Froze %d/%d asset(s) in project", baked_count, len(results),
    )
    return {
        "results": results,
        "baked_count": baked_count,
        "total": len(results),
        "message": (
            f"Froze the root transform of {baked_count} of {len(results)} asset(s)."
        ),
    }


# ── delete_project_asset ──


def delete_project_asset(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Delete an asset folder/file from the project (only if unreferenced)."""
    project = state.require_project()
    name = params["name"]
    assets_dir = state.resolve_assets_dir()
    asset_path = require_folder_entry(assets_dir, name)

    if not asset_path.exists():
        msg = f"Asset not found: {name}"
        raise ValueError(msg)

    referencing = files_referencing(
        project_asset_references(project.path, assets_dir), name,
    )
    if referencing:
        files_list = ", ".join(referencing)
        msg = (
            f"Asset '{name}' is still referenced by: {files_list}. "
            f"Remove those references first."
        )
        raise ValueError(msg)

    if asset_path.is_dir() and not asset_path.is_symlink():
        shutil.rmtree(asset_path)
    else:
        asset_path.unlink()  # a file, or a link: never what a link points to
    logger.info("Deleted project asset: %s", asset_path)

    return {
        "name": name,
        "message": f"Deleted asset '{name}' from project assets.",
    }


# ── delete_project_texture ──


def delete_project_texture(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Delete a texture from the project (``textures/`` or an asset folder) nothing uses."""
    project = state.require_project()
    file_name = params["file_name"]
    target = texture_utils.project_texture_file(project.path, project.assets_dir, file_name)

    users = files_named_by(layer_files(project.path)).get(target, [])
    if users:
        names = ", ".join(sorted({str(user.relative_to(project.path)) for user in users}))
        msg = f"Texture '{file_name}' is still used by: {names}. Remove those uses first."
        raise ValueError(msg)

    target.unlink()
    textures = project.path / ASWFLayerNames.TEXTURES
    in_asset = target.is_relative_to(project.assets_dir.resolve())
    stop = (
        project.assets_dir / target.relative_to(project.assets_dir.resolve()).parts[0]
        if in_asset else textures.parent
    )
    texture_utils.remove_empty_folders(target.parent, stop)
    location = target.relative_to(project.path.resolve()).as_posix()
    logger.info("Deleted project texture: %s", location)
    return {
        "file": location,
        "message": f"Deleted texture {location} from the project.",
    }




