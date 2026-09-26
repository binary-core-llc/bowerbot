# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant suspects — variant sets whose variants no longer differ."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pxr import Sdf, Usd

from bowerbot.schemas import ASWFLayerNames
from bowerbot.utils.core.asset_folder import resolve_default_prim_name


def find_suspect_variant_sets(
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


def suspect_variant_sets_on_scene_carrier(
    stage: Usd.Stage, base_prim_path: str,
) -> list[dict[str, Any]]:
    """Return suspect scene-level variant sets walking ancestors of *base_prim_path*."""
    if stage is None or not base_prim_path or base_prim_path == "/":
        return []
    pairs = find_suspect_variant_sets(stage.GetRootLayer(), base_prim_path)
    return [
        {"carrier_prim_path": c, "variant_set": v, "scope": "scene"}
        for c, v in pairs
    ]


def suspect_variant_sets_in_asset(
    asset_dir: Path, base_prim_path: str | None = None,
) -> list[dict[str, Any]]:
    """Return suspect asset-level variant sets walking ancestors of *base_prim_path*."""
    variants_path = asset_dir / ASWFLayerNames.VARIANTS
    if not variants_path.exists():
        return []
    variants_layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if variants_layer is None:
        return []
    default_prim = resolve_default_prim_name(asset_dir)
    base = base_prim_path or f"/{default_prim}"
    pairs = find_suspect_variant_sets(variants_layer, base)
    return [
        {
            "asset_path": str(asset_dir), "variant_set": v,
            "scope": "asset", "carrier_prim_path": c,
        }
        for c, v in pairs
    ]


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


def _walk_leaf_authorings(spec: Sdf.PrimSpec, accum: str) -> Iterator[tuple[Sdf.PrimSpec, str]]:
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
    info = set(spec.ListInfoKeys()) - {"specifier", "typeName"}
    return info == {"active"}
