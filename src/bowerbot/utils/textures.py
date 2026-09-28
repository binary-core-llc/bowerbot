# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Finding textures in the library by category and name.

Copying textures into the project is in ``authoring.textures``.
"""

from __future__ import annotations

from pathlib import Path

from bowerbot import schemas


def find_textures(
    library_dir: Path,
    category: schemas.TextureCategory,
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
        for p in sorted(library_dir.rglob("*"))
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
    hdri_exts = {f.value for f in schemas.HDRIFormat}
    return "hdri" if path.suffix.lower() in hdri_exts else "material"
