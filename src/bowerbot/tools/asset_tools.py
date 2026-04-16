# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset tools — place referenced assets and manage the project assets/ dir."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from bowerbot.schemas import (
    ASWFLayerNames,
    AssetMetadata,
    PositionMode,
    SceneObject,
    TransformParams,
)
from bowerbot.services import asset_service, nested_service, stage_service
from bowerbot.services.geometry_service import (
    get_geometry_bounds,
    get_mpu,
    resolve_asset_position,
)
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import (
    require_project,
    require_stage,
    resolve_assets_dir,
)
from bowerbot.utils.naming import safe_prim_name
from bowerbot.utils.usd_utils import (
    find_asset_references,
    find_texture_references,
    resolve_asset_dir_for_prim,
)

logger = logging.getLogger(__name__)


def place_asset(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Add an asset reference to the scene at the given group/position."""
    if (err := require_stage(state)):
        return err

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

    assets_dir = resolve_assets_dir(state)
    try:
        relative_path = asset_service.prepare_asset(
            asset_path, assets_dir,
            fix_root_prim=params.get("fix_root_prim", False),
        )
    except ValueError as e:
        state.object_count -= 1
        return ToolResult(success=False, error=str(e))

    scene_object = SceneObject(
        prim_path=prim_path,
        asset=AssetMetadata(
            name=asset_name,
            source_skill="local",
            source_id=str(asset_path),
            file_path=relative_path,
        ),
        translate=(tx, ty, tz),
        rotate=(0.0, ry, 0.0),
    )

    stage_service.add_reference(state.stage, scene_object)
    stage_service.save(state.stage)
    state.touch_project()

    logger.info("Placed %s at %s (%s, %s, %s)", asset_name, prim_path, tx, ty, tz)
    return ToolResult(
        success=True,
        data={
            "prim_path": prim_path,
            "asset": asset_name,
            "position": {"x": tx, "y": ty, "z": tz},
            "rotation_y": ry,
            "message": f"Placed {asset_name} at {prim_path}",
        },
    )


def place_asset_inside(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Nest an asset inside an ASWF container asset's ``contents.usda``."""
    if (err := require_stage(state)):
        return err

    asset_path = Path(params["asset_file_path"])
    asset_name = params["asset_name"]
    container_prim_path = params["container_prim_path"]
    group = params["group"]
    tx = float(params["translate_x"])
    ty = float(params["translate_y"])
    tz = float(params["translate_z"])
    ry = float(params.get("rotate_y", 0.0))

    container_dir, _ = resolve_asset_dir_for_prim(
        state.stage, container_prim_path,
    )
    if container_dir is None:
        return ToolResult(
            success=False,
            error=(
                f"Cannot find ASWF asset folder for {container_prim_path}. "
                "Nested placement only works when the container is an "
                "ASWF folder asset (not a USDZ)."
            ),
        )

    assets_dir = resolve_assets_dir(state)
    try:
        relative_asset_path = asset_service.prepare_asset(
            asset_path, assets_dir,
            fix_root_prim=params.get("fix_root_prim", False),
        )
    except ValueError as e:
        return ToolResult(success=False, error=str(e))

    mode = PositionMode(
        params.get("position_mode", PositionMode.ABSOLUTE.value),
    )
    tx, ty, tz = resolve_asset_position(
        mode,
        get_geometry_bounds(container_dir),
        tx, ty, tz,
        has_explicit_y=params.get("translate_y") is not None,
        world_to_local_mat=stage_service.get_container_world_inverse(
            state.stage, container_prim_path,
        ),
        asset_mpu=get_mpu(container_dir),
    )

    ref_asset_path = _compute_ref_asset_path(
        relative_asset_path, assets_dir, container_dir,
    )

    state.object_count += 1
    safe_asset_name = safe_prim_name(asset_name)
    prim_name = f"{safe_asset_name}_{state.object_count:02d}"

    try:
        nested_prim_path = nested_service.add_nested_asset_reference(
            container_dir=container_dir,
            group=group,
            prim_name=prim_name,
            ref_asset_path=ref_asset_path,
            transform=TransformParams(
                translate=(tx, ty, tz),
                rotate=(0.0, ry, 0.0),
            ),
        )
    except (ValueError, RuntimeError) as e:
        state.object_count -= 1
        return ToolResult(success=False, error=str(e))

    state.stage = stage_service.open_stage(state.stage_path)
    state.touch_project()

    composed_path = f"{container_prim_path}/asset{nested_prim_path}"
    logger.info(
        "Placed %s inside %s at %s",
        asset_name, container_dir.name, nested_prim_path,
    )
    return ToolResult(
        success=True,
        data={
            "prim_path": composed_path,
            "asset": asset_name,
            "container": container_dir.name,
            "position": {"x": tx, "y": ty, "z": tz},
            "rotation_y": ry,
            "message": (
                f"Placed {asset_name} inside {container_dir.name} "
                f"at {composed_path}"
            ),
        },
    )


def list_project_assets(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List every asset in the project directory, with in-scene flags."""
    if (err := require_project(state)):
        return err

    assets_dir = resolve_assets_dir(state)
    if not assets_dir.exists():
        return ToolResult(
            success=True,
            data={"assets": [], "message": "No assets directory found."},
        )

    referenced = stage_service.get_all_ref_paths(state.stage) if state.stage else set()
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
    return ToolResult(
        success=True,
        data={
            "total": len(results),
            "unused_count": len(unused),
            "assets": results,
            "message": f"Project has {len(results)} asset(s), {len(unused)} unused.",
        },
    )


def delete_project_asset(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Delete an asset folder/file from the project, if unreferenced."""
    if (err := require_project(state)):
        return err

    name = params["name"]
    assets_dir = resolve_assets_dir(state)
    asset_path = assets_dir / name

    if not asset_path.exists():
        return ToolResult(success=False, error=f"Asset not found: {name}")

    skip_dir = asset_path if asset_path.is_dir() else None
    referencing = find_asset_references(
        state.project.path, name, skip_dir=skip_dir,
    )
    if referencing:
        files_list = ", ".join(referencing)
        return ToolResult(
            success=False,
            error=(
                f"Asset '{name}' is still referenced by: {files_list}. "
                f"Remove those references first."
            ),
        )

    if asset_path.is_dir():
        shutil.rmtree(asset_path)
    else:
        asset_path.unlink()
    logger.info("Deleted project asset: %s", asset_path)

    return ToolResult(
        success=True,
        data={
            "name": name,
            "message": f"Deleted asset '{name}' from project assets.",
        },
    )


def delete_project_texture(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Delete a texture from the project's ``textures/`` dir, if unreferenced."""
    if (err := require_project(state)):
        return err

    file_name = params["file_name"]
    project_dir = state.project.path
    tex_dir = project_dir / ASWFLayerNames.TEXTURES
    tex_file = tex_dir / file_name

    if not tex_file.exists():
        return ToolResult(
            success=False,
            error=f"Texture file not found: {ASWFLayerNames.TEXTURES}/{file_name}",
        )

    referencing = find_texture_references(project_dir, file_name)
    if referencing:
        files_list = ", ".join(referencing)
        return ToolResult(
            success=False,
            error=(
                f"Texture '{file_name}' is still referenced by: {files_list}. "
                f"Remove those references first."
            ),
        )

    tex_file.unlink()
    logger.info("Deleted project texture: %s", file_name)

    if tex_dir.exists() and not any(tex_dir.iterdir()):
        tex_dir.rmdir()

    return ToolResult(
        success=True,
        data={
            "file": file_name,
            "message": f"Deleted texture '{file_name}' from project textures.",
        },
    )


def _compute_ref_asset_path(
    relative_asset_path: str,
    assets_dir: Path,
    container_dir: Path,
) -> str:
    """Compute the reference path from the container to the nested asset.

    Prefers a container-relative path (e.g. ``./sub/asset.usda``); falls
    back to ``../asset.usda`` when the asset lives as a sibling folder.
    """
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


TOOLS: list[Tool] = [
    Tool(
        name="place_asset",
        description=(
            "Place a 3D asset into the current scene. The asset is added as a "
            "USD reference at the specified prim path with the given transform. "
            "Use the standard hierarchy: Furniture, Products, Lighting, Props."
        ),
        parameters={
            "type": "object",
            "properties": {
                "asset_file_path": {
                    "type": "string",
                    "description": "Local file path to the .usda/.usdc/.usdz asset.",
                },
                "asset_name": {
                    "type": "string",
                    "description": "Human-readable name for this asset instance.",
                },
                "group": {
                    "type": "string",
                    "enum": [
                        "Architecture", "Furniture", "Products", "Lighting", "Props",
                    ],
                    "description": "Which scene group to place the asset in.",
                },
                "translate_x": {
                    "type": "number",
                    "description": "X position in meters. 0 = left edge of room.",
                },
                "translate_y": {
                    "type": "number",
                    "description": (
                        "Y position in meters. 0 = floor, 2.7 = typical ceiling."
                    ),
                },
                "translate_z": {
                    "type": "number",
                    "description": "Z position in meters. 0 = back wall.",
                },
                "rotate_y": {
                    "type": "number",
                    "description": (
                        "Rotation around Y axis in degrees. 0 = facing forward."
                    ),
                    "default": 0.0,
                },
                "fix_root_prim": {
                    "type": "boolean",
                    "description": (
                        "If true, automatically wraps a non-Xform root "
                        "prim under an Xform to comply with ASWF "
                        "guidelines. Only use when the user confirms "
                        "they want the fix."
                    ),
                    "default": False,
                },
            },
            "required": [
                "asset_file_path", "asset_name", "group",
                "translate_x", "translate_y", "translate_z",
            ],
        },
    ),
    Tool(
        name="place_asset_inside",
        description=(
            "Place a 3D asset NESTED INSIDE another asset (the container). "
            "The asset becomes part of the container — if the container is "
            "duplicated or reused, the nested asset comes along. Use this for "
            "permanent fixtures (e.g. a built-in counter inside a building). "
            "For independent, moveable scene items, use place_asset instead. "
            "Translate values are in the container's coordinate space — use "
            "position_mode='absolute' with coordinates from list_prim_children "
            "bounds, or 'bounds_offset' for offsets from the container's surfaces."
        ),
        parameters={
            "type": "object",
            "properties": {
                "asset_file_path": {
                    "type": "string",
                    "description": "Local file path to the .usda/.usdc/.usdz asset.",
                },
                "asset_name": {
                    "type": "string",
                    "description": "Human-readable name for this asset instance.",
                },
                "container_prim_path": {
                    "type": "string",
                    "description": (
                        "Prim path of the ASWF container asset in the scene "
                        "(e.g. '/Scene/Architecture/Building_01'). The nested "
                        "asset will be written into this container's contents.usda."
                    ),
                },
                "group": {
                    "type": "string",
                    "enum": [
                        "Architecture", "Furniture", "Products", "Lighting", "Props",
                    ],
                    "description": "Logical grouping inside the container's contents.",
                },
                "translate_x": {
                    "type": "number",
                    "description": "X position in meters (container-local).",
                },
                "translate_y": {
                    "type": "number",
                    "description": "Y position in meters (container-local).",
                },
                "translate_z": {
                    "type": "number",
                    "description": "Z position in meters (container-local).",
                },
                "rotate_y": {
                    "type": "number",
                    "description": "Rotation around Y axis in degrees.",
                    "default": 0.0,
                },
                "position_mode": {
                    "type": "string",
                    "enum": [m.value for m in PositionMode],
                    "description": (
                        "How to interpret translate values: 'absolute' = "
                        "world-space coordinates (as returned by list_scene / "
                        "list_prim_children) — BowerBot converts to the "
                        "container's internal coordinate frame; 'bounds_offset' "
                        "= offsets from the container's bounding box surfaces."
                    ),
                    "default": PositionMode.ABSOLUTE.value,
                },
                "fix_root_prim": {
                    "type": "boolean",
                    "description": (
                        "If true, auto-wraps non-Xform root prims in the "
                        "asset being placed."
                    ),
                    "default": False,
                },
            },
            "required": [
                "asset_file_path", "asset_name", "container_prim_path", "group",
                "translate_x", "translate_y", "translate_z",
            ],
        },
    ),
    Tool(
        name="list_project_assets",
        description=(
            "List asset folders in the current project's assets directory. "
            "Shows which ones are referenced in the scene and which are "
            "unused. Use this to find asset folders that can be cleaned up. "
            "Optionally filter by name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional keyword to filter by asset name.",
                },
            },
        },
    ),
    Tool(
        name="delete_project_asset",
        description=(
            "Delete an asset from the project's assets directory. Works for "
            "both ASWF asset folders and standalone files (e.g. USDZ). Use "
            "this after removing an asset from the scene when the user "
            "confirms they want to delete the files too. BowerBot scans all "
            "USD files in the project to ensure the asset is not referenced "
            "elsewhere before deleting."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Name of the asset to delete. For ASWF folders, the "
                        "folder name (e.g. 'single_table'). For files, the "
                        "filename (e.g. 'cafe_table.usdz')."
                    ),
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="delete_project_texture",
        description=(
            "Delete a texture file from the project's textures/ directory. "
            "Scans all USD files in the project to ensure the texture is "
            "not referenced elsewhere before deleting."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": (
                        "Name of the texture file to delete (e.g. 'studio.exr')."
                    ),
                },
            },
            "required": ["file_name"],
        },
    ),
]


HANDLERS = {
    "place_asset": place_asset,
    "place_asset_inside": place_asset_inside,
    "list_project_assets": list_project_assets,
    "delete_project_asset": delete_project_asset,
    "delete_project_texture": delete_project_texture,
}
