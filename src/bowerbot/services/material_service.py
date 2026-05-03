# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Material service — orchestrates material operations for the material tools."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from bowerbot.schemas import ASWFLayerNames, ProceduralMaterialParams
from bowerbot.state import SceneState
from bowerbot.utils import material_utils, stage_utils
from bowerbot.utils.asset_folder_utils import resolve_asset_dir_for_prim

logger = logging.getLogger(__name__)


def create_material(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Author a procedural MaterialX material and bind it to a prim."""
    prim_path = params["prim_path"]
    material_name = params["material_name"]

    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(state.stage, prim_path)
    if asset_dir is None or ref_prim_path is None:
        msg = (
            f"Cannot find ASWF asset folder for {prim_path}. "
            "Procedural materials only work on assets placed as ASWF "
            "folders (not USDZ)."
        )
        raise ValueError(msg)

    _check_shared_modification(state, asset_dir, params, op_label="create_material")

    asset_local_path = _to_asset_local(prim_path, ref_prim_path)
    material_params = ProceduralMaterialParams(
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

    material_prim_path = material_utils.create_procedural_material_in_folder(
        asset_dir=asset_dir,
        prim_path=asset_local_path,
        params=material_params,
    )

    state.stage = stage_utils.open_stage(state.stage_path)
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
    prim_path = params["prim_path"]
    material_file = Path(params["material_file"])
    material_prim_path = params.get("material_prim_path")

    if not material_file.exists():
        msg = f"Material file not found: {material_file}"
        raise ValueError(msg)

    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(state.stage, prim_path)
    if asset_dir is None or ref_prim_path is None:
        msg = (
            f"Cannot find ASWF asset folder for {prim_path}. "
            "Material binding only works on assets placed as ASWF "
            "folders (not USDZ)."
        )
        raise ValueError(msg)

    _check_shared_modification(state, asset_dir, params, op_label="bind_material")

    asset_local_path = _to_asset_local(prim_path, ref_prim_path)
    material_prim_path = material_utils.add_material_to_folder(
        asset_dir=asset_dir,
        material_file=material_file,
        prim_path=asset_local_path,
        material_prim_path=material_prim_path,
    )

    state.stage = stage_utils.open_stage(state.stage_path)
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
    prim_path = params["prim_path"]
    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(state.stage, prim_path)
    if asset_dir is None or ref_prim_path is None:
        msg = f"Cannot find ASWF asset folder for {prim_path}."
        raise ValueError(msg)

    asset_local_path = _to_asset_local(prim_path, ref_prim_path)
    material_utils.remove_material_binding_from_folder(asset_dir, asset_local_path)
    state.stage = stage_utils.open_stage(state.stage_path)

    logger.info("Removed material from %s", prim_path)
    return {
        "prim_path": prim_path,
        "asset_folder": asset_dir.name,
        "message": f"Removed material binding from {prim_path}",
    }


def list_materials(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every material across the project's asset folders."""
    del params
    assets_dir = state.resolve_assets_dir()
    all_materials: list[dict] = []

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
    asset_prim_path = params.get("asset_prim_path")

    if asset_prim_path:
        asset_dir, _ = resolve_asset_dir_for_prim(state.stage, asset_prim_path)
        if asset_dir is None:
            msg = (
                f"Cannot find ASWF asset folder for {asset_prim_path}. "
                "Cleanup only works on ASWF folder assets."
            )
            raise ValueError(msg)

        removed = material_utils.cleanup_unused_in_folder(asset_dir)
        state.stage = stage_utils.open_stage(state.stage_path)
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
    for entry in sorted(assets_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / ASWFLayerNames.MTL).exists():
            continue
        removed = material_utils.cleanup_unused_in_folder(entry)
        if removed:
            per_folder.append({"asset_folder": entry.name, "removed": removed})
            total += len(removed)

    state.stage = stage_utils.open_stage(state.stage_path)
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


def _to_asset_local(prim_path: str, ref_prim_path: str) -> str:
    """Strip the scene-side reference prefix to get an asset-local path."""
    if prim_path.startswith(ref_prim_path):
        remainder = prim_path[len(ref_prim_path):]
        return remainder if remainder else "/"
    return prim_path


def _check_shared_modification(
    state: SceneState, asset_dir: Path, params: dict[str, Any], *, op_label: str,
) -> None:
    """Refuse if *asset_dir* is referenced by 2+ scene instances and not confirmed."""
    instance_count = stage_utils.count_scene_refs_to_asset_dir(
        state.stage, asset_dir,
    )
    confirmed = bool(params.get("confirm_shared_modification", False))
    if instance_count >= 2 and not confirmed:
        msg = (
            f"Asset folder '{asset_dir.name}/' is referenced by "
            f"{instance_count} scene instances. {op_label} writes to the "
            f"shared {ASWFLayerNames.MTL}, so the binding would apply to "
            f"all {instance_count} instances. Two ways forward: "
            f"(1) For per-instance materials (different material per "
            f"instance), use place_asset to make each instance independent, "
            f"then bind a material on each. "
            f"(2) For deliberate shared modification (every instance "
            f"should get this material), retry with "
            f"confirm_shared_modification=true."
        )
        raise ValueError(msg)
