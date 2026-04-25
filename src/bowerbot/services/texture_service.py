# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Texture service — find textures and HDRIs in the asset library.

The discovery layer for any texture concern (HDRIs for dome lights,
material maps for surfaces). Use-site code (lights, materials) calls
these functions to surface options to the LLM and then drives its own
binding/localization on top.
"""

from __future__ import annotations

from pathlib import Path

from bowerbot.schemas import HDRIFormat, TextureCategory


def list_textures(
    library_dir: Path, category: TextureCategory,
) -> list[dict[str, str]]:
    """Return every texture in *library_dir* matching *category*."""
    if not library_dir.exists():
        return []
    extensions = category.extensions()
    return [
        _format(p)
        for p in library_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in extensions
    ]


def search_textures(
    library_dir: Path, query: str, category: TextureCategory,
) -> list[dict[str, str]]:
    """Return textures whose stem matches *query* (case-insensitive)."""
    if not library_dir.exists():
        return []
    extensions = category.extensions()
    needle = query.lower()
    return [
        _format(p)
        for p in library_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in extensions
        and needle in p.stem.lower()
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
