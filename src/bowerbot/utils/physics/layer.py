# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The asset's ``phy.usda``: its path, and removing it once empty."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf

from bowerbot import constants
from bowerbot.utils import authoring
from bowerbot.utils import physics


def file_path(asset_dir: Path) -> Path:
    """Path to the asset's ``phy.usda``."""
    return asset_dir / constants.ASWFLayerNames.PHY


def cleanup_if_empty(asset_dir: Path) -> bool:
    """Delete ``phy.usda`` and drop its reference when no opinions remain."""
    phy_path = file_path(asset_dir)
    if not phy_path.exists():
        return False
    if physics.summary.summarize_asset(asset_dir).prims:
        return False

    authoring.asset_folder.drop_root_reference(asset_dir, constants.ASWFLayerNames.PHY)
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is not None:
        layer.Clear()
    phy_path.unlink()
    return True
