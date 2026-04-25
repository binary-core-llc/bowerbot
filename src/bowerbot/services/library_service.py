# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Library service — discover USD assets in the user's asset library.

Detects ASWF asset folders at the top level of *library_dir* and scans
loose USD files recursively, classifying each as ``geo`` (geometry) or
``mtl`` (materials). Folder detection is composition-aware via
:func:`intake_service.detect_folder_root`, so non-canonical layouts are
surfaced as packages.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Usd, UsdShade

from bowerbot.schemas import AssetCategory, AssetFormat, DetectionOutcome
from bowerbot.services.intake_service import detect_folder_root

logger = logging.getLogger(__name__)

_USD_EXTENSIONS: frozenset[str] = frozenset(f.value for f in AssetFormat)
_NON_ASSET_DIRS: frozenset[str] = frozenset({"cache", "maps", "materials"})
ALL: str = "all"


def list_assets(
    library_dir: Path, category: str = ALL,
) -> list[dict[str, str]]:
    """Return every asset in *library_dir* matching *category*."""
    return _scan(library_dir, query=None, category=category)


def search_assets(
    library_dir: Path, query: str, category: str = ALL,
) -> list[dict[str, str]]:
    """Return assets whose name matches *query* (case-insensitive)."""
    return _scan(library_dir, query=query, category=category)


def find_package_for(file_path: Path, library_dir: Path) -> Path | None:
    """Return the package folder containing *file_path*, or ``None`` if loose.

    The package candidate is the immediate child of *library_dir* on the
    way to *file_path*. Files at the root of *library_dir* and files in
    top-level folders that are not unambiguous packages return ``None``
    and are treated as loose by the caller.
    """
    file_path = file_path.resolve()
    library = library_dir.resolve()

    try:
        relative = file_path.relative_to(library)
    except ValueError:
        return None  # outside the library

    if len(relative.parts) < 2:
        return None  # file at the library root

    candidate = library / relative.parts[0]
    detection = detect_folder_root(candidate)
    if detection.outcome is DetectionOutcome.UNAMBIGUOUS:
        return candidate
    return None


def _scan(
    library_dir: Path, query: str | None, category: str,
) -> list[dict[str, str]]:
    """Detect packages then scan loose files, filtered by query/category."""
    if not library_dir.exists():
        return []

    results: list[dict[str, str]] = []

    packages = _find_asset_folders(library_dir)
    package_dirs = set(packages.keys())
    needle = query.lower() if query else None

    for pkg_dir, root_file in packages.items():
        name = pkg_dir.name
        # Match against the folder name (authoritative) and the root
        # filename stem so non-canonical layouts stay findable.
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
            "category": _classify(f),
        }
        if category == ALL or category == entry["category"]:
            results.append(entry)

    return results


def _find_asset_folders(library_dir: Path) -> dict[Path, Path]:
    """Detect asset folders under *library_dir* via composition-aware detection.

    Returns a dict mapping ``folder_path → root_file_path``.
    """
    packages: dict[Path, Path] = {}
    for entry in library_dir.iterdir():
        if not entry.is_dir() or entry.name in _NON_ASSET_DIRS:
            continue
        detection = detect_folder_root(entry)
        if detection.outcome is DetectionOutcome.UNAMBIGUOUS and detection.root:
            packages[entry] = Path(detection.root)
    return packages


def _is_inside_package(file_path: Path, package_dirs: set[Path]) -> bool:
    """Return True if *file_path* lives inside one of *package_dirs*."""
    for pkg_dir in package_dirs:
        if pkg_dir in file_path.parents:
            return True
    return False


def _classify(file_path: Path) -> str:
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
