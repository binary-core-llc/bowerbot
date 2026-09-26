# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Overrides — scene opinions that mask asset layers, and cleanup of empty overs."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pxr import Sdf, Usd

from bowerbot.schemas import OverrideRules
from bowerbot.schemas.overrides import MaskingOpinion, OpinionKind
from bowerbot.utils.core.asset_folder import resolve_default_prim_name
from bowerbot.utils.core.references import find_asset_placements


def placement_paths(
    stage: Usd.Stage, asset_dir: Path, asset_paths: Iterable[str],
) -> list[tuple[str, str]]:
    """``(asset path, scene path)`` for each asset-local path on every placement of *asset_dir*."""
    placements = find_asset_placements(stage, asset_dir)
    if not placements:
        return []
    asset_prefix = f"/{resolve_default_prim_name(asset_dir)}"
    pairs: list[tuple[str, str]] = []
    for asset_path in asset_paths:
        tail = asset_path[len(asset_prefix):] if asset_path.startswith(asset_prefix) else asset_path
        pairs.extend((asset_path, f"{p}{tail}" if tail else p) for p in placements)
    return pairs


def find_masking_opinions(
    stage: Usd.Stage,
    targets: Iterable[tuple[str, OpinionKind, Iterable[str]]],
) -> list[MaskingOpinion]:
    """Scene-layer opinions authored at each ``(scene path, kind, keys)`` target."""
    layer = stage.GetRootLayer()
    found: list[MaskingOpinion] = []
    for scene_path, kind, keys in targets:
        spec = layer.GetPrimAtPath(scene_path)
        if spec is None:
            continue
        for key in keys:
            if _has_opinion(spec, kind, key):
                found.append((scene_path, kind, key))
    return found


def clear_masking_opinions(stage: Usd.Stage, opinions: list[MaskingOpinion]) -> None:
    """Remove *opinions* from the stage's root layer, pruning overs they leave empty."""
    layer = stage.GetRootLayer()
    touched: set[str] = set()
    for prim_path, kind, key in opinions:
        spec = layer.GetPrimAtPath(prim_path)
        if spec is None:
            continue
        if kind == "active":
            spec.ClearInfo("active")
        else:
            container = spec.attributes if kind == "attribute" else spec.relationships
            prop_spec = container.get(key)
            if prop_spec is not None:
                spec.RemoveProperty(prop_spec)
        touched.add(prim_path)
    for prim_path in touched:
        prune_empty_overrides(layer, prim_path)
    if touched:
        layer.Save()


def settle_masking(
    stage: Usd.Stage,
    masking: list[MaskingOpinion],
    *,
    clear: bool,
    confirm: bool,
    refusal: str,
) -> bool:
    """Clear *masking*, accept it, or refuse with *refusal*; True when opinions were cleared."""
    if not masking:
        return False
    if clear:
        clear_masking_opinions(stage, masking)
        return True
    if confirm:
        return False
    raise ValueError(refusal)


def _has_opinion(spec: Sdf.PrimSpec, kind: OpinionKind, key: str) -> bool:
    """Whether *spec* authors an opinion of *kind* at *key*."""
    if kind == "attribute":
        return key in spec.attributes
    if kind == "relationship":
        return key in spec.relationships
    return bool(spec.HasInfo("active"))


def prune_empty_overrides(layer: Sdf.Layer, prim_path: str) -> None:
    """Walk up from *prim_path*, removing any fully-empty SpecifierOver spec."""
    path = Sdf.Path(prim_path)
    while path != Sdf.Path.absoluteRootPath:
        spec = layer.GetPrimAtPath(path)
        if spec is None:
            return
        if not _is_empty_override(spec):
            return
        parent_path = path.GetParentPath()
        edit = Sdf.BatchNamespaceEdit()
        edit.Add(path, Sdf.Path.emptyPath)
        if not layer.Apply(edit):
            return
        path = parent_path


