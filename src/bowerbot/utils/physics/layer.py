# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The asset's ``phy.usda``: its path, opening it for an edit, saving, removing it once empty."""

from __future__ import annotations

from pathlib import Path

from pxr import Usd

from bowerbot import constants
from bowerbot.utils import authoring
from bowerbot.utils import physics


def file_path(asset_dir: Path) -> Path:
    """Path to the asset's ``phy.usda``."""
    return asset_dir / constants.ASWFLayerNames.PHY


def open_for_edit(asset_dir: Path) -> Usd.Stage:
    """Open ``phy.usda`` as a stage, creating it and the asset root's reference to it if missing.

    The reference is made first, while the file has no edit: the scene then
    shows the edit before it is saved, which is what ``save_edit`` checks.
    """
    authoring.asset_folder.ensure_over_layer(asset_dir, constants.ASWFLayerNames.PHY)
    authoring.asset_folder.ensure_root_reference(asset_dir, constants.ASWFLayerNames.PHY)
    return Usd.Stage.Open(str(file_path(asset_dir)))


def save_edit(
    asset_dir: Path, stage: Usd.Stage, scene_stage: Usd.Stage, known: set[str], doing: str,
) -> None:
    """Save an edit made to ``phy.usda``.

    An edit that gives the scene a physics error it did not have (*known*)
    is dropped instead, and refused.
    """
    try:
        physics.rules.refuse_new_errors(scene_stage, known, doing)
    except ValueError:
        stage.GetRootLayer().Reload(force=True)
        cleanup_if_empty(asset_dir)
        raise
    stage.Save()


def cleanup_if_empty(asset_dir: Path) -> bool:
    """Delete ``phy.usda`` and drop its reference when no opinions remain."""
    phy_path = file_path(asset_dir)
    if not phy_path.exists():
        return False
    if physics.summary.summarize_asset(asset_dir).prims:
        return False

    authoring.asset_folder.delete_side_layer(asset_dir, constants.ASWFLayerNames.PHY)
    return True
