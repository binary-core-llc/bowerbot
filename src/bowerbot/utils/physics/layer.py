# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The asset's ``phy.usda``: its path, making one checked edit to it, removing it once empty."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from pathlib import Path

from pxr import Usd

from bowerbot import constants
from bowerbot.utils import authoring
from bowerbot.utils import physics


def file_path(asset_dir: Path) -> Path:
    """Path to the asset's ``phy.usda``."""
    return asset_dir / constants.ASWFLayerNames.PHY


@contextlib.contextmanager
def edit(
    asset_dir: Path, scene_stage: Usd.Stage, doing: str,
) -> Generator[Usd.Stage, None, None]:
    """Open ``phy.usda`` for one edit: saved on exit, dropped whole if it fails or is refused."""
    known = physics.rules.errors(scene_stage)
    authoring.asset_folder.ensure_over_layer(asset_dir, constants.ASWFLayerNames.PHY)
    authoring.asset_folder.ensure_root_reference(asset_dir, constants.ASWFLayerNames.PHY)
    stage = Usd.Stage.Open(str(file_path(asset_dir)))
    try:
        yield stage
        physics.rules.refuse_new_errors(scene_stage, known, doing)
    except Exception:
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
