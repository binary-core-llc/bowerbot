# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Shared USD utilities.

Low-level helpers that multiple modules need. Keeps pxr
usage centralized and avoids cross-module dependencies.
"""

from __future__ import annotations

from pathlib import Path

from pxr import Usd, UsdLux

from bowerbot.schemas import LightType

# Maps LightType values to UsdLux classes. Built from the
# LightType enum so light types are defined in one place.
LIGHT_CLASSES: dict[str, type] = {
    LightType.DISTANT: UsdLux.DistantLight,
    LightType.DOME: UsdLux.DomeLight,
    LightType.SPHERE: UsdLux.SphereLight,
    LightType.RECT: UsdLux.RectLight,
    LightType.DISK: UsdLux.DiskLight,
    LightType.CYLINDER: UsdLux.CylinderLight,
}


def iter_prim_ref_paths(prim: Usd.Prim) -> list[str]:
    """Return all reference asset paths from a prim.

    Reads the reference metadata (prepended, appended, explicit)
    and returns a flat list of asset paths.
    """
    refs = prim.GetMetadata("references")
    if not refs:
        return []
    paths = []
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


def find_asset_references(
    project_dir: Path,
    folder_name: str,
    skip_dir: Path | None = None,
) -> list[str]:
    """Scan all USD files in a directory for references to an asset.

    Args:
        project_dir: Root directory to scan recursively.
        folder_name: Asset folder name to search for in references.
        skip_dir: Optional directory to exclude (e.g. the asset
            folder itself).

    Returns:
        List of relative file paths that reference the asset.
    """
    referencing_files = []

    for usd_file in project_dir.rglob("*"):
        if usd_file.suffix not in (".usd", ".usda", ".usdc"):
            continue

        if skip_dir:
            try:
                usd_file.relative_to(skip_dir)
                continue
            except ValueError:
                pass

        try:
            stage = Usd.Stage.Open(str(usd_file))
        except Exception:
            continue

        if stage is None:
            continue

        found = False
        for prim in stage.Traverse():
            for asset_path in iter_prim_ref_paths(prim):
                if folder_name in asset_path:
                    referencing_files.append(
                        str(
                            usd_file.relative_to(project_dir),
                        ),
                    )
                    found = True
                    break
            if found:
                break

    return referencing_files


def find_texture_references(
    project_dir: Path,
    file_name: str,
) -> list[str]:
    """Scan all USD files in a directory for texture references.

    Args:
        project_dir: Root directory to scan recursively.
        file_name: Texture file name to search for.

    Returns:
        List of relative file paths that reference the texture.
    """
    referencing_files = []

    for usd_file in project_dir.rglob("*"):
        if usd_file.suffix not in (".usd", ".usda", ".usdc"):
            continue

        try:
            stage = Usd.Stage.Open(str(usd_file))
        except Exception:
            continue

        if stage is None:
            continue

        for prim in stage.Traverse():
            tex_attr = prim.GetAttribute(
                "inputs:texture:file",
            )
            if not tex_attr or not tex_attr.Get():
                continue
            tex_val = tex_attr.Get()
            tex_path = (
                tex_val.path
                if hasattr(tex_val, "path")
                else str(tex_val)
            )
            if file_name in tex_path:
                referencing_files.append(
                    str(
                        usd_file.relative_to(project_dir),
                    ),
                )
                break

    return referencing_files
