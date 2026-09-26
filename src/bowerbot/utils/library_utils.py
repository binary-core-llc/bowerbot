# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Library primitives — discover and classify USD assets on disk."""

from __future__ import annotations

import glob
import logging
from difflib import get_close_matches
from pathlib import Path

from pxr import Usd, UsdShade

from bowerbot.schemas import AssetCategory, AssetFormat, DetectionOutcome, LibraryRules
from bowerbot.utils.core.asset_folder import (
    detect_folder_root,
    find_root_file,
    refuse_file_path,
)

logger = logging.getLogger(__name__)


def truncate_with_total(
    matches: list[dict[str, str]], limit: int,
) -> dict[str, object]:
    """Cap *matches* at *limit*; return ``{results, total_matches, truncated}``."""
    limit = max(1, int(limit))
    total = len(matches)
    return {
        "results": matches[:limit],
        "total_matches": total,
        "truncated": total > limit,
    }


def scan_library(
    library_dir: Path,
    *,
    query: str | None = None,
    category: str = LibraryRules.ALL,
) -> list[dict[str, str]]:
    """Return matching assets in *library_dir*.

    Detects ASWF asset folders at the top level, then scans loose files
    recursively. Each entry has ``name`` (what asset inputs take),
    ``location`` (its place inside the library), ``format``, and
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
            "location": asset_location(root_file, library_dir=library_dir, project_dir=None),
            "format": root_file.suffix,
            "category": AssetCategory.PACKAGE.value,
        }
        if category == LibraryRules.ALL or category == entry["category"]:
            results.append(entry)

    for f in library_dir.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in AssetFormat:
            continue
        if _is_inside_package(f, package_dirs):
            continue
        if needle and needle not in _normalize_for_search(f.stem):
            continue
        entry = {
            "name": f.stem,
            "location": asset_location(f, library_dir=library_dir, project_dir=None),
            "format": f.suffix,
            "category": _classify_loose(f),
        }
        if category == LibraryRules.ALL or category == entry["category"]:
            results.append(entry)

    return results


def find_asset(
    ref: str,
    *,
    library_dir: Path | None,
    project_assets_dir: Path | None,
) -> Path:
    """The root file of the asset *ref* names.

    *ref* is a name exactly as ``search_assets``, ``list_assets`` or
    ``list_project_assets`` report it. The project's own copy wins, since it
    is what the scene uses and may carry edits; then the library asset with
    that name. A library location (``cache/sketchfab/Chair.usdz``) picks one
    of several library assets that share a name. File paths are refused.
    """
    refuse_file_path(ref, library_dir)
    if project_assets_dir is not None:
        found = _project_asset(project_assets_dir.expanduser().absolute(), ref)
        if found is not None:
            return found
    if library_dir is None:
        msg = "No asset library configured. Set 'assets_dir' in ~/.bowerbot/config.json."
        raise ValueError(msg)

    library_dir = library_dir.expanduser().absolute()
    matches = _library_assets_named(library_dir, ref)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        locations = ", ".join(sorted(str(m.relative_to(library_dir)) for m in matches))
        msg = (
            f"{len(matches)} library assets are named '{ref}' ({locations}). "
            f"Pass the location of the one you mean instead."
        )
        raise ValueError(msg)
    location = library_dir / ref
    if location.is_file() and location.suffix.lower() in AssetFormat:
        return location
    if location.is_dir():
        detection = detect_folder_root(location)
        if detection.outcome is DetectionOutcome.UNAMBIGUOUS and detection.root:
            return Path(detection.root)
    msg = f"No asset named '{ref}' in the project or the library. Find it with search_assets."
    close = get_close_matches(ref, _library_names(library_dir), n=3)
    if close:
        msg += f" Did you mean: {', '.join(close)}?"
    raise ValueError(msg)


def asset_location(path: Path, *, library_dir: Path | None, project_dir: Path | None) -> str:
    """Where *path* sits, for reports: inside the library, else inside the project."""
    for root in (library_dir, project_dir):
        if root is None:
            continue
        root = root.expanduser().absolute()
        for base, target in ((root, path.absolute()), (root.resolve(), path.resolve())):
            try:
                return target.relative_to(base).as_posix()
            except ValueError:
                continue
    return path.name


def _project_asset(project_assets_dir: Path, ref: str) -> Path | None:
    """The root file of the project asset *ref* (a folder, or a ``.usdz`` entry)."""
    if Path(ref).name != ref:
        return None
    for entry in (project_assets_dir / ref, project_assets_dir / f"{ref}{AssetFormat.USDZ}"):
        if entry.is_file() and entry.suffix.lower() == AssetFormat.USDZ:
            return entry
        if entry.is_dir():
            root = find_root_file(entry)
            if root is not None:
                return root
    return None


def _library_assets_named(library_dir: Path, name: str) -> list[Path]:
    """Every library asset ``scan_library`` would report as *name*: a package or a loose file."""
    matches: list[Path] = []
    folder = library_dir / name
    if folder.is_dir() and name not in LibraryRules.NON_ASSET_DIRS:
        detection = detect_folder_root(folder)
        if detection.outcome is DetectionOutcome.UNAMBIGUOUS and detection.root:
            matches.append(Path(detection.root))
    for candidate in library_dir.rglob(f"{glob.escape(name)}.*"):
        if candidate.stem != name or candidate.suffix.lower() not in AssetFormat:
            continue
        if not candidate.is_file():
            continue
        top = candidate.relative_to(library_dir).parts[0]
        inside_package = top != candidate.name and top not in LibraryRules.NON_ASSET_DIRS and (
            detect_folder_root(library_dir / top).outcome is DetectionOutcome.UNAMBIGUOUS
        )
        if not inside_package:
            matches.append(candidate)
    return matches


def _library_names(library_dir: Path) -> list[str]:
    """Candidate names for a did-you-mean hint (folder names and USD file stems)."""
    names = {entry.name for entry in library_dir.iterdir() if entry.is_dir()}
    names |= {f.stem for f in library_dir.rglob("*") if f.suffix.lower() in AssetFormat}
    return sorted(names)


def _normalize_for_search(value: str) -> str:
    """Lowercase + collapse ``_-.`` to spaces for forgiving substring search."""
    return value.lower().replace("_", " ").replace("-", " ").replace(".", " ")


def _find_top_level_packages(library_dir: Path) -> dict[Path, Path]:
    """Return ``{folder_path: root_file}`` for every package at the top level."""
    packages: dict[Path, Path] = {}
    for entry in library_dir.iterdir():
        if not entry.is_dir() or entry.name in LibraryRules.NON_ASSET_DIRS:
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
