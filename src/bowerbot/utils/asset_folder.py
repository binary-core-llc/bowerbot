# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Resolving an asset file path, and refusing material writes to a shared asset folder.

The asset folder itself is in ``authoring.asset_folder``; scene placements are
in ``authoring.placement``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Usd

from bowerbot import constants
from bowerbot.utils import authoring

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


def check_shared_modification(
    stage: Usd.Stage, asset_dir: Path, params: dict, *, op_label: str,
) -> None:
    """Refuse if *asset_dir* is referenced by 2+ scene instances and not confirmed."""
    instance_count = authoring.placement.count_scene_refs_to_asset_dir(stage, asset_dir)
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


