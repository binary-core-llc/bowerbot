# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""References and payloads: read and clear them, find what a layer references, walk dependencies."""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Sdf
from pxr import Usd

logger = logging.getLogger(__name__)

# ── Reading references ──


def get_prim_ref_paths(prim: Usd.Prim) -> list[str]:
    """Return all reference asset paths authored on *prim*."""
    refs = prim.GetMetadata("references")
    if not refs:
        return []
    paths: list[str] = []
    for ref_list in (
        refs.prependedItems,
        refs.appendedItems,
        refs.explicitItems,
    ):
        if not ref_list:
            continue
        for ref in ref_list:
            if ref.assetPath:
                paths.append(ref.assetPath)
    return paths


def has_direct_references(stage: Usd.Stage, prim_path: str) -> bool:
    """Whether *prim_path* has any directly-authored reference arc in the stage's root layer."""
    layer = stage.GetRootLayer()
    spec = layer.GetPrimAtPath(prim_path)
    if spec is None:
        return False
    return spec.HasInfo("references")


def layer_file_targets(layer: Sdf.Layer) -> set[Path]:
    """The files *layer* points to, as absolute paths.

    Every reference, payload and asset-valued attribute counts, also inside
    variant bodies. Paths are taken relative to the layer's own folder.
    """
    base = Path(layer.realPath).parent
    targets: set[Path] = set()

    def add(asset_path: str) -> None:
        if asset_path:
            targets.add((base / asset_path).resolve())

    def visit(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if isinstance(spec, Sdf.PrimSpec):
            for proxy in (spec.referenceList, spec.payloadList):
                for items in (
                    proxy.prependedItems,
                    proxy.appendedItems,
                    proxy.addedItems,
                    proxy.explicitItems,
                    proxy.orderedItems,
                ):
                    for arc in items:
                        add(arc.assetPath)
        elif isinstance(spec, Sdf.AttributeSpec):
            value = spec.default
            if isinstance(value, Sdf.AssetPath):
                add(value.path)
            elif isinstance(value, Sdf.AssetPathArray):
                for item in value:
                    add(item.path)

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return targets

# ── Editing references ──


def clear_direct_references(stage: Usd.Stage, prim_path: str) -> None:
    """Remove all directly-authored reference arcs at *prim_path* in the stage's root layer."""
    layer = stage.GetRootLayer()
    spec = layer.GetPrimAtPath(prim_path)
    if spec is None:
        return
    if spec.HasInfo("references"):
        spec.ClearInfo("references")
        layer.Save()

# ── Dependencies ──


def resolve_dependencies(root_path: str | Path) -> tuple[list[Path], list[Path]]:
    """Return ``(found, missing)`` absolute paths for *root_path*'s deps.

    Walks sublayers, references, and payloads recursively, guarding
    against cycles and missing files.
    """
    root = Path(root_path).resolve()
    if not root.exists():
        logger.warning("Root file does not exist: %s", root)
        return [], [root]

    visited: set[Path] = set()
    found: list[Path] = []
    missing: list[Path] = []
    _walk(root, visited, found, missing)
    return found, missing

# ── Helpers ──


def _walk(
    file_path: Path,
    visited: set[Path],
    found: list[Path],
    missing: list[Path],
) -> None:
    """Recursively walk a single layer's dependencies."""
    resolved = file_path.resolve()
    if resolved in visited:
        return
    visited.add(resolved)

    if not resolved.exists():
        logger.warning("Dependency not found: %s", resolved)
        missing.append(resolved)
        return

    found.append(resolved)

    layer = Sdf.Layer.FindOrOpen(str(resolved))
    if layer is None:
        logger.warning("Could not open layer: %s", resolved)
        return

    parent_dir = resolved.parent

    for sub_path in layer.subLayerPaths:
        _walk((parent_dir / sub_path).resolve(), visited, found, missing)

    _walk_prim_arcs(layer.pseudoRoot, parent_dir, visited, found, missing)


def _walk_prim_arcs(
    prim_spec: Sdf.PrimSpec,
    parent_dir: Path,
    visited: set[Path],
    found: list[Path],
    missing: list[Path],
) -> None:
    """Walk references and payloads on a prim spec and its children."""
    if prim_spec is None:
        return

    refs = prim_spec.referenceList
    for list_op in (refs.prependedItems, refs.appendedItems, refs.explicitItems):
        for ref in list_op:
            if ref.assetPath:
                _walk(
                    (parent_dir / ref.assetPath).resolve(),
                    visited, found, missing,
                )

    payloads = prim_spec.payloadList
    for list_op in (
        payloads.prependedItems, payloads.appendedItems, payloads.explicitItems,
    ):
        for payload in list_op:
            if payload.assetPath:
                _walk(
                    (parent_dir / payload.assetPath).resolve(),
                    visited, found, missing,
                )

    for child in prim_spec.nameChildren:
        _walk_prim_arcs(child, parent_dir, visited, found, missing)
