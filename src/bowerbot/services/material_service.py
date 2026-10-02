# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Material service — orchestrates material operations for the material tools."""

from __future__ import annotations

import logging
from typing import Any

from bowerbot import constants
from bowerbot import scene_state
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import materials

logger = logging.getLogger(__name__)


def create_material(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Author a procedural MaterialX material and bind it to a prim."""
    prim_path = params["prim_path"]
    material_name = params["material_name"]

    asset_dir, ref_prim_path = authoring.placement.require_asset_context(
        state.stage, prim_path,
    )

    materials.bind.refuse_shared_modification(
        state.stage, asset_dir, params, op_label="create_material",
    )

    asset_local_path = authoring.placement.to_asset_local(prim_path, ref_prim_path)
    material_params = schemas.ProceduralMaterialParams(
        material_name=material_name,
        base_color=(
            float(params.get("base_color_r", 0.8)),
            float(params.get("base_color_g", 0.8)),
            float(params.get("base_color_b", 0.8)),
        ),
        metalness=float(params.get("metalness", 0.0)),
        roughness=float(params.get("roughness", 0.5)),
        opacity=float(params.get("opacity", 1.0)),
    )

    material_prim_path = materials.procedural.create(
        asset_dir=asset_dir,
        prim_path=asset_local_path,
        params=material_params,
    )

    state.reload_stage()
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
            f"bound to {prim_path} in {asset_dir.name}/{constants.ASWFLayerNames.MTL}"
        ),
    }


def bind_material(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Copy a material from a file into the asset and bind it to a prim."""
    prim_path = params["prim_path"]
    material_file = authoring.library.resolve_source_file(
        params["material_file"],
        project_dir=state.project_dir,
        library_dir=state.library_dir,
        what="material file",
    )
    material_prim_path = params.get("material_prim_path")

    asset_dir, ref_prim_path = authoring.placement.require_asset_context(
        state.stage, prim_path,
    )

    materials.bind.refuse_shared_modification(
        state.stage, asset_dir, params, op_label="bind_material",
    )

    asset_local_path = authoring.placement.to_asset_local(prim_path, ref_prim_path)
    material_prim_path = materials.bind.bind_from_file(
        asset_dir=asset_dir,
        material_file=material_file,
        prim_path=asset_local_path,
        material_prim_path=material_prim_path,
    )

    state.reload_stage()
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
            f"{asset_dir.name}/{constants.ASWFLayerNames.MTL}"
        ),
    }


def remove_material(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove the material binding on a prim inside an ASWF asset."""
    prim_path = params["prim_path"]
    asset_dir, ref_prim_path = authoring.placement.require_asset_context(
        state.stage, prim_path,
    )

    asset_local_path = authoring.placement.to_asset_local(prim_path, ref_prim_path)
    materials.bind.unbind(asset_dir, asset_local_path)
    state.reload_stage()

    logger.info("Removed material from %s", prim_path)
    return {
        "prim_path": prim_path,
        "asset_folder": asset_dir.name,
        "message": f"Removed material binding from {prim_path}",
    }


def list_materials(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every material across the project's asset folders."""
    del params
    assets_dir = state.resolve_assets_dir()
    all_materials: list[dict] = []

    for entry in authoring.asset_folder.folders_with_layer(
        assets_dir, constants.ASWFLayerNames.MTL,
    ):
        folder_materials = materials.layer.list_with_bindings(entry)
        for mat in folder_materials:
            mat["asset_folder"] = entry.name
        all_materials.extend(folder_materials)

    return {
        "material_count": len(all_materials),
        "materials": all_materials,
        "message": f"Scene has {len(all_materials)} material(s).",
    }


def cleanup_unused_materials(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Delete material definitions no prim binds to, per asset or project-wide."""
    asset_prim_path = params.get("asset_prim_path")

    if asset_prim_path:
        asset_dir, _ = authoring.placement.require_asset_context(state.stage, asset_prim_path)

        removed = materials.layer.remove_unused(asset_dir)
        state.reload_stage()
        logger.info(
            "Cleaned %d unused material(s) from %s", len(removed), asset_dir.name,
        )
        return {
            "asset_folder": asset_dir.name,
            "removed_count": len(removed),
            "removed": removed,
            "message": (
                f"Removed {len(removed)} unused material(s) from {asset_dir.name}."
            ),
        }

    assets_dir = state.resolve_assets_dir()
    per_folder: list[dict[str, Any]] = []
    total = 0
    for entry in authoring.asset_folder.folders_with_layer(
        assets_dir, constants.ASWFLayerNames.MTL,
    ):
        removed = materials.layer.remove_unused(entry)
        if removed:
            per_folder.append({"asset_folder": entry.name, "removed": removed})
            total += len(removed)

    state.reload_stage()
    logger.info(
        "Cleaned %d unused material(s) across %d asset folder(s)",
        total, len(per_folder),
    )
    return {
        "total_removed": total,
        "per_folder": per_folder,
        "message": (
            f"Removed {total} unused material(s) across "
            f"{len(per_folder)} asset folder(s)."
        ),
    }


