# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""ASWF asset folder primitives.

Pure helpers for inspecting and editing the ASWF folder structure
(root + ``geo.usda`` / ``mtl.usda`` / ``lgt.usda`` / ``contents.usda``).
Services compose these to read folder metadata, scaffold layers, and
detect the canonical root.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom

from bowerbot.schemas import (
    ASWFLayerNames,
    DetectionOutcome,
    FolderDetection,
)
from bowerbot.utils.dependency_utils import resolve as resolve_dependencies
from bowerbot.utils.stage_utils import get_prim_ref_paths

logger = logging.getLogger(__name__)

_USD_EXTS: frozenset[str] = frozenset({".usd", ".usda", ".usdc"})
_ROOT_NAME_HINTS: tuple[str, ...] = ("root", "main", "asset")

CANONICAL_REFERENCE_ORDER: tuple[str, ...] = (
    ASWFLayerNames.VARIANTS,
    ASWFLayerNames.CONTENTS,
    ASWFLayerNames.LGT,
    ASWFLayerNames.MTL,
)


# ── Folder structure ──


def resolve_asset_dir_for_prim(
    stage: Usd.Stage,
    prim_path: str,
) -> tuple[Path | None, str | None]:
    """Find the outer ASWF asset folder backing *prim_path* in *stage*."""
    # Resolution is rooted at stage_dir (project root) on purpose: nested
    # refs in contents.usda are authored relative to that layer
    # (../sibling_asset/...) and resolve to a nonexistent path here, so
    # they are skipped and the walk continues to the outer container's
    # scene-level reference. That is the routing target move/remove/freeze
    # need.
    stage_dir = Path(stage.GetRootLayer().realPath).parent

    def _check(prim: Usd.Prim) -> tuple[Path | None, str | None]:
        for ref_path in get_prim_ref_paths(prim):
            resolved = (stage_dir / ref_path).resolve()
            if not resolved.exists() or not resolved.parent.is_dir():
                continue
            folder = resolved.parent
            for ext in _USD_EXTS:
                if resolved.name == f"{folder.name}{ext}":
                    return folder, str(prim.GetPath())
        return None, None

    target = stage.GetPrimAtPath(prim_path)
    if target and target.IsValid():
        result = _check(target)
        if result[0] is not None:
            return result
        for child in target.GetChildren():
            result = _check(child)
            if result[0] is not None:
                return result

    parts = prim_path.strip("/").split("/")
    for i in range(len(parts) - 1, 0, -1):
        ancestor_path = "/" + "/".join(parts[:i])
        prim = stage.GetPrimAtPath(ancestor_path)
        if not prim or not prim.IsValid():
            continue
        result = _check(prim)
        if result[0] is not None:
            return result
        for child in prim.GetChildren():
            result = _check(child)
            if result[0] is not None:
                return result

    return None, None


def find_root_file(asset_dir: Path) -> Path | None:
    """Return the canonical ASWF root file in *asset_dir*, or ``None``."""
    for ext in (".usd", ".usda", ".usdc"):
        candidate = asset_dir / f"{asset_dir.name}{ext}"
        if candidate.exists():
            return candidate
    return None


def require_asset_context(
    stage: Usd.Stage, prim_path: str,
) -> tuple[Path, str]:
    """Resolve the asset folder + reference prim path; raise if neither is found."""
    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(stage, prim_path)
    if asset_dir is None or ref_prim_path is None:
        raise ValueError(
            f"Cannot find ASWF asset folder for {prim_path}. "
            "Operation only works on assets placed as ASWF folders (not USDZ).",
        )
    return asset_dir, ref_prim_path


def asset_has_root_payload(asset_dir: Path) -> bool:
    """Return whether the asset's root prim has a directly authored payload."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return False
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return False
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return False
    plist = prim_spec.payloadList
    return bool(
        plist.prependedItems
        or plist.appendedItems
        or plist.addedItems
        or plist.explicitItems,
    )


def clear_root_payload(asset_dir: Path) -> None:
    """Strip every payload list-op slot from the asset's root prim."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return
    plist = prim_spec.payloadList
    plist.ClearEdits()
    layer.Save()


def list_alternate_geo_files(asset_dir: Path) -> list[str]:
    """USD files in the asset folder that aren't canonical ASWF layers or root."""
    if not asset_dir.is_dir():
        return []
    canonical = {
        ASWFLayerNames.GEO,
        ASWFLayerNames.MTL,
        ASWFLayerNames.LGT,
        ASWFLayerNames.CONTENTS,
        ASWFLayerNames.VARIANTS,
    }
    canonical |= {f"{asset_dir.name}{ext}" for ext in _USD_EXTS}
    return sorted(
        p.name for p in asset_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in _USD_EXTS
        and p.name not in canonical
    )


def resolve_default_prim_name(asset_dir: Path) -> str:
    """Return the asset's ``defaultPrim`` name, falling back to folder name."""
    name = _get_default_prim_name(asset_dir)
    return name if name else asset_dir.name


