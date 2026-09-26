# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scene variants — lighting and model-selection variants authored in scene.usda."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pxr import Sdf, Usd

from bowerbot.schemas import (
    SceneNamespace,
)
from bowerbot.utils.core.overrides import (
    prune_empty_overrides,
)
from bowerbot.utils.core.references import find_asset_placements
from bowerbot.utils.variants.authoring import author_in_variant, scrub_variant_set_metadata


def apply_scene_variant(
    stage: Usd.Stage,
    carrier_prim_path: str,
    variant_set: str,
    variant_name: str,
    author_fn: Callable[[Usd.Stage, str], None],
    set_as_default: bool = False,
) -> None:
    """Author a scene-level variant on a carrier prim; preserve prior default unless overridden."""
    prior_selection = ""
    prim = stage.GetPrimAtPath(carrier_prim_path)
    if prim and prim.IsValid():
        vset = prim.GetVariantSets().GetVariantSet(variant_set)
        if vset.IsValid():
            prior_selection = vset.GetVariantSelection() or ""

    author_in_variant(
        stage, carrier_prim_path, variant_set, variant_name, author_fn,
    )

    prim = stage.GetPrimAtPath(carrier_prim_path)
    if not prim or not prim.IsValid():
        return
    if not prim.GetVariantSets().GetVariantSet(variant_set).IsValid():
        return

    if set_as_default:
        target = variant_name
    elif prior_selection:
        target = prior_selection
    else:
        target = variant_name
    set_scene_variant_default(
        stage, carrier_prim_path, variant_set, target,
    )


def set_scene_variant_default(
    stage: Usd.Stage,
    carrier_prim_path: str,
    set_name: str,
    variant_name: str,
) -> None:
    """Author a variant selection on a scene carrier prim."""
    prim = stage.GetPrimAtPath(carrier_prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Carrier prim not found: {carrier_prim_path}")
    vset = prim.GetVariantSets().GetVariantSet(set_name)
    if not vset.IsValid():
        raise ValueError(
            f"Variant set '{set_name}' not on {carrier_prim_path}",
        )
    vset.SetVariantSelection(variant_name)
    stage.Save()


def clear_scene_variant_default(
    stage: Usd.Stage, carrier_prim_path: str, set_name: str,
) -> None:
    """Clear the variant selection on a scene carrier prim."""
    layer = stage.GetRootLayer()
    prim_spec = layer.GetPrimAtPath(carrier_prim_path)
    if prim_spec is None:
        return
    if set_name in prim_spec.variantSelections:
        del prim_spec.variantSelections[set_name]
        layer.Save()


def remove_scene_variant(
    stage: Usd.Stage,
    carrier_prim_path: str,
    set_name: str,
    variant_name: str,
) -> bool:
    """Remove one variant from a scene-level variant set on a carrier prim."""
    layer = stage.GetRootLayer()
    prim_spec = layer.GetPrimAtPath(carrier_prim_path)
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
        if set_name in prim_spec.variantSelections:
            del prim_spec.variantSelections[set_name]
        layer.Save()
        prune_empty_overrides(layer, carrier_prim_path)
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

    if prim_spec.variantSelections.get(set_name) == variant_name:
        del prim_spec.variantSelections[set_name]

    layer.Save()
    return True


def remove_scene_variant_set(
    stage: Usd.Stage, carrier_prim_path: str, set_name: str,
) -> bool:
    """Remove an entire variant set from a scene carrier prim."""
    layer = stage.GetRootLayer()
    prim_spec = layer.GetPrimAtPath(carrier_prim_path)
    if prim_spec is None:
        return False
    if set_name not in prim_spec.variantSets:
        return False
    del prim_spec.variantSets[set_name]
    scrub_variant_set_metadata(prim_spec, set_name)
    if set_name in prim_spec.variantSelections:
        del prim_spec.variantSelections[set_name]
    layer.Save()
    prune_empty_overrides(layer, carrier_prim_path)
    return True


def require_scene_lighting_carrier(stage: Usd.Stage) -> str:
    """Return the lighting carrier path or raise if it does not exist yet."""
    if stage is None:
        raise ValueError("No scene stage is open.")
    carrier = SceneNamespace.LIGHTING
    prim = stage.GetPrimAtPath(carrier)
    if not prim or not prim.IsValid():
        raise ValueError(
            f"No lighting carrier at {carrier}. Create at least one scene "
            "light before authoring a lighting variant.",
        )
    return carrier


def clear_scene_variant_selections(
    stage: Usd.Stage,
    asset_dir: Path,
    set_name: str,
    variant_name: str | None = None,
) -> int:
    """Drop ``variantSelections[set_name]`` from every placement of the asset.

    When *variant_name* is given, only drop selections whose current value
    matches it. Prunes empty over ancestors left behind on each touched
    placement. Returns the number of placements scrubbed.
    """
    placements = find_asset_placements(stage, asset_dir)
    if not placements:
        return 0
    layer = stage.GetRootLayer()
    scrubbed = 0
    for placement in placements:
        spec = layer.GetPrimAtPath(placement)
        if spec is None:
            continue
        sels = spec.variantSelections
        if set_name not in sels:
            continue
        if variant_name is not None and sels[set_name] != variant_name:
            continue
        del sels[set_name]
        scrubbed += 1
        prune_empty_overrides(layer, placement)
    if scrubbed:
        layer.Save()
    return scrubbed


def restore_active_scene_variant_references_to_direct_ref(
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


def has_direct_references(stage: Usd.Stage, prim_path: str) -> bool:
    """Whether *prim_path* has any directly-authored reference arc in scene.usda."""
    layer = stage.GetRootLayer()
    spec = layer.GetPrimAtPath(prim_path)
    if spec is None:
        return False
    return spec.HasInfo("references")


def clear_direct_references(stage: Usd.Stage, prim_path: str) -> None:
    """Remove all directly-authored reference arcs at *prim_path* in scene.usda."""
    layer = stage.GetRootLayer()
    spec = layer.GetPrimAtPath(prim_path)
    if spec is None:
        return
    if spec.HasInfo("references"):
        spec.ClearInfo("references")
        layer.Save()
