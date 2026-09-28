# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Finding the asset folder behind a scene prim, and mapping prim paths into it.

The asset folder itself (root file, layers, building one) is in
``authoring.asset_folder``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Usd

from bowerbot import constants
from bowerbot import utils
from bowerbot.utils import authoring
from bowerbot.utils import usd

logger = logging.getLogger(__name__)


# ── Folder structure ──


def resolve_asset_file_path(
    raw: str,
    project_dir: Path | None,
    library_dir: Path | None,
) -> Path:
    """Resolve a relative asset path against project dir, then library dir."""
    p = Path(raw)
    if p.is_absolute():
        return p
    if project_dir is not None:
        candidate = project_dir / p
        if candidate.exists():
            return candidate
    if library_dir is not None:
        candidate = library_dir / p
        if candidate.exists():
            return candidate
    return p.resolve()


def resolve_asset_dir_for_prim(
    stage: Usd.Stage,
    prim_path: str,
) -> tuple[Path | None, str | None]:
    """Find the outer ASWF asset folder backing *prim_path* in *stage*."""
    # Resolution is rooted at stage_dir (project root) on purpose: nested
    # refs in contents.usda are authored relative to that layer
    # (../sibling_asset/...) and resolve to a nonexistent path here, so
    # they are skipped and the walk continues to the outer container's
    # scene-level reference. That is the routing target move/remove/freeze
    # need.
    stage_dir = Path(stage.GetRootLayer().realPath).parent

    def _check(prim: Usd.Prim) -> tuple[Path | None, str | None]:
        for ref_path in usd.references.get_prim_ref_paths(prim):
            resolved = (stage_dir / ref_path).resolve()
            if not resolved.exists() or not resolved.parent.is_dir():
                continue
            folder = resolved.parent
            for ext in constants.AssetFolderRules.USD_LAYER_EXTENSIONS:
                if resolved.name == f"{folder.name}{ext}":
                    return folder, str(prim.GetPath())
        return None, None

    target = stage.GetPrimAtPath(prim_path)
    if target and target.IsValid():
        result = _check(target)
        if result[0] is not None:
            return result
        for child in target.GetChildren():
            result = _check(child)
            if result[0] is not None:
                return result

    parts = prim_path.strip("/").split("/")
    for i in range(len(parts) - 1, 0, -1):
        ancestor_path = "/" + "/".join(parts[:i])
        prim = stage.GetPrimAtPath(ancestor_path)
        if not prim or not prim.IsValid():
            continue
        result = _check(prim)
        if result[0] is not None:
            return result
        for child in prim.GetChildren():
            result = _check(child)
            if result[0] is not None:
                return result

    return None, None


def require_asset_context(
    stage: Usd.Stage, prim_path: str,
) -> tuple[Path, str]:
    """Resolve the asset folder + reference prim path; raise if neither is found."""
    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(stage, prim_path)
    if asset_dir is None or ref_prim_path is None:
        raise ValueError(
            f"Cannot find ASWF asset folder for {prim_path}. "
            "Operation only works on assets placed as ASWF folders (not USDZ).",
        )
    return asset_dir, ref_prim_path


def compute_ref_asset_path(
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


def to_asset_local(prim_path: str, ref_prim_path: str) -> str:
    """Strip the scene-side reference prefix to get an asset-local path."""
    if prim_path.startswith(ref_prim_path):
        remainder = prim_path[len(ref_prim_path):]
        return remainder if remainder else "/"
    return prim_path


def check_shared_modification(
    stage: Usd.Stage, asset_dir: Path, params: dict, *, op_label: str,
) -> None:
    """Refuse if *asset_dir* is referenced by 2+ scene instances and not confirmed."""
    instance_count = utils.stage.count_scene_refs_to_asset_dir(stage, asset_dir)
    confirmed = bool(params.get("confirm_shared_modification", False))
    if instance_count >= 2 and not confirmed:
        msg = (
            f"Asset folder '{asset_dir.name}/' is referenced by "
            f"{instance_count} scene instances. {op_label} writes to the "
            f"shared {constants.ASWFLayerNames.MTL}, so the binding would apply to "
            f"all {instance_count} instances. Two ways forward: "
            f"(1) For per-instance materials (different material per "
            f"instance), use place_asset to make each instance independent, "
            f"then bind a material on each. "
            f"(2) For deliberate shared modification (every instance "
            f"should get this material), retry with "
            f"confirm_shared_modification=true."
        )
        raise ValueError(msg)


def normalize_asset_prim_path(
    prim_path: str, ref_prim_path: str, default_prim_name: str,
) -> str:
    """Strip the scene namespace then anchor under the asset's default prim."""
    if prim_path == ref_prim_path:
        return f"/{default_prim_name}"
    if prim_path.startswith(f"{ref_prim_path}/"):
        return authoring.asset_folder.to_layer_local_path(
            prim_path[len(ref_prim_path):], default_prim_name,
        )
    return authoring.asset_folder.to_layer_local_path(prim_path, default_prim_name)
