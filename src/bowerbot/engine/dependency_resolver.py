# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Dependency resolver — walks USD file dependency trees to collect
all referenced assets.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Sdf, Usd, UsdShade

logger = logging.getLogger(__name__)


class DependencyResolver:
    """Walks a USD file's dependency tree and returns all required files."""

    def resolve(
        self, root_path: str | Path,
    ) -> tuple[list[Path], list[Path]]:
        """Return all files needed by *root_path*, including itself.

        Walks sublayers, references, and payloads recursively.
        Guards against circular dependencies and missing files.

        Returns a tuple of (found, missing) — both as absolute paths.
        The caller can reconstruct relative structure by comparing
        each path to root_path's parent.
        """
        root = Path(root_path).resolve()
        if not root.exists():
            logger.warning("Root file does not exist: %s", root)
            return [], [root]

        visited: set[Path] = set()
        found: list[Path] = []
        missing: list[Path] = []
        self._walk(root, visited, found, missing)
        return found, missing

    def _walk(
        self,
        file_path: Path,
        visited: set[Path],
        found: list[Path],
        missing: list[Path],
    ) -> None:
        """Recursively walk a single USD layer's dependencies."""
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

        # Walk sublayers
        for sub_path in layer.subLayerPaths:
            abs_sub = (parent_dir / sub_path).resolve()
            self._walk(abs_sub, visited, found, missing)

        # Walk references and payloads on every prim
        self._walk_prim_arcs(layer.pseudoRoot, parent_dir, visited, found, missing)

    def _walk_prim_arcs(
        self,
        prim_spec: Sdf.PrimSpec,
        parent_dir: Path,
        visited: set[Path],
        found: list[Path],
        missing: list[Path],
    ) -> None:
        """Walk references and payloads on a prim spec and its children."""
        if prim_spec is None:
            return

        # References
        refs = prim_spec.referenceList
        for list_op in (refs.prependedItems, refs.appendedItems, refs.explicitItems):
            for ref in list_op:
                if ref.assetPath:
                    abs_ref = (parent_dir / ref.assetPath).resolve()
                    self._walk(abs_ref, visited, found, missing)

        # Payloads
        payloads = prim_spec.payloadList
        for list_op in (payloads.prependedItems, payloads.appendedItems, payloads.explicitItems):
            for payload in list_op:
                if payload.assetPath:
                    abs_payload = (parent_dir / payload.assetPath).resolve()
                    self._walk(abs_payload, visited, found, missing)

        # Recurse into child prims
        for child in prim_spec.nameChildren:
            self._walk_prim_arcs(child, parent_dir, visited, found, missing)

    def validate_asset_folder(
        self, root_path: str | Path,
    ) -> tuple[bool, list[str]]:
        """Validate an ASWF asset folder is complete.

        Checks:
        - Root file exists and its stem matches the parent folder name
        - All sublayers resolve (geo.usd, mtl.usd)
        - All references within sublayers resolve

        Returns ``(is_valid, list_of_error_messages)``.
        """
        root = Path(root_path).resolve()
        errors: list[str] = []

        if not root.exists():
            return False, [f"Root file not found: {root}"]

        # Check ASWF naming convention
        if root.stem != root.parent.name:
            errors.append(
                f"Root file '{root.name}' does not match "
                f"folder name '{root.parent.name}'"
            )

        # Walk all dependencies
        found, missing = self.resolve(root)
        for m in missing:
            try:
                rel = m.relative_to(root.parent)
            except ValueError:
                rel = Path(m.name)
            errors.append(f"Missing dependency: {rel}")

        return len(errors) == 0, errors

    @staticmethod
    def find_first_material(file_path: str | Path) -> str | None:
        """Return the prim path of the first Material defined in a USD file.

        Opens the file as a stage to traverse the composed prim hierarchy.
        Returns None if no Material prim is found.
        """
        stage = Usd.Stage.Open(str(file_path))
        if stage is None:
            return None
        for prim in stage.Traverse():
            if prim.IsA(UsdShade.Material):
                return str(prim.GetPath())
        return None
