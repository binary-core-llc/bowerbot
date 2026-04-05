# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Shared USD utilities to centralize pxr usage."""

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


def get_prim_ref_paths(prim: Usd.Prim) -> list[str]:
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


def resolve_asset_dir_for_prim(
    stage: Usd.Stage,
    prim_path: str,
) -> tuple[Path | None, str | None]:
    """Find the ASWF asset folder backing a given prim path.

    Walks the stage hierarchy checking the prim itself, its children,
    and then its ancestors for a reference to an ASWF asset folder.

    An ASWF folder is identified by a reference whose file name
    matches its parent directory (e.g. ``chair/chair.usd``).

    Args:
        stage: The composed USD stage to search.
        prim_path: Absolute prim path to resolve.

    Returns:
        ``(asset_dir, ref_prim_path)`` where *asset_dir* is the
        resolved :class:`Path` to the ASWF folder and
        *ref_prim_path* is the prim that holds the reference.
        Returns ``(None, None)`` if no ASWF folder is found.
    """
    stage_dir = Path(stage.GetRootLayer().realPath).parent

    def _check_prim_refs(prim: Usd.Prim) -> tuple[Path | None, str | None]:
        for ref_path in get_prim_ref_paths(prim):
            resolved = (stage_dir / ref_path).resolve()
            if not resolved.exists() or not resolved.parent.is_dir():
                continue
            folder = resolved.parent
            for ext in (".usd", ".usda", ".usdc"):
                if resolved.name == f"{folder.name}{ext}":
                    return folder, str(prim.GetPath())
        return None, None

    # Check the target prim and its direct children
    target = stage.GetPrimAtPath(prim_path)
    if target and target.IsValid():
        result = _check_prim_refs(target)
        if result[0] is not None:
            return result
        for child in target.GetChildren():
            result = _check_prim_refs(child)
            if result[0] is not None:
                return result

    # Walk up ancestors
    path_parts = prim_path.strip("/").split("/")
    for i in range(len(path_parts) - 1, 0, -1):
        check_path = "/" + "/".join(path_parts[:i])
        prim = stage.GetPrimAtPath(check_path)
        if not prim or not prim.IsValid():
            continue
        result = _check_prim_refs(prim)
        if result[0] is not None:
            return result
        for child in prim.GetChildren():
            result = _check_prim_refs(child)
            if result[0] is not None:
                return result

    return None, None


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
            for asset_path in get_prim_ref_paths(prim):
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
