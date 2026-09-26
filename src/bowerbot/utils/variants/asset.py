# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset variants — authoring, defaults and removal in an asset's variants.usda."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pxr import Sdf, Usd

from bowerbot.schemas import (
    ASWFLayerNames,
)
from bowerbot.utils.core.asset_folder import (
    asset_has_root_payload,
    clear_root_payload,
    delete_side_layer,
    ensure_root_reference,
    ensure_side_layer,
    find_root_file,
    resolve_default_prim_name,
)
from bowerbot.utils.core.naming import validate_variant_name
from bowerbot.utils.variants.authoring import (
    author_in_variant,
    open_variants_stage,
    scrub_variant_set_metadata,
)
from bowerbot.utils.variants.checks import validate_lod_namespace_stability, validate_payload_path
from bowerbot.utils.variants.inspection import get_variant_summary


def apply_variant(
    asset_dir: Path,
    variant_set: str,
    variant_name: str,
    author_fn: Callable[[Usd.Stage, str], None],
    set_as_default: bool = False,
) -> None:
    """End-to-end variant authoring: layer, reference, opinions, default selection."""
    ensure_side_layer(asset_dir, ASWFLayerNames.VARIANTS)
    ensure_root_reference(asset_dir, ASWFLayerNames.VARIANTS)
    stage = open_variants_stage(asset_dir)
    author_in_variant(
        stage, f"/{resolve_default_prim_name(asset_dir)}",
        variant_set, variant_name, author_fn,
    )

    summary = get_variant_summary(asset_dir)
    existing = next(
        (s for s in summary.variant_sets if s.name == variant_set), None,
    )
    needs_default = set_as_default or (existing is not None and not existing.selection)
    if needs_default:
        set_default_variant(asset_dir, variant_set, variant_name)


def setup_geometry_variant_set(
    asset_dir: Path,
    variant_set: str,
    variants: dict[str, str],
    default_variant: str,
) -> None:
    """Author a Pixar-pattern LOD variant set: clear root payload, payloads inside variants."""
    if not variants:
        raise ValueError("setup_geometry_variant_set requires at least one variant")
    if default_variant not in variants:
        raise ValueError(
            f"default_variant {default_variant!r} not present in variants "
            f"{list(variants)!r}",
        )
    validate_variant_name(variant_set, "variant set")
    for name in variants:
        validate_variant_name(name)
    for payload_ref in variants.values():
        validate_payload_path(asset_dir, payload_ref)
    validate_lod_namespace_stability(asset_dir, variants)

    ensure_side_layer(asset_dir, ASWFLayerNames.VARIANTS)
    ensure_root_reference(asset_dir, ASWFLayerNames.VARIANTS)
    stage = open_variants_stage(asset_dir)
    root_prim_path = f"/{resolve_default_prim_name(asset_dir)}"

    for variant_name, payload_ref in variants.items():
        author_in_variant(
            stage, root_prim_path, variant_set, variant_name,
            _payload_setter(payload_ref),
        )

    clear_root_payload(asset_dir)
    set_default_variant(asset_dir, variant_set, default_variant)


def _payload_setter(payload_ref: str) -> Callable[[Usd.Stage, str], None]:
    """Return an author function that sets the root prim's payload."""
    def author_fn(stage: Usd.Stage, prim_path: str) -> None:
        target = stage.GetPrimAtPath(prim_path)
        target.GetPayloads().ClearPayloads()
        target.GetPayloads().AddPayload(payload_ref)
    return author_fn


def set_default_variant(
    asset_dir: Path, set_name: str, variant_name: str,
) -> None:
    """Author the default variant selection on the asset root prim."""
    root_file = find_root_file(asset_dir)
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
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return
    if set_name in prim_spec.variantSelections:
        del prim_spec.variantSelections[set_name]
        layer.Save()


