# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The project's textures: copying texture files in, staging file-path values, finding users.

Texture files are copied into the project's ``textures/`` or an asset folder's
``maps/``; file-path (Asset) attribute values are resolved and copied the same way.
"""

from __future__ import annotations

import filecmp
import shutil
from pathlib import Path

from pxr import Sdf

from bowerbot import constants
from bowerbot.utils import authoring

# ── Finding and copying texture files ──


def resolve_texture(raw: str, *, project_dir: Path | None, library_dir: Path | None) -> Path:
    """The texture file *raw* names.

    A path is read as ``authoring.library.resolve_source_file`` reads it. A bare
    file name is also looked up in the project's ``textures/`` and across the
    library; when several library files have that name the call is refused, so
    the wrong one is never picked.
    """
    try:
        return authoring.library.resolve_source_file(
            raw, project_dir=project_dir, library_dir=library_dir, what="texture",
        )
    except ValueError:
        if Path(raw).name != raw:
            raise
        if project_dir is not None:
            staged = project_dir / constants.ASWFLayerNames.TEXTURES / raw
            if staged.is_file():
                return staged.resolve()
        if library_dir is None or not library_dir.exists():
            raise
        matches = sorted(p for p in library_dir.rglob(raw) if p.is_file())
        if len(matches) == 1:
            return matches[0].resolve()
        if not matches:
            raise
        names = ", ".join(str(m.relative_to(library_dir)) for m in matches)
        msg = f"texture '{raw}' names {len(matches)} files in the library ({names}); give its path."
        raise ValueError(msg) from None


def copy_into(source: Path, folder: Path) -> str:
    """Copy *source* into *folder* and return the name of the copy.

    A file already there with the same content is reused; one with the same
    name and other content is left alone, and the copy gets a numbered name.
    """
    folder.mkdir(parents=True, exist_ok=True)
    if source.resolve().parent == folder.resolve():
        return source.name
    counter = 1
    dest = folder / source.name
    while dest.exists():
        if filecmp.cmp(source, dest, shallow=False):
            return dest.name
        counter += 1
        dest = folder / f"{source.stem}_{counter}{source.suffix}"
    shutil.copy2(source, dest)
    return dest.name


def stage_scene_texture(
    texture: str | None, *, project_dir: Path | None, library_dir: Path | None,
) -> str | None:
    """Copy a scene-level texture into ``<project>/textures/``; return the path to author."""
    if texture is None:
        return None
    if project_dir is None:
        msg = "No project set; cannot copy scene-level texture."
        raise RuntimeError(msg)
    return stage_asset_value(texture, project_dir, library_dir)


def stage_asset_texture(
    asset_dir: Path, texture: str | None, *, project_dir: Path | None, library_dir: Path | None,
) -> str | None:
    """Copy a texture into the asset's ``maps/`` dir; return the path to author."""
    if not texture:
        return texture
    source = resolve_texture(texture, project_dir=project_dir, library_dir=library_dir)
    maps_dir = asset_dir / constants.ASWFLayerNames.MAPS
    return f"./{constants.ASWFLayerNames.MAPS}/{copy_into(source, maps_dir)}"


# ── File-path attribute values ──


def stage_asset_value(
    value: str,
    project_dir: Path,
    library_dir: Path | None = None,
) -> str:
    """Find the file an Asset-attr value names and stage it in the project's ``textures/``."""
    if not value or not Path(value).name:
        return value
    source = resolve_texture(value, project_dir=project_dir, library_dir=library_dir)
    textures_dir = project_dir / constants.ASWFLayerNames.TEXTURES
    return f"./{constants.ASWFLayerNames.TEXTURES}/{copy_into(source, textures_dir)}"


def stage_asset_typed_overrides(
    overrides: dict[str, dict[str, object]],
    resolved_types: dict[str, dict[str, Sdf.ValueTypeName | None]],
    project_dir: Path | None,
    library_dir: Path | None,
) -> dict[str, dict[str, object]]:
    """Return a new overrides dict with Asset-typed string values staged into the project."""
    if project_dir is None:
        return overrides
    asset_type = Sdf.ValueTypeNames.Asset
    out: dict[str, dict[str, object]] = {}
    for prim_path, attrs in overrides.items():
        types = resolved_types.get(prim_path, {})
        staged: dict[str, object] = {}
        for attr_name, value in attrs.items():
            if types.get(attr_name) == asset_type and isinstance(value, str):
                staged[attr_name] = stage_asset_value(
                    value, project_dir, library_dir,
                )
            else:
                staged[attr_name] = value
        out[prim_path] = staged
    return out
