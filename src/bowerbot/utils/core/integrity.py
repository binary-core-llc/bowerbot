# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scene integrity invariant: no rel target points at a missing prim."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pxr import Sdf, Usd

from bowerbot.utils.core.overrides import clear_orphan_variant_overs


def remove_scene_prim(stage: Usd.Stage, prim_path: str) -> dict[str, Any]:
    """Remove a prim from the scene layer and drop the rel targets it leaves dangling.

    Returns the ``{"rels_touched": [...]}`` report of the dropped targets.
    Raises ``ValueError`` if no prim is at ``prim_path`` and
    ``RuntimeError`` if the scene layer has no opinion there to remove.
    """
    if not stage.GetPrimAtPath(prim_path).IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)
    before = composed_prim_paths(stage)
    if not stage.RemovePrim(prim_path):
        msg = (
            f"Cannot remove {prim_path}: the scene layer does not define it; "
            "it is composed from another layer."
        )
        raise RuntimeError(msg)
    clear_orphan_variant_overs(stage.GetRootLayer(), prim_path)
    report = drop_refs_to_vanished(stage, before)
    stage.Save()
    return report


def composed_prim_paths(stage: Usd.Stage) -> set[Sdf.Path]:
    """Every prim the stage composes now, inactive ones included."""
    return {
        prim.GetPath()
        for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.PrimAllPrimsPredicate)
    }


def drop_refs_to_vanished(
    stage: Usd.Stage, before: set[Sdf.Path],
) -> dict[str, Any]:
    """Drop the root-layer rel targets at or under a prim of ``before`` that is gone.

    ``before`` is :func:`composed_prim_paths` taken ahead of the edit. A
    target is dropped only when the edit removed its prim or an ancestor,
    so a target into an unselected variant elsewhere is never touched.
    """
    vanished = {path for path in before if not stage.GetPrimAtPath(path).IsValid()}
    if not vanished:
        return {"rels_touched": []}
    layer = stage.GetRootLayer()
    touched = _walk_root_layer_rels(layer, _drop_under(vanished))
    if touched:
        layer.Save()
    return {"rels_touched": touched}


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


def _drop_under(
    vanished: set[Sdf.Path],
) -> Callable[[list[Sdf.Path]], list[Sdf.Path]]:
    def policy(targets: list[Sdf.Path]) -> list[Sdf.Path]:
        return [
            t for t in targets
            if not any(p in vanished for p in t.GetPrimPath().GetPrefixes())
        ]
    return policy


def _rewrite(
    mapping: dict[Sdf.Path, Sdf.Path],
) -> Callable[[list[Sdf.Path]], list[Sdf.Path]]:
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


def _walk_root_layer_rels(
    layer: Sdf.Layer, policy: Callable[[list[Sdf.Path]], list[Sdf.Path]],
) -> list[dict[str, Any]]:
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


def _apply(
    rel_spec: Sdf.RelationshipSpec, policy: Callable[[list[Sdf.Path]], list[Sdf.Path]],
) -> dict[str, Any] | None:
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
