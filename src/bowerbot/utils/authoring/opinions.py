# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scene opinions that would mask what BowerBot writes into an asset layer or a variant."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pxr import Sdf
from pxr import Usd

from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import usd

# ── Opinions on asset placements ──


def find_physics_masking_opinions(
    stage: Usd.Stage,
    asset_dir: Path,
    asset_local_path: str,
    attributes: dict[str, Any] | None = None,
    relationships: dict[str, list[str]] | None = None,
) -> list[tuple[str, str, str]]:
    """Scene opinions on placements that would mask a phy.usda write: (prim path, kind, key)."""
    attr_names = set((attributes or {}).keys())
    rel_names = set((relationships or {}).keys())
    if not attr_names and not rel_names:
        return []

    placements = authoring.placement.find_asset_placements(stage, asset_dir)
    if not placements:
        return []

    default_prim = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    asset_prefix = f"/{default_prim}"
    tail = (
        asset_local_path[len(asset_prefix):]
        if asset_local_path.startswith(asset_prefix)
        else asset_local_path
    )

    layer = stage.GetRootLayer()
    masking: list[tuple[str, str, str]] = []
    for placement in placements:
        scene_path = f"{placement}{tail}" if tail else placement
        spec = layer.GetPrimAtPath(scene_path)
        if spec is None:
            continue
        for name in attr_names:
            if name in spec.attributes:
                masking.append((scene_path, "attribute", name))
        for name in rel_names:
            if name in spec.relationships:
                masking.append((scene_path, "relationship", name))
    return masking


def clear_physics_masking_opinions(
    stage: Usd.Stage,
    masking: list[tuple[str, str, str]],
) -> None:
    """Remove every masking opinion in *masking* from scene.usda."""
    layer = stage.GetRootLayer()
    touched_paths: set[str] = set()
    for prim_path, kind, key in masking:
        spec = layer.GetPrimAtPath(prim_path)
        if spec is None:
            continue
        container = spec.attributes if kind == "attribute" else spec.relationships
        prop_spec = container.get(key)
        if prop_spec is not None:
            spec.RemoveProperty(prop_spec)
            touched_paths.add(prim_path)
    for prim_path in touched_paths:
        usd.namespace.prune_empty_overrides(layer, prim_path)
    if touched_paths:
        layer.Save()


def find_variant_masking_opinions(
    stage: Usd.Stage,
    asset_dir: Path,
    default_prim: str,
    target_map: dict[str, Iterable[str]],
    kind: schemas.OpinionKind,
) -> list[tuple[str, str]]:
    """Scene opinions that would mask a variant body opinion: (scene prim path, key) pairs.

    *target_map* maps an asset prim path to the keys the variant authors there; *kind* is
    ``attribute``, ``relationship`` or ``active``.
    """
    placements = authoring.placement.find_asset_placements(stage, asset_dir)
    if not placements:
        return []
    layer = stage.GetRootLayer()
    asset_prefix = f"/{default_prim}"
    masking: list[tuple[str, str]] = []
    for asset_path, keys in target_map.items():
        tail = (
            asset_path[len(asset_prefix):]
            if asset_path.startswith(asset_prefix)
            else asset_path
        )
        for placement in placements:
            scene_path = f"{placement}{tail}" if tail else placement
            spec = layer.GetPrimAtPath(scene_path)
            if spec is None:
                continue
            for key in keys:
                if _has_authored_opinion(spec, key, kind):
                    masking.append((scene_path, key))
    return masking


def clear_variant_masking_opinions(
    stage: Usd.Stage,
    opinions: list[tuple[str, str]],
    kind: schemas.OpinionKind,
) -> None:
    """Remove the listed masking opinions from the stage's root layer."""
    layer = stage.GetRootLayer()
    touched_paths: set[str] = set()
    for prim_path, key in opinions:
        spec = layer.GetPrimAtPath(prim_path)
        if spec is None:
            continue
        if kind == "attribute":
            attr_spec = spec.attributes.get(key)
            if attr_spec is not None:
                spec.RemoveProperty(attr_spec)
        elif kind == "relationship":
            rel_spec = spec.relationships.get(key)
            if rel_spec is not None:
                spec.RemoveProperty(rel_spec)
        elif kind == "active":
            spec.ClearInfo("active")
        touched_paths.add(prim_path)
    for prim_path in touched_paths:
        usd.namespace.prune_empty_overrides(layer, prim_path)
    layer.Save()


# ── Opinions on scene prims ──


def find_masking_scene_opinions_direct(
    stage: Usd.Stage,
    target_map: dict[str, Iterable[str]],
    kind: schemas.OpinionKind,
) -> list[tuple[str, str]]:
    """Return direct scene opinions that would mask a scene-level variant body."""
    layer = stage.GetRootLayer()
    masking: list[tuple[str, str]] = []
    for scene_path, keys in target_map.items():
        spec = layer.GetPrimAtPath(scene_path)
        if spec is None:
            continue
        for key in keys:
            if _has_authored_opinion(spec, key, kind):
                masking.append((scene_path, key))
    return masking


# ── Helpers ──


def _has_authored_opinion(
    spec: Sdf.PrimSpec, key: str, kind: schemas.OpinionKind,
) -> bool:
    """Whether *spec* has an authored opinion at *key* for the given *kind*."""
    if kind == "attribute":
        return key in spec.attributes
    if kind == "relationship":
        return key in spec.relationships
    if kind == "active":
        return spec.HasInfo("active")
    return False
