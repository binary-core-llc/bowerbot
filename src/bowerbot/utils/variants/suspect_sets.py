# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant sets that lost their purpose, and restoring a direct reference."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf
from pxr import Usd

from bowerbot import constants
from bowerbot.utils import authoring


def find(
    layer: Sdf.Layer, base_prim_path: str,
) -> list[tuple[str, str]]:
    """Walk ancestors of *base*; return (carrier, set) pairs for collapsed selection variants."""
    base = Sdf.Path(base_prim_path)
    if not base.IsAbsolutePath():
        return []

    suspect: list[tuple[str, str]] = []
    cursor = base
    while cursor != Sdf.Path.absoluteRootPath and cursor != Sdf.Path.emptyPath:
        spec = layer.GetPrimAtPath(cursor)
        if spec is not None:
            for vset_name in list(spec.variantSets.keys()):
                if _is_collapsed_selection_set(spec.variantSets[vset_name]):
                    suspect.append((str(cursor), vset_name))
        cursor = cursor.GetParentPath()
    return suspect


def find_on_scene_carrier(
    stage: Usd.Stage, base_prim_path: str,
) -> list[dict]:
    """Return suspect scene-level variant sets walking ancestors of *base_prim_path*."""
    if stage is None or not base_prim_path or base_prim_path == "/":
        return []
    pairs = find(stage.GetRootLayer(), base_prim_path)
    return [
        {"carrier_prim_path": c, "variant_set": v, "scope": "scene"}
        for c, v in pairs
    ]


def find_above(stage: Usd.Stage, prim_path: str) -> list[dict[str, str]]:
    """Suspect scene-level variant sets on the ancestors of *prim_path*, not the prim itself."""
    return find_on_scene_carrier(stage, str(Sdf.Path(prim_path).GetParentPath()))


def find_in_asset(
    asset_dir: Path, base_prim_path: str | None = None,
) -> list[dict]:
    """Return suspect asset-level variant sets walking ancestors of *base_prim_path*."""
    variants_path = asset_dir / constants.ASWFLayerNames.VARIANTS
    if not variants_path.exists():
        return []
    variants_layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if variants_layer is None:
        return []
    default_prim = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    base = base_prim_path or f"/{default_prim}"
    pairs = find(variants_layer, base)
    return [
        {
            "asset_path": str(asset_dir), "variant_set": v,
            "scope": "asset", "carrier_prim_path": c,
        }
        for c, v in pairs
    ]


def restore_direct_reference(
    stage: Usd.Stage, carrier_prim_path: str, set_name: str,
) -> str | None:
    """Demote a model-selection set's active variant refs back to a direct ref on its child."""
    layer = stage.GetRootLayer()
    carrier_spec = layer.GetPrimAtPath(carrier_prim_path)
    if carrier_spec is None or set_name not in carrier_spec.variantSets:
        return None
    vset_spec = carrier_spec.variantSets[set_name]
    if not vset_spec.variants:
        return None

    selection = carrier_spec.variantSelections.get(set_name)
    target_variant = (
        vset_spec.variants[selection]
        if selection and selection in vset_spec.variants
        else next(iter(vset_spec.variants.values()))
    )
    inner = target_variant.primSpec
    if inner is None or len(inner.nameChildren) != 1:
        return None
    child_name = next(iter(inner.nameChildren)).name
    child_spec = inner.nameChildren[child_name]
    if not child_spec.HasInfo("references"):
        return None

    refs: list[str] = []
    for items in (
        child_spec.referenceList.prependedItems,
        child_spec.referenceList.appendedItems,
        child_spec.referenceList.explicitItems,
    ):
        for r in items:
            if r.assetPath:
                refs.append(r.assetPath)
    if not refs:
        return None

    target_path = f"{carrier_prim_path}/{child_name}"
    target_prim = stage.GetPrimAtPath(target_path)
    if not target_prim or not target_prim.IsValid():
        return None
    for ref in refs:
        target_prim.GetReferences().AddReference(ref)
    stage.Save()
    return target_variant.name


# ── Helpers ──


def _is_collapsed_selection_set(vset_spec: Sdf.VariantSetSpec) -> bool:
    """Whether a variant set has lost its purpose (single model left, or selection on one prim)."""
    if len(vset_spec.variants) == 0:
        return False
    if len(vset_spec.variants) == 1:
        only = next(iter(vset_spec.variants.values()))
        return _variant_body_authors_references(only)
    leaf_paths: set[str] = set()
    active_only = True
    for variant_name in list(vset_spec.variants.keys()):
        inner = vset_spec.variants[variant_name].primSpec
        if inner is None:
            continue
        for leaf_spec, rel_path in _walk_leaf_authorings(inner, ""):
            leaf_paths.add(rel_path)
            if not _is_active_only_spec(leaf_spec):
                active_only = False
    return active_only and len(leaf_paths) == 1


def _variant_body_authors_references(variant_spec: Sdf.VariantSpec) -> bool:
    """Whether a variant body authors any reference arcs (model_selection style)."""
    inner = variant_spec.primSpec
    if inner is None:
        return False
    stack = [inner]
    while stack:
        spec = stack.pop()
        if spec.HasInfo("references"):
            return True
        stack.extend(spec.nameChildren)
    return False


def _walk_leaf_authorings(spec: Sdf.PrimSpec, accum: str):
    """Yield (leaf_spec, rel_path) for descendants that author direct opinions."""
    has_opinions = (
        len(spec.attributes) > 0
        or len(spec.relationships) > 0
        or "active" in set(spec.ListInfoKeys())
    )
    if has_opinions and not len(spec.nameChildren):
        yield spec, accum
        return
    for child in spec.nameChildren:
        child_rel = f"{accum}/{child.name}" if accum else child.name
        yield from _walk_leaf_authorings(child, child_rel)


def _is_active_only_spec(spec: Sdf.PrimSpec) -> bool:
    """Whether *spec* authors ONLY the ``active`` metadata (no attrs, rels, or children)."""
    if len(spec.attributes) or len(spec.relationships) or len(spec.nameChildren):
        return False
    info = set(spec.ListInfoKeys()) - constants.NamespaceRules.INTRINSIC_PRIM_INFO_KEYS
    return info == {"active"}