def _is_empty_override(spec: Sdf.PrimSpec) -> bool:
    """An ``over`` with no authored content; safe to delete."""
    if spec.specifier != Sdf.SpecifierOver:
        return False
    if spec.typeName:
        return False
    if len(spec.attributes) or len(spec.relationships) or len(spec.nameChildren):
        return False
    if len(spec.variantSets) or len(spec.variantSelections):
        return False
    for arc in (
        spec.referenceList, spec.payloadList,
        spec.inheritPathList, spec.specializesList,
    ):
        if (
            arc.prependedItems or arc.appendedItems
            or arc.addedItems or arc.explicitItems
            or arc.deletedItems
        ):
            return False
    authored = set(spec.ListInfoKeys()) - OverrideRules.INTRINSIC_INFO_KEYS
    return not authored


def clear_orphan_variant_overs(
    layer: Sdf.Layer, removed_prim_path: str,
) -> bool:
    """Clear orphan variant-body specs at *removed_prim_path*, cascading empties."""
    target = Sdf.Path(removed_prim_path)
    if not target.IsAbsolutePath() or target == Sdf.Path.absoluteRootPath:
        return False

    touched = False
    ancestor = target.GetParentPath()
    while ancestor != Sdf.Path.absoluteRootPath and ancestor != Sdf.Path.emptyPath:
        ancestor_spec = layer.GetPrimAtPath(ancestor)
        if ancestor_spec is None:
            ancestor = ancestor.GetParentPath()
            continue
        names = str(target.MakeRelativePath(ancestor)).split("/")
        for vset_name in list(ancestor_spec.variantSets.keys()):
            vset_spec = ancestor_spec.variantSets[vset_name]
            for variant_name in list(vset_spec.variants.keys()):
                variant_spec = vset_spec.variants[variant_name]
                inner_prim = variant_spec.primSpec
                if inner_prim is None:
                    continue
                if _delete_descendant_spec(inner_prim, names):
                    touched = True
                if _is_variant_body_empty(variant_spec):
                    vset_spec.RemoveVariant(variant_spec)
                    touched = True
            if len(vset_spec.variants) == 0:
                del ancestor_spec.variantSets[vset_name]
                name_list = ancestor_spec.variantSetNameList
                for items in (
                    name_list.prependedItems,
                    name_list.appendedItems,
                    name_list.addedItems,
                    name_list.explicitItems,
                    name_list.orderedItems,
                ):
                    if vset_name in items:
                        items.remove(vset_name)
                if vset_name in name_list.deletedItems:
                    name_list.deletedItems.remove(vset_name)
                if vset_name in ancestor_spec.variantSelections:
                    del ancestor_spec.variantSelections[vset_name]
                touched = True
        ancestor = ancestor.GetParentPath()

    if touched:
        layer.Save()
    return touched


def _delete_descendant_spec(
    root_spec: Sdf.PrimSpec, name_chain: list[str],
) -> bool:
    """Delete the descendant at *name_chain*; prune empty intermediates back up to *root_spec*."""
    cursor = root_spec
    chain: list[tuple[Sdf.PrimSpec, str]] = []
    for name in name_chain[:-1]:
        if cursor is None or name not in cursor.nameChildren:
            return False
        chain.append((cursor, name))
        cursor = cursor.nameChildren[name]
    leaf_name = name_chain[-1]
    if cursor is None or leaf_name not in cursor.nameChildren:
        return False
    del cursor.nameChildren[leaf_name]
    for parent_spec, child_name in reversed(chain):
        child_spec = parent_spec.nameChildren.get(child_name)
        if child_spec is None or not _is_empty_intermediate(child_spec):
            break
        del parent_spec.nameChildren[child_name]
    return True


def _is_empty_intermediate(spec: Sdf.PrimSpec) -> bool:
    """Whether a prim spec carries no opinions and no children (safe to prune)."""
    if len(spec.nameChildren) or len(spec.attributes) or len(spec.relationships):
        return False
    info = set(spec.ListInfoKeys()) - {"specifier", "typeName"}
    return not info


def _is_variant_body_empty(variant_spec: Sdf.VariantSpec) -> bool:
    """Whether a variant body has no authored opinions left."""
    inner = variant_spec.primSpec
    if inner is None:
        return True
    if len(inner.nameChildren) or len(inner.attributes) or len(inner.relationships):
        return False
    info = set(inner.ListInfoKeys()) - {"specifier", "typeName"}
    return not info
