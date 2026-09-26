# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Localize — copy a USD file and everything it depends on into an asset folder."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from pxr import Sdf, Usd, UsdUtils

from bowerbot.schemas import ASWFLayerNames, LocalizedCopy


def localize(source_root: Path, source_folder: Path, target_root: Path) -> LocalizedCopy:
    """Copy *source_root* to *target_root* along with every file it depends on.

    Dependencies inside *source_folder* keep their place relative to it;
    those outside it are copied into the target folder (layers at its top,
    other files under ``textures/``). Every asset path in the copied layers
    is rewritten to point at the copies, and the result is checked to be
    self-contained. Raises ``ValueError`` if a dependency does not resolve.
    """
    layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(source_root))
    if unresolved:
        missing = ", ".join(str(p) for p in unresolved)
        msg = (
            f"Cannot intake {source_root.name}: {len(unresolved)} dependency "
            f"path(s) did not resolve on disk ({missing})."
        )
        raise ValueError(msg)

    source_root = source_root.resolve()
    source_folder = source_folder.resolve()
    target_folder = target_root.parent
    plan = _plan(
        source_root, source_folder, target_root,
        layer_sources=[Path(layer.realPath).resolve() for layer in layers],
        asset_sources=[Path(a).resolve() for a in assets],
    )
    for source, target in plan.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix == ".usda" and not _is_text_usda(source):
            Sdf.Layer.FindOrOpen(str(source)).Export(str(target))
        else:
            shutil.copy2(source, target)
    layer_sources = {Path(layer.realPath).resolve() for layer in layers}
    for source in layer_sources:
        _rewrite_asset_paths(source, plan[source], plan)
    _require_self_contained(target_root, target_folder)
    _require_same_composition(source_root, target_root)

    return LocalizedCopy(
        files_copied=len(plan),
        localized_layers=[str(s) for s in layer_sources if not _is_inside(s, source_folder)],
        localized_assets=[
            str(s) for s in plan if s not in layer_sources and not _is_inside(s, source_folder)
        ],
    )


def _plan(
    source_root: Path,
    source_folder: Path,
    target_root: Path,
    *,
    layer_sources: list[Path],
    asset_sources: list[Path],
) -> dict[Path, Path]:
    """Map every source file to its copy; the root gets *target_root*, names never collide."""
    target_folder = target_root.parent
    plan = {source_root: target_root}
    used = {target_root}
    for source in (*layer_sources, *asset_sources):
        if source in plan:
            continue
        if _is_inside(source, source_folder):
            target = target_folder / source.relative_to(source_folder)
        elif source in layer_sources:
            target = target_folder / source.name
        else:
            target = target_folder / ASWFLayerNames.TEXTURES / source.name
        target = _unused(target, used)
        used.add(target)
        plan[source] = target
    return plan


def _rewrite_asset_paths(source: Path, target: Path, plan: dict[Path, Path]) -> None:
    """Point every asset path in the copied layer *target* at the planned copies.

    Paths are resolved against the SOURCE layer's folder: that is where
    they were authored, and where files outside the source folder live.
    """
    layer = Sdf.Layer.FindOrOpen(str(target))
    if layer is None:
        msg = f"Could not open copied layer for rewrite: {target}"
        raise RuntimeError(msg)

    def rewrite(asset_path: str) -> str:
        if not asset_path:
            return asset_path
        try:
            resolved = (source.parent / asset_path).resolve()
        except (OSError, ValueError):
            return asset_path
        copy = plan.get(resolved)
        if copy is None:
            return asset_path
        return "./" + Path(os.path.relpath(copy, target.parent)).as_posix()

    UsdUtils.ModifyAssetPaths(layer, rewrite)
    layer.Save()


def _require_self_contained(root: Path, folder: Path) -> None:
    """Raise unless every dependency of *root* resolves inside *folder*."""
    layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(root))
    if unresolved:
        msg = (
            f"Intake validation failed: {len(unresolved)} dependency "
            f"path(s) became unresolved after localization."
        )
        raise RuntimeError(msg)
    folder = folder.resolve()
    leaks = [
        item for item in (*[layer.realPath for layer in layers], *assets)
        if not _is_inside(Path(item).resolve(), folder)
    ]
    if leaks:
        msg = (
            f"Intake validation failed: {len(leaks)} dependency path(s) "
            f"still point outside the asset folder after localization."
        )
        raise RuntimeError(msg)


def _require_same_composition(source: Path, copy: Path) -> None:
    """Raise if the copy composes fewer prims than the source it was made from."""
    source_stage = Usd.Stage.Open(str(source))
    copy_stage = Usd.Stage.Open(str(copy))
    source_prims = {prim.GetPath() for prim in source_stage.TraverseAll()}
    copy_prims = {prim.GetPath() for prim in copy_stage.TraverseAll()}
    lost = sorted(str(path) for path in source_prims - copy_prims)
    if lost:
        msg = (
            f"Intake validation failed: the copy of {source.name} is missing "
            f"{len(lost)} prim(s) the source composes (e.g. {', '.join(lost[:3])})."
        )
        raise RuntimeError(msg)


def _is_text_usda(path: Path) -> bool:
    """Whether *path* is a text USD layer (``#usda`` header), not a binary crate file."""
    with path.open("rb") as handle:
        return handle.read(5) == b"#usda"


def _is_inside(path: Path, folder: Path) -> bool:
    """Return True if *path* is a descendant of *folder*."""
    try:
        path.relative_to(folder)
    except ValueError:
        return False
    return True


def _unused(candidate: Path, used: set[Path]) -> Path:
    """Return *candidate*, or a ``stem_N.ext`` variant if already used."""
    if candidate not in used:
        return candidate
    counter = 2
    while True:
        alt = candidate.with_name(f"{candidate.stem}_{counter}{candidate.suffix}")
        if alt not in used:
            return alt
        counter += 1
