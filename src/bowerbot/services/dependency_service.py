# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Dependency service — walk a USD file's dependency tree."""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Sdf

logger = logging.getLogger(__name__)


def resolve(root_path: str | Path) -> tuple[list[Path], list[Path]]:
    """Return all files needed by *root_path*, including itself.

    Walks sublayers, references, and payloads recursively. Guards
    against cycles and missing files. Returns ``(found, missing)``
    as absolute paths; callers can reconstruct relative layout by
    comparing each path to ``root_path.parent``.
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


def validate_asset_folder(
    root_path: str | Path,
) -> tuple[bool, list[str]]:
    """Validate that an ASWF asset folder is complete.

    Checks that the root file exists, its stem matches the folder
    name, and every dependency (sublayers, references, payloads)
    resolves to a real file on disk.
    """
    root = Path(root_path).resolve()
    errors: list[str] = []

    if not root.exists():
        return False, [f"Root file not found: {root}"]

    if root.stem != root.parent.name:
        errors.append(
            f"Root file '{root.name}' does not match "
            f"folder name '{root.parent.name}'",
        )

    _, missing = resolve(root)
    for m in missing:
        try:
            rel = m.relative_to(root.parent)
        except ValueError:
            rel = Path(m.name)
        errors.append(f"Missing dependency: {rel}")

    return len(errors) == 0, errors


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
