# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""An asset's variants.usda: the layer, its variant sets and payloads, defaults, removal."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf
from pxr import Usd

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import usd

# ── The variants.usda layer ──


def variants_layer_path(asset_dir: Path) -> Path:
    """Return the canonical ``variants.usda`` path."""
    return asset_dir / constants.ASWFLayerNames.VARIANTS


# ── Opening variants.usda ──


def open_variants_stage(asset_dir: Path) -> Usd.Stage:
    """Open ``variants.usda`` as a stage."""
    path = authoring.asset_folder.ensure_over_layer(
        asset_dir, constants.ASWFLayerNames.VARIANTS,
    )
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise RuntimeError(f"Failed to open variants layer: {path}")
    return stage


# ── Reading variant sets and payloads ──


def get_variant_summary(asset_dir: Path) -> schemas.VariantsSummary:
    """Return all variant sets, variants, and selections."""
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    has_layer = variants_layer_path(asset_dir).exists()

    if root_file is None:
        return schemas.VariantsSummary(
            asset_path=str(asset_dir), has_variants_layer=has_layer,
        )

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return schemas.VariantsSummary(
            asset_path=str(asset_dir), has_variants_layer=has_layer,
        )
    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        return schemas.VariantsSummary(
            asset_path=str(asset_dir), has_variants_layer=has_layer,
        )

    sets = [
        usd.variant_sets.read_variant_set(root_prim, name)
        for name in root_prim.GetVariantSets().GetNames()
    ]
    return schemas.VariantsSummary(
        asset_path=str(asset_dir),
        has_variants_layer=has_layer,
        variant_sets=sets,
    )


def get_variant_payload_refs(asset_dir: Path, set_name: str) -> dict[str, str]:
    """Read each variant's authored payload asset path from variants.usda."""
    variants_path = variants_layer_path(asset_dir)
    if not variants_path.exists():
        return {}
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return {}
    default = authoring.asset_folder.resolve_default_prim_name(asset_dir)
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


def variants_have_any_payload(asset_dir: Path) -> bool:
    """Whether any variant body in ``variants.usda`` authors a payload."""
    variants_path = variants_layer_path(asset_dir)
    if not variants_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return False

    found = False

    def visit(path: Sdf.Path) -> None:
        nonlocal found
        if found:
            return
        spec = layer.GetPrimAtPath(path)
        if spec is None:
            return
        plist = spec.payloadList
        if (
            plist.prependedItems
            or plist.appendedItems
            or plist.addedItems
            or plist.explicitItems
        ):
            found = True

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return found


# ── Default selection on the asset root ──


def set_default_variant(
    asset_dir: Path, set_name: str, variant_name: str,
) -> None:
    """Author the default variant selection on the asset root prim."""
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        raise ValueError(f"No root file in {asset_dir}")
    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        raise RuntimeError(f"Failed to open {root_file}")
    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        raise ValueError(f"No defaultPrim in {root_file}")

    vset = root_prim.GetVariantSets().GetVariantSet(set_name)
    if not vset.IsValid():
        raise ValueError(f"Variant set '{set_name}' not visible on root prim")
    vset.SetVariantSelection(variant_name)
    stage.Save()


def clear_default_variant(asset_dir: Path, set_name: str) -> None:
    """Clear the default variant selection on the asset root prim."""
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        return
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return
    if usd.variant_sets.drop_variant_selection(prim_spec, set_name):
        layer.Save()


# ── Removing variants ──


def remove_variant(
    asset_dir: Path, set_name: str, variant_name: str,
) -> bool:
    """Remove one variant from a variant set."""
    variants_path = variants_layer_path(asset_dir)
    if not variants_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return False
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return False

    surviving = usd.variant_sets.remove_variant_from_spec(
        layer, prim_spec, set_name, variant_name,
    )
    if surviving is None:
        return False
    layer.Save()
    return True


def remove_variant_set(asset_dir: Path, set_name: str) -> bool:
    """Remove an entire variant set."""
    variants_path = variants_layer_path(asset_dir)
    if not variants_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return False
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return False

    if set_name not in prim_spec.variantSets:
        return False

    usd.variant_sets.delete_variant_set(prim_spec, set_name)
    layer.Save()
    return True


def cleanup_if_empty(asset_dir: Path) -> bool:
    """Delete ``variants.usda`` and scrub references when no variant sets remain."""
    if _has_variant_sets(asset_dir):
        return False

    _clear_all_default_variants(asset_dir)
    authoring.asset_folder.delete_side_layer(asset_dir, constants.ASWFLayerNames.VARIANTS)
    return True


# ── Helpers ──


def _clear_all_default_variants(asset_dir: Path) -> None:
    """Clear every variant selection on the asset root prim."""
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        return
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return
    if prim_spec.variantSelections:
        prim_spec.variantSelections.clear()
        layer.Save()


def _has_variant_sets(asset_dir: Path) -> bool:
    """Return whether ``variants.usda`` declares any variant sets."""
    variants_path = variants_layer_path(asset_dir)
    if not variants_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return False
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return False
    return bool(prim_spec.variantSets) or bool(
        usd.variant_sets.all_variant_set_names_in_metadata(prim_spec),
    )
