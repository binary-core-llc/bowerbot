# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Texture file primitives — discovery, classification, project staging."""

from __future__ import annotations

import shutil
from pathlib import Path

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
