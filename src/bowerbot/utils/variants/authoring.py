# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant authoring — the edit context every variant is authored in."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pxr import Sdf, Usd

from bowerbot.schemas import ASWFLayerNames
from bowerbot.utils.core.asset_folder import ensure_side_layer


def open_variants_stage(asset_dir: Path) -> Usd.Stage:
    """Open ``variants.usda`` as a stage."""
    path = ensure_side_layer(asset_dir, ASWFLayerNames.VARIANTS)
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise RuntimeError(f"Failed to open variants layer: {path}")
    return stage


def author_in_variant(
    stage: Usd.Stage,
    prim_path: str,
    set_name: str,
    variant_name: str,
    author_fn: Callable[[Usd.Stage, str], None],
) -> None:
    """Run ``author_fn(stage, prim_path)`` inside the variant's edit context."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")

    vset = prim.GetVariantSets().GetVariantSet(set_name)
    if not vset.IsValid():
        vset = prim.GetVariantSets().AddVariantSet(set_name)
    if variant_name not in vset.GetVariantNames():
        vset.AddVariant(variant_name)

    vset.SetVariantSelection(variant_name)
    with vset.GetVariantEditContext():
        author_fn(stage, prim_path)
    vset.ClearVariantSelection()
    stage.Save()


def scrub_variant_set_metadata(prim_spec: Sdf.PrimSpec, set_name: str) -> None:
    """Remove ``set_name`` from every variantSetNameList slot."""
    name_list = prim_spec.variantSetNameList
    for items in (
        name_list.prependedItems,
        name_list.appendedItems,
        name_list.addedItems,
        name_list.explicitItems,
        name_list.orderedItems,
    ):
        if set_name in items:
            items.remove(set_name)
    if set_name in name_list.deletedItems:
        name_list.deletedItems.remove(set_name)
