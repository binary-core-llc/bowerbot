# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scene integrity invariant: no rel target points at a missing prim."""

from __future__ import annotations

import logging
from typing import Any

from pxr import Sdf, Usd

logger = logging.getLogger(__name__)


def scrub_dangling_refs(stage: Usd.Stage) -> dict[str, Any]:
    """Drop every root-layer rel target whose composed prim no longer exists."""
    layer = stage.GetRootLayer()
    touched = _walk_root_layer_rels(layer, _drop_missing(stage))
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
