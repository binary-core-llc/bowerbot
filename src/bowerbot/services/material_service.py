# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Material service — orchestrates material operations for the material tools."""

from __future__ import annotations

import logging
from typing import Any

from bowerbot.schemas import ASWFLayerNames, ProceduralMaterialParams
from bowerbot.state import SceneState
from bowerbot.utils import library_utils, material_utils
from bowerbot.utils.core.asset_folder import (
    check_shared_modification,
    resolve_asset_dir_for_prim,
    to_asset_local,
    unused_asset_files,
)
from bowerbot.utils.core.integrity import require_prim
from bowerbot.utils.core.naming import clean_prim_name
from bowerbot.utils.core.references import newly_unused, unused_files_note

logger = logging.getLogger(__name__)


def create_material(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Author a procedural MaterialX material and bind it to a prim."""
    stage = state.require_stage()
    prim_path = params["prim_path"]
    material_name = clean_prim_name(params["material_name"], "Material")
    require_prim(stage, prim_path)

    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(stage, prim_path)
    if asset_dir is None or ref_prim_path is None:
        msg = (
            f"Cannot find ASWF asset folder for {prim_path}. "
            "Procedural materials only work on assets placed as ASWF "
            "folders (not USDZ)."
        )
        raise ValueError(msg)

    check_shared_modification(stage, asset_dir, params, op_label="create_material")

    asset_local_path = to_asset_local(prim_path, ref_prim_path)
    inputs = {
        name: float(params.get(name, default)) for name, default in (
            ("base_color_r", 0.8), ("base_color_g", 0.8), ("base_color_b", 0.8),
            ("metalness", 0.0), ("roughness", 0.5), ("opacity", 1.0),
        )
    }
    out_of_range = [f"{name}={value}" for name, value in inputs.items() if not 0.0 <= value <= 1.0]
    if out_of_range:
        msg = f"Material inputs run from 0 to 1; got {', '.join(out_of_range)}."
        raise ValueError(msg)
    material_params = ProceduralMaterialParams(
        material_name=material_name,
        base_color=(inputs["base_color_r"], inputs["base_color_g"], inputs["base_color_b"]),
        metalness=inputs["metalness"],
        roughness=inputs["roughness"],
        opacity=inputs["opacity"],
    )

    material_prim_path = material_utils.create_procedural_material_in_folder(
        asset_dir=asset_dir,
        prim_path=asset_local_path,
        params=material_params,
    )

    state.reopen_stage()
    logger.info(
        "Created procedural material %s on %s in %s/",
        material_prim_path, prim_path, asset_dir.name,
    )
    return {
        "prim_path": prim_path,
        "material": material_prim_path,
        "asset_folder": asset_dir.name,
        "message": (
            f"Created procedural material '{material_name}' and "
            f"bound to {prim_path} in {asset_dir.name}/{ASWFLayerNames.MTL}"
        ),
    }


def bind_material(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Copy a material from a file into the asset and bind it to a prim."""
    stage = state.require_stage()
    prim_path = params["prim_path"]
    material_file = library_utils.find_asset(
        params["material_asset"],
        library_dir=state.library_dir,
        project_assets_dir=None,
    )
    material_prim_path = params.get("material_prim_path")
    require_prim(stage, prim_path)

    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(stage, prim_path)
    if asset_dir is None or ref_prim_path is None:
        msg = (
            f"Cannot find ASWF asset folder for {prim_path}. "
            "Material binding only works on assets placed as ASWF "
            "folders (not USDZ)."
        )
        raise ValueError(msg)

    check_shared_modification(stage, asset_dir, params, op_label="bind_material")

    asset_local_path = to_asset_local(prim_path, ref_prim_path)
    material_prim_path = material_utils.add_material_to_folder(
        asset_dir=asset_dir,
        material_file=material_file,
        prim_path=asset_local_path,
        material_prim_path=material_prim_path,
    )

    state.reopen_stage()
    logger.info(
        "Bound %s to %s in %s/",
        material_prim_path, prim_path, asset_dir.name,
    )
    return {
        "prim_path": prim_path,
        "material": material_prim_path,
        "asset_folder": asset_dir.name,
        "message": (
            f"Bound {material_prim_path} to {prim_path} in "
            f"{asset_dir.name}/{ASWFLayerNames.MTL}"
        ),
    }


def remove_material(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove the material binding on a prim inside an ASWF asset."""
    stage = state.require_stage()
    prim_path = params["prim_path"]
    require_prim(stage, prim_path)
    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(stage, prim_path)
    if asset_dir is None or ref_prim_path is None:
        msg = f"Cannot find ASWF asset folder for {prim_path}."
        raise ValueError(msg)

    asset_local_path = to_asset_local(prim_path, ref_prim_path)
    unused_before = unused_asset_files(asset_dir)
    if not material_utils.remove_material_binding_from_folder(asset_dir, asset_local_path):
        msg = (
            f"{prim_path} has no binding in {asset_dir.name}/{ASWFLayerNames.MTL} "
            "to remove; a material from the asset's own files stays."
        )
        raise ValueError(msg)
    unused = newly_unused(
        state.require_project().path, unused_before, unused_asset_files(asset_dir),
    )
    state.reopen_stage()

    logger.info("Removed material from %s", prim_path)
    return {
        "prim_path": prim_path,
        "asset_folder": asset_dir.name,
        "unused_files": unused,
        "message": f"Removed material binding from {prim_path}." + unused_files_note(unused),
    }


def list_materials(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every material across the project's asset folders."""
    state.require_stage()
    del params
    assets_dir = state.resolve_assets_dir()
    all_materials: list[dict[str, Any]] = []

    for entry in assets_dir.iterdir():
        if not entry.is_dir():
            continue
        if not (entry / ASWFLayerNames.MTL).exists():
            continue
        materials = material_utils.list_materials_in_folder(entry)
        for mat in materials:
            mat["asset_folder"] = entry.name
        all_materials.extend(materials)

    return {
        "material_count": len(all_materials),
        "materials": all_materials,
        "message": f"Scene has {len(all_materials)} material(s).",
    }


def cleanup_unused_materials(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Delete material definitions no prim binds to, per asset or project-wide."""
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

        unused_before = unused_asset_files(asset_dir)
        removed = material_utils.cleanup_unused_in_folder(asset_dir)
        left = newly_unused(
            state.require_project().path, unused_before, unused_asset_files(asset_dir),
        )
        state.reopen_stage()
        logger.info(
            "Cleaned %d unused material(s) from %s", len(removed), asset_dir.name,
        )
        return {
            "asset_folder": asset_dir.name,
            "removed_count": len(removed),
            "removed": removed,
            "unused_files": left,
            "message": (
                f"Removed {len(removed)} unused material(s) from {asset_dir.name}."
                + unused_files_note(left)
            ),
        }

    assets_dir = state.resolve_assets_dir()
    project_dir = state.require_project().path
    per_folder: list[dict[str, Any]] = []
    unused: list[str] = []
    total = 0
    for entry in sorted(assets_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / ASWFLayerNames.MTL).exists():
            continue
        unused_before = unused_asset_files(entry)
        removed = material_utils.cleanup_unused_in_folder(entry)
        if removed:
            per_folder.append({"asset_folder": entry.name, "removed": removed})
            total += len(removed)
            unused += newly_unused(project_dir, unused_before, unused_asset_files(entry))

    state.reopen_stage()
    logger.info(
        "Cleaned %d unused material(s) across %d asset folder(s)",
        total, len(per_folder),
    )
    return {
        "total_removed": total,
        "per_folder": per_folder,
        "unused_files": unused,
        "message": (
            f"Removed {total} unused material(s) across "
            f"{len(per_folder)} asset folder(s)." + unused_files_note(unused)
        ),
    }