def to_layer_local_path(prim_path: str, default_prim_name: str) -> str:
    """Convert a composed prim path to a layer-local path under defaultPrim."""
    prefix = f"/{default_prim_name}"
    if prim_path in ("", "/", prefix):
        return prefix
    if prim_path.startswith(f"{prefix}/"):
        return prim_path
    if not prim_path.startswith("/"):
        prim_path = f"/{prim_path}"
    return f"{prefix}{prim_path}"


def normalize_asset_prim_path(
    prim_path: str, ref_prim_path: str, default_prim_name: str,
) -> str:
    """Strip the scene namespace then anchor under the asset's default prim."""
    if prim_path == ref_prim_path:
        return f"/{default_prim_name}"
    if prim_path.startswith(f"{ref_prim_path}/"):
        return to_layer_local_path(
            prim_path[len(ref_prim_path):], default_prim_name,
        )
    return to_layer_local_path(prim_path, default_prim_name)


def ensure_layer_scope(
    layer: Sdf.Layer,
    default_prim_name: str,
    scope_name: str,
    scope_type: str,
) -> None:
    """Ensure ``/{default_prim_name}/{scope_name}`` exists in *layer*."""
    root_prim_path = Sdf.Path(f"/{default_prim_name}")
    scope_path = Sdf.Path(f"/{default_prim_name}/{scope_name}")

    if not layer.GetPrimAtPath(root_prim_path):
        Sdf.CreatePrimInLayer(layer, root_prim_path)
        layer.GetPrimAtPath(root_prim_path).specifier = Sdf.SpecifierOver

    if not layer.GetPrimAtPath(scope_path):
        Sdf.CreatePrimInLayer(layer, scope_path)
        scope = layer.GetPrimAtPath(scope_path)
        scope.specifier = Sdf.SpecifierDef
        scope.typeName = scope_type


def ensure_root_reference(asset_dir: Path, layer_file: str) -> None:
    """Ensure the asset's root file references *layer_file*."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return

    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        return

    ref_path = f"./{layer_file}"
    if ref_path in get_prim_ref_paths(root_prim):
        return

    del stage
    rebuild_root_references(asset_dir)


def remove_empty_layer(
    layer_path: Path,
    asset_dir: Path,
    has_content: Callable[[Usd.Prim], bool],
) -> None:
    """Remove *layer_path* when no prim in it satisfies *has_content*."""
    stage = Usd.Stage.Open(str(layer_path))
    if stage:
        for prim in stage.Traverse():
            if has_content(prim):
                return

    layer_path.unlink()
    rebuild_root_references(asset_dir)
    logger.info("Removed empty %s from %s", layer_path.name, asset_dir.name)


def rebuild_root_references(asset_dir: Path) -> None:
    """Rebuild root composition arcs: geo via payload, others via references."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return

    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        return

    root_prim.GetReferences().ClearReferences()
    root_prim.GetPayloads().ClearPayloads()

    geo_path = asset_dir / ASWFLayerNames.GEO
    if geo_path.exists():
        root_prim.GetPayloads().AddPayload(f"./{ASWFLayerNames.GEO}")

    for layer_file in CANONICAL_REFERENCE_ORDER:
        if (asset_dir / layer_file).exists():
            root_prim.GetReferences().AddReference(f"./{layer_file}")

    stage.Save()


# ── Stage metadata ──


def read_stage_metadata(file_path: Path) -> tuple[float, str]:
    """Return ``(metersPerUnit, upAxis)`` for *file_path*."""
    stage = Usd.Stage.Open(str(file_path))
    if stage is None:
        return 1.0, "Y"

    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    up = UsdGeom.GetStageUpAxis(stage)
    up_str = "Y" if up == UsdGeom.Tokens.y else "Z"
    return mpu, up_str


def read_stage_metadata_from_dir(asset_dir: Path) -> tuple[float, str]:
    """Return ``(metersPerUnit, upAxis)`` from an asset's ``geo.usda``."""
    geo_path = asset_dir / ASWFLayerNames.GEO
    if geo_path.exists():
        return read_stage_metadata(geo_path)
    return 1.0, "Y"


def read_asset_mpu_from_file(asset_file: Path) -> float:
    """Return ``metersPerUnit`` from any USD file. Defaults to 1.0."""
    mpu, _ = read_stage_metadata(asset_file)
    return mpu if mpu > 0 else 1.0


# ── Root detection ──


def detect_folder_root(folder: Path) -> FolderDetection:
    """Classify *folder* and identify its root USD file when possible.

    USD composition is the source of truth: the file no sibling depends
    on is the root. With multiple candidates, naming heuristics
    (``<folder>``, ``root``, ``main``, ``asset``) break the tie.
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


# ── Internal helpers ──


def _get_default_prim_name(asset_dir: Path) -> str | None:
    """Return the ``defaultPrim`` recorded in ``geo.usda``, if any."""
    geo_path = asset_dir / ASWFLayerNames.GEO
    if geo_path.exists():
        layer = Sdf.Layer.FindOrOpen(str(geo_path))
        if layer and layer.defaultPrim:
            return layer.defaultPrim
    return None


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
    """Pick the preferred candidate by filename convention, or ``None``."""
    for stem in (folder_name, *_ROOT_NAME_HINTS):
        matches = [p for p in candidates if p.stem == stem]
        if len(matches) == 1:
            return matches[0]
    return None
