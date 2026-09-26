# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Texture file primitives — discovery, classification, project staging."""

from __future__ import annotations

import filecmp
import shutil
from pathlib import Path

from pxr import Usd

from bowerbot.schemas import AssetFormat, ASWFLayerNames, HDRIFormat, TextureCategory
from bowerbot.utils.core.asset_folder import resolve_library_file
from bowerbot.utils.library_utils import asset_location


def copy_file_into(source: Path, folder: Path) -> Path:
    """Copy *source* into *folder* and return the copy.

    An identical file already there is reused; a different file with the same
    name (texture names repeat across a library) makes this copy ``name_2``.
    """
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / source.name
    n = 2
    while dest.exists() and not filecmp.cmp(source, dest, shallow=False):
        dest = folder / f"{source.stem}_{n}{source.suffix}"
        n += 1
    if not dest.exists():
        shutil.copy2(source, dest)
    return dest


def copy_texture_to_project(source: Path, project_dir: Path) -> str:
    """Copy *source* into the project's ``textures/`` dir; return the rel path."""
    dest = copy_file_into(source, project_dir / ASWFLayerNames.TEXTURES)
    return f"./{ASWFLayerNames.TEXTURES}/{dest.name}"


def stage_asset_texture(
    asset_dir: Path,
    texture: str | None,
    *,
    library_dir: Path | None,
    project_dir: Path | None,
) -> str | None:
    """Copy a texture from the library into the asset's ``maps/`` dir; return the ref path."""
    if not texture:
        return texture
    if not Path(texture).is_absolute() and (asset_dir / texture).is_file():
        return texture  # already staged inside the asset (e.g. ./maps/foo.hdr)
    source = resolve_library_file(texture, library_dir=library_dir, project_dir=project_dir)
    dest = copy_file_into(source, asset_dir / ASWFLayerNames.MAPS)
    return f"./{ASWFLayerNames.MAPS}/{dest.name}"


def stage_scene_texture(
    texture: str | None,
    *,
    library_dir: Path | None,
    project_dir: Path | None,
) -> str | None:
    """Copy a scene-level texture from the library into ``<project>/textures/``; return its path."""
    if texture is None:
        return None
    if project_dir is None:
        msg = "No project set; cannot copy scene-level texture."
        raise RuntimeError(msg)
    source = resolve_library_file(texture, library_dir=library_dir, project_dir=project_dir)
    return copy_texture_to_project(source, project_dir)


def stage_asset_value(
    value: str,
    project_dir: Path,
    library_dir: Path | None = None,
) -> str:
    """Stage an Asset-attr value (a texture location) into the project; raise if unresolvable.

    *value* locates the file in the project (``textures/wood.png``) or the
    asset library, as ``search_textures`` reports it.
    """
    if not value:
        return value
    source = resolve_library_file(value, library_dir=library_dir, project_dir=project_dir)
    return copy_texture_to_project(source, project_dir)


def find_texture_references(
    project_dir: Path,
    file_name: str,
) -> list[str]:
    """Scan *project_dir* for USD files that reference *file_name*."""
    referencing: list[str] = []
    for usd_file in project_dir.rglob("*"):
        if usd_file.suffix not in AssetFormat.layer_formats():
            continue
        try:
            stage = Usd.Stage.Open(str(usd_file))
        except Exception:
            continue
        if stage is None:
            continue
        for prim in stage.Traverse():
            tex_attr = prim.GetAttribute("inputs:texture:file")
            if not tex_attr or not tex_attr.Get():
                continue
            tex_val = tex_attr.Get()
            tex_path = (
                tex_val.path if hasattr(tex_val, "path") else str(tex_val)
            )
            if file_name in tex_path:
                referencing.append(
                    str(usd_file.relative_to(project_dir)),
                )
                break
    return referencing


def find_textures(
    library_dir: Path,
    category: TextureCategory,
    *,
    query: str | None = None,
) -> list[dict[str, str]]:
    """Return textures in *library_dir* matching *category* (and *query*)."""
    if not library_dir.exists():
        return []
    extensions = category.extensions()
    needle = query.lower() if query else None
    return [
        _format(p, library_dir)
        for p in library_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in extensions
        and (needle is None or needle in p.stem.lower())
    ]


def _format(path: Path, library_dir: Path) -> dict[str, str]:
    """Build the entry shape surfaced to the LLM; ``location`` is what texture inputs take."""
    return {
        "name": path.stem,
        "location": asset_location(path, library_dir=library_dir, project_dir=None),
        "format": path.suffix.lower(),
        "category": _classify(path),
    }


def _classify(path: Path) -> str:
    """Return ``hdri`` for HDRI extensions, ``material`` otherwise."""
    hdri_exts = {f.value for f in HDRIFormat}
    return "hdri" if path.suffix.lower() in hdri_exts else "material"
