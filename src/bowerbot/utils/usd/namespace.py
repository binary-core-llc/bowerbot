# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Renaming, moving and removing prims, and what must follow them.

Variant-body overs, relationship targets and empty overs are kept in step
with the prims they point at.
"""

from __future__ import annotations

from typing import Any

from pxr import Sdf
from pxr import Usd

from bowerbot import constants

# ── Renaming and moving ──


def rename_prim(stage: Usd.Stage, old_path: str, new_path: str) -> bool:
    """Rename/move a prim. Caller should reopen the stage afterwards."""
    old_prim = stage.GetPrimAtPath(old_path)
    if not old_prim.IsValid():
        msg = f"Prim not found: {old_path}"
        raise ValueError(msg)

    parent_path = str(Sdf.Path(new_path).GetParentPath())
    if parent_path and parent_path != "/":
        parent_prim = stage.GetPrimAtPath(parent_path)
        if not parent_prim.IsValid():
            stage.DefinePrim(parent_path, "Xform")

    edit = Sdf.BatchNamespaceEdit()
    edit.Add(old_path, new_path)
    success = stage.GetRootLayer().Apply(edit)
    if success:
        rename_variant_overs(stage.GetRootLayer(), old_path, new_path)
        stage.Save()
    return success


def rename_variant_overs(
    layer: Sdf.Layer, old_prim_path: str, new_prim_path: str,
) -> bool:
    """Relabel variant-body specs from *old_prim_path* to *new_prim_path*."""
    old = Sdf.Path(old_prim_path)
    new = Sdf.Path(new_prim_path)
    if not old.IsAbsolutePath() or not new.IsAbsolutePath():
        return False
    if old.GetParentPath() != new.GetParentPath():
        return False

    touched = False
    ancestor = old.GetParentPath()
    while ancestor != Sdf.Path.absoluteRootPath and ancestor != Sdf.Path.emptyPath:
        ancestor_spec = layer.GetPrimAtPath(ancestor)
        if ancestor_spec is None:
            ancestor = ancestor.GetParentPath()
            continue
        names = str(old.MakeRelativePath(ancestor)).split("/")
        for vset_name in list(ancestor_spec.variantSets.keys()):
            vset_spec = ancestor_spec.variantSets[vset_name]
            for variant_name in list(vset_spec.variants.keys()):
                inner_prim = vset_spec.variants[variant_name].primSpec
                if inner_prim is None:
                    continue
                if _rename_descendant_spec(inner_prim, names, new.name):
                    touched = True
        ancestor = ancestor.GetParentPath()

    if touched:
        layer.Save()
    return touched


def rewrite_refs(
    stage: Usd.Stage, mapping: dict[str, str],
) -> dict[str, Any]:
    """Rebase every root-layer rel target against an ``{old_path: new_path}`` map."""
    if not mapping:
        return {"rels_touched": []}
    rewrite = {Sdf.Path(o): Sdf.Path(n) for o, n in mapping.items()}
    layer = stage.GetRootLayer()
    touched = _walk_root_layer_rels(layer, _rewrite(rewrite))
    if touched:
        layer.Save()
    return {"rels_touched": touched}

# ── Removing ──


def remove_prim(stage: Usd.Stage, prim_path: str) -> bool:
    """Remove a prim, clean any orphan variant body specs, and save on success."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)

    removed = stage.RemovePrim(prim_path)
    if removed:
        clear_orphan_variant_overs(stage.GetRootLayer(), prim_path)
        stage.Save()
    return removed


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


def scrub_dangling_refs(stage: Usd.Stage) -> dict[str, Any]:
    """Drop every root-layer rel target whose composed prim no longer exists."""
    layer = stage.GetRootLayer()
    touched = _walk_root_layer_rels(layer, _drop_missing(stage))
    if touched:
        layer.Save()
    return {"rels_touched": touched}

# ── Free names ──


def unique_prim_path(stage: Usd.Stage, parent: str, base_name: str) -> str:
    """Return ``<parent>/<base_name>`` or the next free ``<parent>/<base_name>_NN``."""
    direct = f"{parent}/{base_name}"
    if not stage.GetPrimAtPath(direct).IsValid():
        return direct
    n = 2
    while True:
        candidate = f"{parent}/{base_name}_{n:02d}"
        if not stage.GetPrimAtPath(candidate).IsValid():
            return candidate
        n += 1

# ── Helpers ──


def _rename_descendant_spec(
    root_spec: Sdf.PrimSpec, name_chain: list[str], new_leaf_name: str,
) -> bool:
    """Rename the descendant prim spec at *name_chain* under *root_spec* to *new_leaf_name*."""
    cursor = root_spec
    for i, name in enumerate(name_chain):
        if cursor is None or name not in cursor.nameChildren:
            return False
        if i == len(name_chain) - 1:
            child_spec = cursor.nameChildren[name]
            child_spec.name = new_leaf_name
            return True
        cursor = cursor.nameChildren[name]
    return False


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
    info = set(spec.ListInfoKeys()) - constants.NamespaceRules.INTRINSIC_PRIM_INFO_KEYS
    return not info


def _is_variant_body_empty(variant_spec: Sdf.VariantSpec) -> bool:
    """Whether a variant body has no authored opinions left."""
    inner = variant_spec.primSpec
    return inner is None or _is_empty_intermediate(inner)


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
    authored = set(spec.ListInfoKeys()) - constants.NamespaceRules.INTRINSIC_PRIM_INFO_KEYS
    return not authored


def _drop_missing(stage: Usd.Stage):
    def policy(targets: list[Sdf.Path]) -> list[Sdf.Path]:
        return [t for t in targets if _prim_exists(stage, t)]
    return policy


def _rewrite(mapping: dict[Sdf.Path, Sdf.Path]):
    def policy(targets: list[Sdf.Path]) -> list[Sdf.Path]:
        return [_rebase(t, mapping) for t in targets]
    return policy


def _rebase(target: Sdf.Path, mapping: dict[Sdf.Path, Sdf.Path]) -> Sdf.Path:
    for old, new in mapping.items():
        if target == old:
            return new
        if target.HasPrefix(old):
            return target.ReplacePrefix(old, new)
    return target


def _prim_exists(stage: Usd.Stage, path: Sdf.Path) -> bool:
    prim_path = path.GetPrimPath() if path else path
    if not prim_path:
        return False
    prim = stage.GetPrimAtPath(prim_path)
    return bool(prim and prim.IsValid())


def _walk_root_layer_rels(layer: Sdf.Layer, policy) -> list[dict[str, Any]]:
    touched: list[dict[str, Any]] = []

    def visit(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if not isinstance(spec, Sdf.PrimSpec):
            return
        for rel_spec in spec.relationships:
            mutation = _apply(rel_spec, policy)
            if mutation is not None:
                touched.append({
                    "prim_path": str(spec.path),
                    "relationship": rel_spec.name,
                    **mutation,
                })

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return touched


def _apply(rel_spec: Sdf.RelationshipSpec, policy) -> dict[str, Any] | None:
    list_op = rel_spec.targetPathList
    before: dict[str, list[str]] = {}
    after: dict[str, list[str]] = {}
    touched = False
    for slot in ("prependedItems", "appendedItems", "explicitItems"):
        old = [Sdf.Path(p) for p in getattr(list_op, slot)]
        if not old:
            continue
        new = policy(old)
        if new != old:
            setattr(list_op, slot, [Sdf.Path(p) for p in new])
            touched = True
            before[slot] = [str(p) for p in old]
            after[slot] = [str(p) for p in new]
    if not touched:
        return None
    return {"before": before, "after": after}
