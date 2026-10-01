# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD variant sets: author inside a variant, read, select and remove variant sets.

Opinion-agnostic: anything USD can author into a variant goes through
``author_in_variant``.
"""

from __future__ import annotations

from collections.abc import Callable

from pxr import Sdf
from pxr import Usd

from bowerbot import schemas
from bowerbot.utils import usd

# ── Authoring inside a variant ──


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

# ── Reading variant sets ──


def find_variant_carriers(
    stage: Usd.Stage,
    scene_prim_path: str,
    variant_set: str | None = None,
) -> list[schemas.VariantCarrier]:
    """Composed prims under ``scene_prim_path`` that expose variant sets."""
    root = stage.GetPrimAtPath(scene_prim_path)
    if not root or not root.IsValid():
        raise ValueError(f"Prim not found in scene: {scene_prim_path}")

    carriers: list[schemas.VariantCarrier] = []
    for prim in Usd.PrimRange(root):
        names = list(prim.GetVariantSets().GetNames())
        if not names:
            continue
        if variant_set is not None and variant_set not in names:
            continue
        carriers.append(schemas.VariantCarrier(
            prim_path=str(prim.GetPath()),
            variant_sets=[
                read_variant_set(prim, name)
                for name in names
                if variant_set is None or name == variant_set
            ],
        ))
    return carriers


def get_scene_variants_summary(
    stage: Usd.Stage, scene_prim_path: str,
) -> schemas.SceneVariantsSummary:
    """Scene-composition view of every variant set visible under a prim."""
    return schemas.SceneVariantsSummary(
        prim_path=scene_prim_path,
        carriers=find_variant_carriers(stage, scene_prim_path),
    )


def read_variant_set(prim: Usd.Prim, name: str) -> schemas.VariantSetSummary:
    """Read a single variant set's variants and current selection."""
    vset = prim.GetVariantSets().GetVariantSet(name)
    return schemas.VariantSetSummary(
        name=name,
        variants=list(vset.GetVariantNames()),
        selection=vset.GetVariantSelection() or None,
    )


def all_variant_set_names_in_metadata(prim_spec: Sdf.PrimSpec) -> set[str]:
    """Union of every variantSetNames list-op slot."""
    name_list = prim_spec.variantSetNameList
    return (
        set(name_list.prependedItems)
        | set(name_list.appendedItems)
        | set(name_list.addedItems)
        | set(name_list.explicitItems)
        | set(name_list.orderedItems)
    )

# ── Selecting a variant ──


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

# ── Removing variants and variant sets ──


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
    surviving = remove_variant_from_spec(layer, prim_spec, set_name, variant_name)
    if surviving is None:
        return False

    if not surviving:
        drop_variant_selection(prim_spec, set_name)
        layer.Save()
        usd.namespace.prune_empty_overrides(layer, carrier_prim_path)
        return True

    if prim_spec.variantSelections.get(set_name) == variant_name:
        del prim_spec.variantSelections[set_name]

    layer.Save()
    return True


def remove_variant_from_spec(
    layer: Sdf.Layer, prim_spec: Sdf.PrimSpec, set_name: str, variant_name: str,
) -> list[str] | None:
    """Take one variant out of a set on *prim_spec*; the set goes with its last variant.

    Returns the names of the variants that remain, or None when the variant
    was not there. The layer is not saved.
    """
    vset_spec = prim_spec.variantSets.get(set_name)
    if vset_spec is None:
        return None
    existing = list(vset_spec.variants.keys())
    if variant_name not in existing:
        return None

    surviving = [v for v in existing if v != variant_name]
    temp_layer = Sdf.Layer.CreateAnonymous()
    for v in surviving:
        Sdf.CreateVariantInLayer(temp_layer, prim_spec.path, set_name, v)
        var_path = prim_spec.path.AppendVariantSelection(set_name, v)
        if layer.GetObjectAtPath(var_path) is not None:
            Sdf.CopySpec(layer, var_path, temp_layer, var_path)

    delete_variant_set(prim_spec, set_name)

    for v in surviving:
        Sdf.CreateVariantInLayer(layer, prim_spec.path, set_name, v)
        var_path = prim_spec.path.AppendVariantSelection(set_name, v)
        if temp_layer.GetObjectAtPath(var_path) is not None:
            Sdf.CopySpec(temp_layer, var_path, layer, var_path)
    return surviving


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
    delete_variant_set(prim_spec, set_name)
    drop_variant_selection(prim_spec, set_name)
    layer.Save()
    usd.namespace.prune_empty_overrides(layer, carrier_prim_path)
    return True


def delete_variant_set(prim_spec: Sdf.PrimSpec, set_name: str) -> None:
    """Delete a variant set from a prim spec, and its name from every variantSetNameList slot."""
    del prim_spec.variantSets[set_name]
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


def drop_variant_selection(prim_spec: Sdf.PrimSpec, set_name: str) -> bool:
    """Drop a prim spec's selection for *set_name*; False when it had none."""
    if set_name not in prim_spec.variantSelections:
        return False
    del prim_spec.variantSelections[set_name]
    return True
