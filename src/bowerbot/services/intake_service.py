# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Intake service — bring external asset folders into the project.

* **detect_folder_root** — classify a source folder and, when possible,
  identify its root USD file.
* **intake_folder** — copy a source folder into the project as a
  self-contained ASWF asset, localizing any external dependencies and
  canonicalizing the root filename.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

from pxr import Sdf, UsdUtils

from bowerbot.schemas import (
    ASWFLayerNames,
    DetectionOutcome,
    FolderDetection,
    IntakeReport,
)
from bowerbot.services.dependency_service import resolve as resolve_dependencies

logger = logging.getLogger(__name__)

_USD_EXTS: frozenset[str] = frozenset({".usd", ".usda", ".usdc"})
_ROOT_NAME_HINTS: tuple[str, ...] = ("root", "main", "asset")


def detect_folder_root(folder: Path) -> FolderDetection:
    """Classify *folder* and identify its root USD file when possible.

    Uses USD composition (the file that no sibling depends on is the
    root). With multiple candidates, naming heuristics (``<folder>``,
    ``root``, ``main``, ``asset``) break the tie.
    """
    folder = folder.resolve()
    if not folder.is_dir():
        return FolderDetection(
            outcome=DetectionOutcome.EMPTY,
            folder=str(folder),
            reason="not a directory",
        )

    usd_files = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in _USD_EXTS
    )
    if not usd_files:
        return FolderDetection(
            outcome=DetectionOutcome.EMPTY,
            folder=str(folder),
            reason="no USD files at the top level",
        )

    if len(usd_files) == 1:
        return FolderDetection(
            outcome=DetectionOutcome.UNAMBIGUOUS,
            folder=str(folder),
            root=str(usd_files[0]),
            reason="only USD file in the folder",
        )

    candidates = _candidate_roots_by_dep_graph(usd_files)

    if len(candidates) == 1:
        return FolderDetection(
            outcome=DetectionOutcome.UNAMBIGUOUS,
            folder=str(folder),
            root=str(candidates[0]),
            reason="only USD file in the folder not referenced by a sibling",
        )

    if not candidates:
        return FolderDetection(
            outcome=DetectionOutcome.AMBIGUOUS,
            folder=str(folder),
            candidates=[str(p) for p in usd_files],
            reason="circular references between siblings",
        )

    tiebreak = _name_tiebreak(candidates, folder.name)
    if tiebreak is not None:
        return FolderDetection(
            outcome=DetectionOutcome.UNAMBIGUOUS,
            folder=str(folder),
            root=str(tiebreak),
            reason=f"multiple candidates; picked by naming convention '{tiebreak.stem}'",
        )

    return FolderDetection(
        outcome=DetectionOutcome.AMBIGUOUS,
        folder=str(folder),
        candidates=[str(p) for p in candidates],
        reason="multiple independent USD files with no cross-references",
    )


