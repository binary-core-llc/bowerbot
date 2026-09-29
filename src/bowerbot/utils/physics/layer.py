# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The asset's ``phy.usda``: its path, creating it, dropping its reference, removing it."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf

from bowerbot import constants
from bowerbot.utils import authoring
from bowerbot.utils import physics


def file_path(asset_dir: Path) -> Path:
    """Path to the asset's ``phy.usda``."""
    return asset_dir / constants.ASWFLayerNames.PHY


def ensure(asset_dir: Path) -> Path:
    """Create ``phy.usda`` if missing."""
    path = file_path(asset_dir)
    if path.exists():
        return path

    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    layer = Sdf.Layer.CreateNew(str(path))
    layer.defaultPrim = default_prim_name
    over = Sdf.CreatePrimInLayer(layer, Sdf.Path(f"/{default_prim_name}"))
    over.specifier = Sdf.SpecifierOver
    layer.Save()
    return path


def drop_reference(asset_dir: Path) -> None:
    """Remove ``./phy.usda`` from the asset root's reference list."""
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        return
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    prim_spec = layer.GetPrimAtPath(
        f"/{authoring.asset_folder.resolve_default_prim_name(asset_dir)}",
    )
    if prim_spec is None:
        return
    target = f"./{constants.ASWFLayerNames.PHY}"
    ref_list = prim_spec.referenceList
    for items in (
        ref_list.prependedItems,
        ref_list.appendedItems,
        ref_list.addedItems,
        ref_list.explicitItems,
        ref_list.orderedItems,
    ):
        for r in [x for x in items if x.assetPath == target]:
            items.remove(r)
    layer.Save()


def cleanup_if_empty(asset_dir: Path) -> bool:
    """Delete ``phy.usda`` and drop its reference when no opinions remain."""
    phy_path = file_path(asset_dir)
    if not phy_path.exists():
        return False
    if physics.summary.summarize_asset(asset_dir).prims:
        return False

    drop_reference(asset_dir)
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is not None:
        layer.Clear()
    phy_path.unlink()
    return True
