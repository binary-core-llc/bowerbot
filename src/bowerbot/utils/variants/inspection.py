# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant inspection — variant sets, carriers and payload references."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf, Usd

from bowerbot.schemas import (
    ASWFLayerNames,
    SceneVariantsSummary,
    VariantCarrier,
    VariantSetSummary,
    VariantsSummary,
)
from bowerbot.utils.core.asset_folder import (
    find_root_file,
    resolve_default_prim_name,
)


def get_variant_summary(asset_dir: Path) -> VariantsSummary:
    """Return all variant sets, variants, and selections."""
    root_file = find_root_file(asset_dir)
    has_layer = (asset_dir / ASWFLayerNames.VARIANTS).exists()

    if root_file is None:
        return VariantsSummary(
            asset_path=str(asset_dir), has_variants_layer=has_layer,
        )

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return VariantsSummary(
            asset_path=str(asset_dir), has_variants_layer=has_layer,
        )
    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        return VariantsSummary(
            asset_path=str(asset_dir), has_variants_layer=has_layer,
        )

    sets = [
        _read_variant_set(root_prim, name)
        for name in root_prim.GetVariantSets().GetNames()
    ]
    return VariantsSummary(
        asset_path=str(asset_dir),
        has_variants_layer=has_layer,
        variant_sets=sets,
    )


def find_variant_carriers(
    stage: Usd.Stage,
    scene_prim_path: str,
    variant_set: str | None = None,
) -> list[VariantCarrier]:
    """Composed prims under ``scene_prim_path`` that expose variant sets."""
    root = stage.GetPrimAtPath(scene_prim_path)
    if not root or not root.IsValid():
        raise ValueError(f"Prim not found in scene: {scene_prim_path}")

    carriers: list[VariantCarrier] = []
    for prim in Usd.PrimRange(root):
        names = list(prim.GetVariantSets().GetNames())
        if not names:
            continue
        if variant_set is not None and variant_set not in names:
            continue
        carriers.append(VariantCarrier(
            prim_path=str(prim.GetPath()),
            variant_sets=[
                _read_variant_set(prim, name)
                for name in names
                if variant_set is None or name == variant_set
            ],
        ))
    return carriers


def get_scene_variants_summary(
    stage: Usd.Stage, scene_prim_path: str,
) -> SceneVariantsSummary:
    """Scene-composition view of every variant set visible under a placement."""
    return SceneVariantsSummary(
        prim_path=scene_prim_path,
        carriers=find_variant_carriers(stage, scene_prim_path),
    )


def _read_variant_set(prim: Usd.Prim, name: str) -> VariantSetSummary:
    """Read a single variant set's variants and current selection."""
    vset = prim.GetVariantSets().GetVariantSet(name)
    return VariantSetSummary(
        name=name,
        variants=list(vset.GetVariantNames()),
        selection=vset.GetVariantSelection() or None,
    )


def get_variant_payload_refs(asset_dir: Path, set_name: str) -> dict[str, str]:
    """Read each variant's authored payload asset path from variants.usda."""
    variants_path = asset_dir / ASWFLayerNames.VARIANTS
    if not variants_path.exists():
        return {}
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return {}
    default = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default}")
    if prim_spec is None:
        return {}
    vset_spec = prim_spec.variantSets.get(set_name)
    if vset_spec is None:
        return {}

    refs: dict[str, str] = {}
    for variant_name, variant_spec in vset_spec.variants.items():
        inner = variant_spec.primSpec
        if inner is None:
            continue
        plist = inner.payloadList
        for op in (plist.prependedItems, plist.appendedItems, plist.explicitItems):
            if op:
                refs[variant_name] = op[0].assetPath
                break
    return refs