def intake_folder(source_folder: Path, project_assets_dir: Path) -> IntakeReport:
    """Copy *source_folder* into the project as a self-contained asset.

    Every transitive dependency (including shader texture paths) is
    localized so the output folder is portable. The root is canonicalized
    to ``<folder>.usda`` and sibling references are rewritten.
    """
    detection = detect_folder_root(source_folder)
    if detection.outcome is DetectionOutcome.EMPTY:
        msg = f"No USD files found in {source_folder}"
        raise ValueError(msg)
    if detection.outcome is DetectionOutcome.AMBIGUOUS:
        names = ", ".join(Path(c).name for c in detection.candidates)
        msg = (
            f"Folder {source_folder.name} has multiple independent USD files "
            f"with no cross-references ({names}). ASWF expects a single root. "
            f"Rename one to '{source_folder.name}.usda' or place the files "
            f"individually."
        )
        raise ValueError(msg)

    source_folder = source_folder.resolve()
    project_assets_dir = project_assets_dir.resolve()
    source_root = Path(detection.root)  # type: ignore[arg-type]
    target_folder = project_assets_dir / source_folder.name

    if target_folder.exists():
        return _reuse_existing_target(target_folder, source_root)

    layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(source_root))
    if unresolved:
        pretty = ", ".join(str(p) for p in unresolved)
        msg = (
            f"Cannot intake {source_folder.name}: {len(unresolved)} "
            f"dependency path(s) did not resolve on disk ({pretty})."
        )
        raise ValueError(msg)

    path_map, layer_targets, localized_layer_sources, localized_asset_sources = (
        _plan_copies(
            source_folder=source_folder,
            target_folder=target_folder,
            layer_sources=[Path(lyr.realPath).resolve() for lyr in layers],
            asset_sources=[Path(a).resolve() for a in assets],
        )
    )

    target_folder.mkdir(parents=True, exist_ok=False)
    files_copied = 0
    try:
        for src, dst in path_map.items():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            files_copied += 1

        _rewrite_asset_paths(layer_targets, path_map)

        canonical_root = target_folder / f"{target_folder.name}.usda"
        copied_root = path_map[source_root.resolve()]
        was_renamed = _canonicalize_root(
            copied_root=copied_root,
            canonical_root=canonical_root,
            sibling_layer_targets=[p for p in layer_targets if p != copied_root],
        )

        warnings = _validate_self_contained(canonical_root, target_folder)
    except Exception:
        shutil.rmtree(target_folder, ignore_errors=True)
        raise

    logger.info(
        "Intaked %s → %s (%d file(s), %d localized)",
        source_folder.name, target_folder.name,
        files_copied, len(localized_layer_sources) + len(localized_asset_sources),
    )
    return IntakeReport(
        scene_ref_path=f"assets/{target_folder.name}/{canonical_root.name}",
        asset_folder_name=target_folder.name,
        root_original_name=source_root.name,
        root_canonical_name=canonical_root.name,
        was_renamed=was_renamed,
        files_copied=files_copied,
        localized_layers=localized_layer_sources,
        localized_assets=localized_asset_sources,
        warnings=warnings,
    )


def _reuse_existing_target(target_folder: Path, source_root: Path) -> IntakeReport:
    """Return a report for a target folder that already exists on disk."""
    canonical = target_folder / f"{target_folder.name}.usda"
    if not canonical.exists():
        msg = (
            f"Target folder {target_folder} exists but has no canonical "
            f"root '{canonical.name}'. Delete it and retry."
        )
        raise RuntimeError(msg)
    return IntakeReport(
        scene_ref_path=f"assets/{target_folder.name}/{canonical.name}",
        asset_folder_name=target_folder.name,
        root_original_name=source_root.name,
        root_canonical_name=canonical.name,
        was_renamed=source_root.name != canonical.name,
        files_copied=0,
        warnings=["target folder already existed; source was not re-copied"],
    )


def _candidate_roots_by_dep_graph(usd_files: list[Path]) -> list[Path]:
    """Return files no sibling depends on (so they can't be sub-layers)."""
    usd_set = {p.resolve() for p in usd_files}
    referenced: set[Path] = set()
    for candidate in usd_files:
        found, _missing = resolve_dependencies(candidate)
        for dep in found:
            dep_resolved = dep.resolve()
            if dep_resolved == candidate.resolve():
                continue
            if dep_resolved in usd_set:
                referenced.add(dep_resolved)
    return [p for p in usd_files if p.resolve() not in referenced]


def _name_tiebreak(candidates: list[Path], folder_name: str) -> Path | None:
    """Pick the preferred candidate by filename convention, or None."""
    for stem in (folder_name, *_ROOT_NAME_HINTS):
        matches = [p for p in candidates if p.stem == stem]
        if len(matches) == 1:
            return matches[0]
    return None


def _plan_copies(
    source_folder: Path,
    target_folder: Path,
    layer_sources: Iterable[Path],
    asset_sources: Iterable[Path],
) -> tuple[dict[Path, Path], list[Path], list[str], list[str]]:
    """Return ``(path_map, layer_targets, localized_layers, localized_assets)``.

    Files inside *source_folder* mirror their relative layout in the
    target. External layers land at the folder root; external assets
    (textures) land under ``textures/``. Collisions get a numeric suffix.
    """
    path_map: dict[Path, Path] = {}
    layer_targets: list[Path] = []
    localized_layer_sources: list[str] = []
    localized_asset_sources: list[str] = []
    used_targets: set[Path] = set()

    for src in layer_sources:
        if _is_inside(src, source_folder):
            dst = target_folder / src.relative_to(source_folder)
        else:
            dst = target_folder / src.name
            localized_layer_sources.append(str(src))
        resolved = _dedupe(dst, used_targets)
        used_targets.add(resolved)
        path_map[src] = resolved
        layer_targets.append(resolved)

    for src in asset_sources:
        if _is_inside(src, source_folder):
            dst = target_folder / src.relative_to(source_folder)
        else:
            dst = target_folder / ASWFLayerNames.TEXTURES / src.name
            localized_asset_sources.append(str(src))
        resolved = _dedupe(dst, used_targets)
        used_targets.add(resolved)
        path_map[src] = resolved

    return path_map, layer_targets, localized_layer_sources, localized_asset_sources


