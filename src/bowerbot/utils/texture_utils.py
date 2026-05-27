# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Texture file primitives — discovery, classification, project staging."""

from __future__ import annotations

import shutil
from pathlib import Path

from pxr import Usd

from bowerbot.schemas import ASWFLayerNames, HDRIFormat, TextureCategory


def copy_texture_to_project(source: Path, project_dir: Path) -> str:
    """Copy *source* into the project's ``textures/`` dir; return the rel path.

    Skips the copy if the destination already exists.
    """
    tex_dir = project_dir / ASWFLayerNames.TEXTURES
    tex_dir.mkdir(parents=True, exist_ok=True)

    dest = tex_dir / source.name
    if not dest.exists():
        shutil.copy2(source, dest)

    return f"./{ASWFLayerNames.TEXTURES}/{source.name}"


def stage_scene_texture(
    project_dir: Path | None, texture: str | None,
) -> str | None:
    """Copy a scene-level texture into ``<project>/textures/`` if it exists on disk."""
    if texture is None:
        return None
    source = Path(texture)
    if not source.exists():
        return texture
    if project_dir is None:
        msg = "No project set; cannot copy scene-level texture."
        raise RuntimeError(msg)
    return copy_texture_to_project(source, project_dir)


def stage_asset_value(
    value: str,
    project_dir: Path,
    library_dir: Path | None = None,
) -> str:
    """Resolve and stage an Asset-attr value into the project; raise if unresolvable."""
    if not value:
        return value
    src = Path(value)
    filename = src.name
    if not filename:
        return value

    project_rel = f"./{ASWFLayerNames.TEXTURES}/{filename}"
    if (project_dir / ASWFLayerNames.TEXTURES / filename).exists():
        return project_rel

    candidates: list[Path] = []
    if src.is_absolute() and src.exists():
        candidates.append(src)
    if library_dir is not None and library_dir.exists():
        candidates.extend(library_dir.rglob(filename))
    for candidate in candidates:
        if candidate.is_file():
            return copy_texture_to_project(candidate, project_dir)

    raise ValueError(
        f"Cannot stage texture {value!r}: file not found in project's textures/, "
        "in the library, or as an absolute path. Provide an absolute path to the "
        "source file, or copy it into the library first.",
    )


def find_texture_references(
    project_dir: Path,
    file_name: str,
) -> list[str]:
    """Scan *project_dir* for USD files that reference *file_name*."""
    referencing: list[str] = []
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
        _format(p)
        for p in library_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in extensions
        and (needle is None or needle in p.stem.lower())
    ]


def _format(path: Path) -> dict[str, str]:
    """Build the entry shape surfaced to the LLM."""
    return {
        "name": path.stem,
        "path": str(path),
        "format": path.suffix.lower(),
        "category": _classify(path),
    }


def _classify(path: Path) -> str:
    """Return ``hdri`` for HDRI extensions, ``material`` otherwise."""
    hdri_exts = {f.value for f in HDRIFormat}
    return "hdri" if path.suffix.lower() in hdri_exts else "material"
