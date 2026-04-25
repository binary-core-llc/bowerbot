# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Library primitives — discover and classify USD assets on disk."""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Usd, UsdShade

from bowerbot.schemas import AssetCategory, AssetFormat, DetectionOutcome
from bowerbot.utils.asset_folder_utils import detect_folder_root

logger = logging.getLogger(__name__)

_USD_EXTENSIONS: frozenset[str] = frozenset(f.value for f in AssetFormat)
_NON_ASSET_DIRS: frozenset[str] = frozenset({"cache", "maps", "materials"})
ALL: str = "all"


def scan_library(
    library_dir: Path,
    *,
    query: str | None = None,
    category: str = ALL,
) -> list[dict[str, str]]:
    """Return matching assets in *library_dir*.

    Detects ASWF asset folders at the top level, then scans loose files
    recursively. Each entry has ``name``, ``path``, ``format``, and
    ``category`` (``geo`` / ``mtl`` / ``package``).
    """
    if not library_dir.exists():
        return []

    results: list[dict[str, str]] = []
    packages = find_top_level_packages(library_dir)
    package_dirs = set(packages.keys())
    needle = query.lower() if query else None

    for pkg_dir, root_file in packages.items():
        name = pkg_dir.name
        haystack = (name.lower(), root_file.stem.lower())
        if needle and not any(needle in h for h in haystack):
            continue
        entry = {
            "name": name,
            "path": str(root_file),
            "format": root_file.suffix,
            "category": AssetCategory.PACKAGE.value,
        }
        if category == ALL or category == entry["category"]:
            results.append(entry)

    for f in library_dir.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in _USD_EXTENSIONS:
            continue
        if _is_inside_package(f, package_dirs):
            continue
        if needle and needle not in f.stem.lower():
            continue
        entry = {
            "name": f.stem,
            "path": str(f),
            "format": f.suffix,
            "category": _classify_loose(f),
        }
        if category == ALL or category == entry["category"]:
            results.append(entry)

    return results


def find_top_level_packages(library_dir: Path) -> dict[Path, Path]:
    """Return ``{folder_path: root_file}`` for every package at the top level."""
    packages: dict[Path, Path] = {}
    for entry in library_dir.iterdir():
        if not entry.is_dir() or entry.name in _NON_ASSET_DIRS:
            continue
        detection = detect_folder_root(entry)
        if detection.outcome is DetectionOutcome.UNAMBIGUOUS and detection.root:
            packages[entry] = Path(detection.root)
    return packages


def find_package_for(file_path: Path, library_dir: Path) -> Path | None:
    """Return the package folder containing *file_path*, or ``None`` if loose.

    Treats only the immediate child of *library_dir* as a package
    candidate, so files at the library root never trigger a folder
    intake.
    """
    file_path = file_path.resolve()
    library = library_dir.resolve()

    try:
        relative = file_path.relative_to(library)
    except ValueError:
        return None

    if len(relative.parts) < 2:
        return None

    candidate = library / relative.parts[0]
    detection = detect_folder_root(candidate)
    if detection.outcome is DetectionOutcome.UNAMBIGUOUS:
        return candidate
    return None


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
                    return AssetCategory.MTL.value
    except Exception:
        logger.debug(
            "Could not classify %s, defaulting to geo",
            file_path, exc_info=True,
        )
    return AssetCategory.GEO.value