def _is_inside(path: Path, folder: Path) -> bool:
    """Return True if *path* is a descendant of *folder*."""
    try:
        path.relative_to(folder)
    except ValueError:
        return False
    return True


def _dedupe(candidate: Path, used: set[Path]) -> Path:
    """Return *candidate*, or a ``stem_N.ext`` variant if already used."""
    if candidate not in used:
        return candidate
    counter = 2
    while True:
        alt = candidate.with_name(f"{candidate.stem}_{counter}{candidate.suffix}")
        if alt not in used:
            return alt
        counter += 1


def _rewrite_asset_paths(
    layer_targets: list[Path], path_map: dict[Path, Path],
) -> None:
    """Rewrite every asset path in *layer_targets* to point inside the target."""
    resolved_map = {src.resolve(): dst.resolve() for src, dst in path_map.items()}

    for layer_path in layer_targets:
        layer = Sdf.Layer.FindOrOpen(str(layer_path))
        if layer is None:
            msg = f"Could not open copied layer for rewrite: {layer_path}"
            raise RuntimeError(msg)

        layer_dir = layer_path.parent.resolve()

        def _rewrite(asset_path: str, _layer_dir: Path = layer_dir) -> str:
            if not asset_path:
                return asset_path
            try:
                resolved = (_layer_dir / asset_path).resolve()
            except (OSError, ValueError):
                return asset_path
            target = resolved_map.get(resolved)
            if target is None:
                return asset_path
            try:
                relative = target.relative_to(_layer_dir)
            except ValueError:
                relative = Path(os.path.relpath(target, _layer_dir))
            return "./" + relative.as_posix()

        UsdUtils.ModifyAssetPaths(layer, _rewrite)
        layer.Save()


def _canonicalize_root(
    copied_root: Path,
    canonical_root: Path,
    sibling_layer_targets: list[Path],
) -> bool:
    """Rename *copied_root* to *canonical_root* and update sibling refs."""
    if copied_root.resolve() == canonical_root.resolve():
        return False

    shutil.move(str(copied_root), str(canonical_root))
    old_name = copied_root.name
    new_name = canonical_root.name

    for sibling_path in sibling_layer_targets:
        if not sibling_path.exists():
            continue
        layer = Sdf.Layer.FindOrOpen(str(sibling_path))
        if layer is None:
            continue

        def _swap(asset_path: str, _old: str = old_name, _new: str = new_name) -> str:
            if not asset_path or Path(asset_path).name != _old:
                return asset_path
            parent = Path(asset_path).parent
            if str(parent) in (".", ""):
                return f"./{_new}"
            return (parent / _new).as_posix()

        UsdUtils.ModifyAssetPaths(layer, _swap)
        layer.Save()

    return True


def _validate_self_contained(
    canonical_root: Path, target_folder: Path,
) -> list[str]:
    """Verify every dep of *canonical_root* resolves inside *target_folder*."""
    layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(canonical_root))

    if unresolved:
        msg = (
            f"Intake validation failed: {len(unresolved)} dependency "
            f"path(s) became unresolved after localization."
        )
        raise RuntimeError(msg)

    target_folder = target_folder.resolve()
    leaks = [
        str(Path(item).resolve())
        for item in (*[lyr.realPath for lyr in layers], *assets)
        if not _is_inside(Path(item).resolve(), target_folder)
    ]
    if leaks:
        msg = (
            f"Intake validation failed: {len(leaks)} dependency path(s) "
            f"still point outside the asset folder after localization."
        )
        raise RuntimeError(msg)

    return []
