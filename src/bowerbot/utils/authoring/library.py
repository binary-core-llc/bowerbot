# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The asset library: searching it for assets and textures, its asset folders, resolving a path."""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Usd
from pxr import UsdShade

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring

logger = logging.getLogger(__name__)

# ── Searching the library ──


def scan_library(
    library_dir: Path,
    *,
    query: str | None = None,
    category: str = constants.LibraryRules.ANY_CATEGORY,
) -> list[dict[str, str]]:
    """Return matching assets in *library_dir*.

    Detects ASWF asset folders at the top level, then scans loose files
    recursively. Each entry has ``name``, ``path``, ``format``, and
    ``category`` (``geo`` / ``mtl`` / ``package``).
    """
    if not library_dir.exists():
        return []

    results: list[dict[str, str]] = []
    packages = _find_top_level_packages(library_dir)
    package_dirs = set(packages.keys())
    needle = _normalize_for_search(query) if query else None

    for pkg_dir, root_file in packages.items():
        name = pkg_dir.name
        haystack = " ".join(
            _normalize_for_search(s) for s in (name, root_file.stem)
        )
        if needle and needle not in haystack:
            continue
        entry = {
            "name": name,
            "path": str(root_file),
            "format": root_file.suffix,
            "category": schemas.AssetCategory.PACKAGE.value,
        }
        if category == constants.LibraryRules.ANY_CATEGORY or category == entry["category"]:
            results.append(entry)

    for f in sorted(library_dir.rglob("*")):
        if not f.is_file():
            continue
        if f.suffix.lower() not in constants.LibraryRules.USD_EXTENSIONS:
            continue
        if _is_inside_package(f, package_dirs):
            continue
        if needle and needle not in _normalize_for_search(f.stem):
            continue
        entry = {
            "name": f.stem,
            "path": str(f),
            "format": f.suffix,
            "category": _classify_loose(f),
        }
        if category == constants.LibraryRules.ANY_CATEGORY or category == entry["category"]:
            results.append(entry)

    return results


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
        _texture_entry(p)
        for p in sorted(library_dir.rglob("*"))
        if p.is_file()
        and p.suffix.lower() in extensions
        and (needle is None or needle in p.stem.lower())
    ]


def truncate_with_total(
    matches: list[dict[str, str]], limit: int, library_dir: Path | None,
) -> dict[str, object]:
    """Cap *matches* at *limit*; return ``{results, total_matches, truncated}``.

    The results that BowerBot would refuse to place say why (``cannot_be_used``).
    """
    limit = max(1, int(limit))
    total = len(matches)
    shown = matches[:limit]
    if library_dir is not None:
        authoring.accepted_shapes.mark_refused(shown, library_dir)
    return {
        "results": shown,
        "total_matches": total,
        "truncated": total > limit,
    }


# ── Resolving an asset path ──


def resolve_source_file(
    raw: str,
    *,
    project_dir: Path | None,
    library_dir: Path | None,
    what: str = "asset",
) -> Path:
    """The existing file *raw* names: an absolute path, or a path inside the project or library.

    A relative path is looked up in the project, then in the library, and
    never in the folder BowerBot was started from. *what* names the kind of
    file in the refusal (``"asset"``, ``"material file"``, ``"texture"``).
    """
    path = Path(raw)
    if path.is_absolute():
        candidates = [path]
    else:
        roots = (project_dir, library_dir)
        candidates = [root / raw for root in roots if root is not None]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    for candidate in candidates:
        if candidate.is_dir():
            msg = (
                f"'{raw}' is a folder ({candidate}); reference the {what}'s root "
                f"file instead (e.g. '{candidate.name}/{candidate.name}.usda')."
            )
            raise ValueError(msg)
    searched = ", ".join(str(c) for c in candidates) or "no roots available"
    msg = f"{what} '{raw}' not found (searched: {searched})."
    raise ValueError(msg)


# ── Helpers ──


def _normalize_for_search(value: str) -> str:
    """Lowercase + collapse ``_-.`` to spaces for forgiving substring search."""
    return value.lower().replace("_", " ").replace("-", " ").replace(".", " ")


def _find_top_level_packages(library_dir: Path) -> dict[Path, Path]:
    """Return ``{folder_path: root_file}`` for every package at the top level."""
    packages: dict[Path, Path] = {}
    for entry in sorted(library_dir.iterdir()):
        if not entry.is_dir() or entry.name in constants.LibraryRules.NON_ASSET_DIRS:
            continue
        root_file = authoring.accepted_shapes.folder_root_file(entry)
        if root_file is not None:
            packages[entry] = root_file
    return packages


def _is_inside_package(file_path: Path, package_dirs: set[Path]) -> bool:
    """Return True if *file_path* lives inside one of *package_dirs*."""
    for pkg_dir in package_dirs:
        if pkg_dir in file_path.parents:
            return True
    return False


def _classify_loose(file_path: Path) -> str:
    """Classify a loose USD file as ``mtl`` (defines a Material) or ``geo``."""
    try:
        stage = Usd.Stage.Open(str(file_path))
        if stage is not None:
            for prim in stage.Traverse():
                if prim.IsA(UsdShade.Material):
                    return schemas.AssetCategory.MTL.value
    except Exception:
        logger.debug(
            "Could not classify %s, defaulting to geo",
            file_path, exc_info=True,
        )
    return schemas.AssetCategory.GEO.value


def _texture_entry(path: Path) -> dict[str, str]:
    """Build the entry shape surfaced to the LLM."""
    return {
        "name": path.stem,
        "path": str(path),
        "format": path.suffix.lower(),
        "category": _classify_texture(path),
    }


def _classify_texture(path: Path) -> str:
    """Return ``hdri`` for HDRI extensions, ``material`` otherwise."""
    hdri_exts = {f.value for f in schemas.HDRIFormat}
    return "hdri" if path.suffix.lower() in hdri_exts else "material"
