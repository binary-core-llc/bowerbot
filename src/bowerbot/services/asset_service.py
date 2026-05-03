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
    ASWFLayerNames,
    IntakeReport,
    PositionMode,
    SceneObject,
    TransformParams,
)
from bowerbot.state import SceneState
from bowerbot.utils import (
    asset_intake_utils,
    geometry_utils,
    library_utils,
    stage_utils,
)
from bowerbot.utils.asset_folder_utils import resolve_asset_dir_for_prim
from bowerbot.utils.naming_utils import safe_prim_name
from bowerbot.utils.stage_utils import (
    find_asset_references,
    find_texture_references,
)

logger = logging.getLogger(__name__)


# ── place_asset ──


def place_asset(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Bring an asset into the project and add it to the scene."""
    asset_path = Path(params["asset_file_path"])
    asset_name = params["asset_name"]
    group = params["group"]
    tx = float(params["translate_x"])
    ty = float(params["translate_y"])
    tz = float(params["translate_z"])
    ry = float(params.get("rotate_y", 0.0))

    state.object_count += 1
    safe_asset_name = safe_prim_name(asset_name)
    prim_path = f"/Scene/{group}/{safe_asset_name}_{state.object_count:02d}"

    assets_dir = state.resolve_assets_dir()
    try:
        report = prepare_asset(
            asset_path, assets_dir,
            library_dir=state.library_dir,
            fix_root_prim=params.get("fix_root_prim", False),
        )
    except (ValueError, RuntimeError):
        state.object_count -= 1
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
        rotate=(0.0, ry, 0.0),
    )

    stage_utils.add_reference(state.stage, scene_object)
    stage_utils.save_stage(state.stage)
    state.touch_project()

    logger.info("Placed %s at %s (%s, %s, %s)", asset_name, prim_path, tx, ty, tz)
    return {
        "prim_path": prim_path,
        "asset": asset_name,
        "position": {"x": tx, "y": ty, "z": tz},
        "rotation_y": ry,
        "intake": _intake_summary(report),
        "message": _placement_message(asset_name, prim_path, report),
    }


# ── place_asset_inside ──


def place_asset_inside(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Nest an asset inside an ASWF container's ``contents.usda``."""
    asset_path = Path(params["asset_file_path"])
    asset_name = params["asset_name"]
    container_prim_path = params["container_prim_path"]
    group = params["group"]
    tx = float(params["translate_x"])
    ty = float(params["translate_y"])
    tz = float(params["translate_z"])
    ry = float(params.get("rotate_y", 0.0))

    container_dir, _ = resolve_asset_dir_for_prim(state.stage, container_prim_path)
    if container_dir is None:
        msg = (
            f"Cannot find ASWF asset folder for {container_prim_path}. "
            "Nested placement only works when the container is an "
            "ASWF folder asset (not a USDZ)."
        )
        raise ValueError(msg)

    instance_count = stage_utils.count_scene_refs_to_asset_dir(
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
    report = prepare_asset(
        asset_path, assets_dir,
        library_dir=state.library_dir,
        fix_root_prim=params.get("fix_root_prim", False),
    )

    mode = PositionMode(
        params.get("position_mode", PositionMode.ABSOLUTE.value),
    )
    tx, ty, tz = geometry_utils.resolve_asset_position(
        mode,
        geometry_utils.get_geometry_bounds(container_dir),
        tx, ty, tz,
        has_explicit_y=params.get("translate_y") is not None,
        world_to_local_mat=stage_utils.get_container_world_inverse(
            state.stage, container_prim_path,
        ),
        asset_mpu=geometry_utils.get_mpu(container_dir),
    )

    ref_asset_path = _compute_ref_asset_path(
        report.scene_ref_path, assets_dir, container_dir,
    )

    state.object_count += 1
    safe_asset_name = safe_prim_name(asset_name)
    prim_name = f"{safe_asset_name}_{state.object_count:02d}"

    try:
        nested_prim_path = asset_intake_utils.add_nested_asset_reference(
            container_dir=container_dir,
            group=group,
            prim_name=prim_name,
            ref_asset_path=ref_asset_path,
            transform=TransformParams(
                translate=(tx, ty, tz),
                rotate=(0.0, ry, 0.0),
            ),
        )
    except (ValueError, RuntimeError):
        state.object_count -= 1
        raise

    state.stage = stage_utils.open_stage(state.stage_path)
    state.touch_project()

    composed_path = f"{container_prim_path}/asset{nested_prim_path}"
    logger.info(
        "Placed %s inside %s at %s",
        asset_name, container_dir.name, nested_prim_path,
    )
    return {
        "prim_path": composed_path,
        "asset": asset_name,
        "container": container_dir.name,
        "position": {"x": tx, "y": ty, "z": tz},
        "rotation_y": ry,
        "intake": _intake_summary(report),
        "message": (
            f"Placed {asset_name} inside {container_dir.name} at {composed_path}"
        ),
    }


# ── list_project_assets ──


def list_project_assets(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every asset in the project's assets dir, with in-scene flags."""
    assets_dir = state.resolve_assets_dir()
    if not assets_dir.exists():
        return {"assets": [], "message": "No assets directory found."}

    referenced = (
        stage_utils.get_all_ref_paths(state.stage) if state.stage else set()
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


def cleanup_unused_contents(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Drop empty ``contents.usda`` layers, per asset or project-wide."""
    asset_prim_path = params.get("asset_prim_path")

    if asset_prim_path:
        asset_dir, _ = resolve_asset_dir_for_prim(state.stage, asset_prim_path)
        if asset_dir is None:
            msg = (
                f"Cannot find ASWF asset folder for {asset_prim_path}. "
                "Cleanup only works on ASWF folder assets."
            )
            raise ValueError(msg)

        removed = asset_intake_utils.cleanup_unused_contents_in_folder(asset_dir)
        state.stage = stage_utils.open_stage(state.stage_path)
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
        removed = asset_intake_utils.cleanup_unused_contents_in_folder(entry)
        if removed:
            per_folder.append({"asset_folder": entry.name, "removed": removed})
            total += len(removed)

    state.stage = stage_utils.open_stage(state.stage_path)
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


# ── delete_project_asset ──


def delete_project_asset(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Delete an asset folder/file from the project (only if unreferenced)."""
    name = params["name"]
    assets_dir = state.resolve_assets_dir()
    asset_path = assets_dir / name

    if not asset_path.exists():
        msg = f"Asset not found: {name}"
        raise ValueError(msg)

    skip_dir = asset_path if asset_path.is_dir() else None
    referencing = find_asset_references(
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


def delete_project_texture(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Delete a texture from the project's ``textures/`` dir (if unreferenced)."""
    file_name = params["file_name"]
    project_dir = state.project.path
    tex_dir = project_dir / ASWFLayerNames.TEXTURES
    tex_file = tex_dir / file_name

    if not tex_file.exists():
        msg = f"Texture file not found: {ASWFLayerNames.TEXTURES}/{file_name}"
        raise ValueError(msg)

    referencing = find_texture_references(project_dir, file_name)
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


# ── prepare_asset routing (USDZ / library-package / loose-file) ──


def prepare_asset(
    asset_path: Path,
    assets_dir: Path,
    *,
    library_dir: Path | None,
    fix_root_prim: bool = False,
) -> IntakeReport:
    """Route an input file to USDZ / library-package / loose-file intake."""
    if asset_path.suffix.lower() == ".usdz":
        return asset_intake_utils.intake_usdz(asset_path, assets_dir)

    if library_dir is not None:
        package_dir = library_utils.find_package_for(asset_path, library_dir)
        if package_dir is not None:
            return asset_intake_utils.intake_folder(package_dir, assets_dir)

    asset_intake_utils.ensure_aswf_compliance(asset_path, fix_root_prim=fix_root_prim)

    folder_name = asset_path.stem
    root_file = asset_intake_utils.create_asset_folder(
        output_dir=assets_dir,
        asset_name=folder_name,
        geometry_file=asset_path,
    )
    return IntakeReport(
        scene_ref_path=f"assets/{folder_name}/{root_file.name}",
        asset_folder_name=folder_name,
        root_original_name=asset_path.name,
        root_canonical_name=root_file.name,
        was_renamed=asset_path.name != root_file.name,
        files_copied=1,
    )


def _compute_ref_asset_path(
    relative_asset_path: str,
    assets_dir: Path,
    container_dir: Path,
) -> str:
    """Compute the reference path from the container to the nested asset."""
    asset_full_path = (assets_dir.parent / relative_asset_path).resolve()
    try:
        ref_path = asset_full_path.relative_to(container_dir.resolve())
        return f"./{ref_path.as_posix()}"
    except ValueError:
        return (
            "../" + asset_full_path.relative_to(
                container_dir.parent.resolve(),
            ).as_posix()
        )


def _intake_summary(report: IntakeReport) -> dict[str, Any]:
    """Condense an intake report into fields surfaced to the LLM."""
    return {
        "asset_folder": report.asset_folder_name,
        "root_canonical_name": report.root_canonical_name,
        "was_renamed": report.was_renamed,
        "root_original_name": (
            report.root_original_name if report.was_renamed else None
        ),
        "files_copied": report.files_copied,
        "localized_layers": report.localized_layers,
        "localized_assets": report.localized_assets,
        "warnings": report.warnings,
    }


def _placement_message(
    asset_name: str, prim_path: str, report: IntakeReport,
) -> str:
    """Format a placement message that narrates intake normalization."""
    parts = [f"Placed {asset_name} at {prim_path}."]
    if report.was_renamed:
        parts.append(
            f"Normalized on intake: {report.root_original_name} -> "
            f"{report.root_canonical_name} (ASWF convention).",
        )
    localized = len(report.localized_layers) + len(report.localized_assets)
    if localized:
        parts.append(
            f"Localized {localized} external dependency/ies into the asset folder.",
        )
    return " ".join(parts)