def _clear_all_default_variants(asset_dir: Path) -> None:
    """Clear every variant selection on the asset root prim."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return
    if prim_spec.variantSelections:
        prim_spec.variantSelections.clear()
        layer.Save()


def remove_variant(
    asset_dir: Path, set_name: str, variant_name: str,
) -> bool:
    """Remove one variant from a variant set."""
    variants_path = asset_dir / ASWFLayerNames.VARIANTS
    if not variants_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return False
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return False

    vset_spec = prim_spec.variantSets.get(set_name)
    if vset_spec is None:
        return False
    existing = list(vset_spec.variants.keys())
    if variant_name not in existing:
        return False

    if len(existing) == 1:
        del prim_spec.variantSets[set_name]
        scrub_variant_set_metadata(prim_spec, set_name)
        layer.Save()
        return True

    surviving = [v for v in existing if v != variant_name]

    temp_layer = Sdf.Layer.CreateAnonymous()
    for v in surviving:
        Sdf.CreateVariantInLayer(temp_layer, prim_spec.path, set_name, v)
        var_path = prim_spec.path.AppendVariantSelection(set_name, v)
        if layer.GetObjectAtPath(var_path) is not None:
            Sdf.CopySpec(layer, var_path, temp_layer, var_path)

    del prim_spec.variantSets[set_name]
    scrub_variant_set_metadata(prim_spec, set_name)

    for v in surviving:
        Sdf.CreateVariantInLayer(layer, prim_spec.path, set_name, v)
        var_path = prim_spec.path.AppendVariantSelection(set_name, v)
        if temp_layer.GetObjectAtPath(var_path) is not None:
            Sdf.CopySpec(temp_layer, var_path, layer, var_path)

    layer.Save()
    return True


def remove_variant_set(asset_dir: Path, set_name: str) -> bool:
    """Remove an entire variant set."""
    variants_path = asset_dir / ASWFLayerNames.VARIANTS
    if not variants_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return False
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return False

    if set_name not in prim_spec.variantSets:
        return False

    del prim_spec.variantSets[set_name]
    scrub_variant_set_metadata(prim_spec, set_name)
    layer.Save()
    return True


def restore_canonical_geo_if_needed(asset_dir: Path) -> bool:
    """Restore ``./geo.usda`` on the asset root when no other geometry source remains."""
    if asset_has_root_payload(asset_dir):
        return False
    if _variants_have_any_payload(asset_dir):
        return False
    if not (asset_dir / ASWFLayerNames.GEO).exists():
        return False

    root_file = find_root_file(asset_dir)
    if root_file is None:
        return False
    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return False
    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        return False
    root_prim.GetPayloads().AddPayload(f"./{ASWFLayerNames.GEO}")
    stage.Save()
    return True


def _variants_have_any_payload(asset_dir: Path) -> bool:
    """Whether any variant body in ``variants.usda`` authors a payload."""
    variants_path = asset_dir / ASWFLayerNames.VARIANTS
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


def remove_variants_layer_if_empty(asset_dir: Path) -> bool:
    """Delete ``variants.usda`` and scrub references when no variant sets remain."""
    if _has_variant_sets(asset_dir):
        return False
    _clear_all_default_variants(asset_dir)
    delete_side_layer(asset_dir, ASWFLayerNames.VARIANTS)
    return True


def _has_variant_sets(asset_dir: Path) -> bool:
    """Return whether ``variants.usda`` declares any variant sets."""
    variants_path = asset_dir / ASWFLayerNames.VARIANTS
    if not variants_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return False
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return False
    return bool(prim_spec.variantSets) or bool(
        _all_variant_set_names_in_metadata(prim_spec),
    )


def _all_variant_set_names_in_metadata(prim_spec: Sdf.PrimSpec) -> set[str]:
    """Union of every variantSetNames list-op slot."""
    name_list = prim_spec.variantSetNameList
    return (
        set(name_list.prependedItems)
        | set(name_list.appendedItems)
        | set(name_list.addedItems)
        | set(name_list.explicitItems)
        | set(name_list.orderedItems)
    )
