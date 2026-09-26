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

from pxr import Sdf, Usd

from bowerbot.schemas import (
    AssetFormat,
    ASWFLayerNames,
    DetectionOutcome,
    FolderDetection,
    IntakeRules,
)
from bowerbot.utils.core.bounds import bbox_cache, world_range
from bowerbot.utils.core.dependencies import resolve as resolve_dependencies
from bowerbot.utils.core.metrics import read_mpu, read_stage_metadata
from bowerbot.utils.core.references import count_scene_refs_to_asset_dir, get_prim_ref_paths

logger = logging.getLogger(__name__)


# ── Folder structure ──


def resolve_asset_file_path(
    raw: str,
    project_dir: Path | None,
    library_dir: Path | None,
) -> Path:
    """Resolve a relative asset path against project dir, then library dir."""
    p = Path(raw)
    if p.is_absolute():
        return p
    if project_dir is not None:
        candidate = project_dir / p
        if candidate.exists():
            return candidate
    if library_dir is not None:
        candidate = library_dir / p
        if candidate.exists():
            return candidate
    return p.resolve()


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
            for ext in AssetFormat.layer_formats():
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
    for ext in AssetFormat.layer_formats():
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
        ASWFLayerNames.PHY,
        ASWFLayerNames.CONTENTS,
        ASWFLayerNames.VARIANTS,
    }
    canonical |= {f"{asset_dir.name}{ext}" for ext in AssetFormat.layer_formats()}
    return sorted(
        p.name for p in asset_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in AssetFormat.layer_formats()
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


def compute_ref_asset_path(
    relative_asset_path: str,
    assets_dir: Path,
    container_dir: Path,
) -> str:
    """Compute the reference path from the container to the nested asset."""
    asset_full_path = (assets_dir.parent / relative_asset_path).resolve()
    try:
        ref_path = asset_full_path.relative_to(container_dir.resolve())
        return f"./{ref_path.as_posix()}"
    except ValueError:
        return (
            "../" + asset_full_path.relative_to(
                container_dir.parent.resolve(),
            ).as_posix()
        )


def to_asset_local(prim_path: str, ref_prim_path: str) -> str:
    """Strip the scene-side reference prefix to get an asset-local path."""
    if prim_path.startswith(ref_prim_path):
        remainder = prim_path[len(ref_prim_path):]
        return remainder if remainder else "/"
    return prim_path


def check_shared_modification(
    stage: Usd.Stage, asset_dir: Path, params: dict, *, op_label: str,
) -> None:
    """Refuse if *asset_dir* is referenced by 2+ scene instances and not confirmed."""
    instance_count = count_scene_refs_to_asset_dir(stage, asset_dir)
    confirmed = bool(params.get("confirm_shared_modification", False))
    if instance_count >= 2 and not confirmed:
        msg = (
            f"Asset folder '{asset_dir.name}/' is referenced by "
            f"{instance_count} scene instances. {op_label} writes to the "
            f"shared {ASWFLayerNames.MTL}, so the binding would apply to "
            f"all {instance_count} instances. Two ways forward: "
            f"(1) For per-instance materials (different material per "
            f"instance), use place_asset to make each instance independent, "
            f"then bind a material on each. "
            f"(2) For deliberate shared modification (every instance "
            f"should get this material), retry with "
            f"confirm_shared_modification=true."
        )
        raise ValueError(msg)


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


def ensure_side_layer(asset_dir: Path, layer_file: str) -> Path:
    """Create *layer_file* in *asset_dir* (default prim ``over``) if missing; return its path."""
    path = asset_dir / layer_file
    if path.exists():
        return path
    default_prim_name = resolve_default_prim_name(asset_dir)
    layer = Sdf.Layer.CreateNew(str(path))
    layer.defaultPrim = default_prim_name
    root = Sdf.CreatePrimInLayer(layer, Sdf.Path(f"/{default_prim_name}"))
    root.specifier = Sdf.SpecifierOver
    layer.Save()
    return path


def delete_side_layer(asset_dir: Path, layer_file: str) -> None:
    """Drop *layer_file* from the root's references and delete it from disk."""
    remove_root_reference(asset_dir, layer_file)
    path = asset_dir / layer_file
    if not path.exists():
        return
    layer = Sdf.Layer.FindOrOpen(str(path))
    if layer is not None:
        layer.Clear()
    path.unlink()


def remove_root_reference(asset_dir: Path, layer_file: str) -> None:
    """Remove ``./<layer_file>`` from the asset root's reference list."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    prim_spec = layer.GetPrimAtPath(f"/{resolve_default_prim_name(asset_dir)}")
    if prim_spec is None:
        return
    target = f"./{layer_file}"
    ref_list = prim_spec.referenceList
    for items in (
        ref_list.prependedItems,
        ref_list.appendedItems,
        ref_list.addedItems,
        ref_list.explicitItems,
        ref_list.orderedItems,
    ):
        for ref in [r for r in items if r.assetPath == target]:
            items.remove(ref)
    layer.Save()


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

    for layer_file in ASWFLayerNames.REFERENCE_ORDER:
        if (asset_dir / layer_file).exists():
            root_prim.GetReferences().AddReference(f"./{layer_file}")

    stage.Save()


# ── Stage metadata ──


def read_stage_metadata_from_dir(asset_dir: Path) -> tuple[float, str]:
    """Return ``(metersPerUnit, upAxis)`` from an asset's ``geo.usda``."""
    geo_path = asset_dir / ASWFLayerNames.GEO
    if geo_path.exists():
        return read_stage_metadata(geo_path)
    return 1.0, "Y"


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
        if p.is_file() and p.suffix.lower() in AssetFormat.layer_formats()
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
    for stem in (folder_name, *IntakeRules.ROOT_NAME_HINTS):
        matches = [p for p in candidates if p.stem == stem]
        if len(matches) == 1:
            return matches[0]
    return None


def get_geometry_bounds(
    asset_dir: Path,
) -> dict[str, dict[str, float]] | None:
    """Return the asset's geometry bounds in meters, or ``None``."""
    geo_path = asset_dir / ASWFLayerNames.GEO
    if not geo_path.exists():
        return None

    stage = Usd.Stage.Open(str(geo_path))
    if stage is None:
        return None

    root = stage.GetDefaultPrim()
    if root is None:
        return None

    rng = world_range(root, bbox_cache())
    if rng is None:
        return None

    mpu, _ = read_stage_metadata_from_dir(asset_dir)
    mn = rng.GetMin()
    mx = rng.GetMax()

    return {
        "min": {"x": mn[0] * mpu, "y": mn[1] * mpu, "z": mn[2] * mpu},
        "max": {"x": mx[0] * mpu, "y": mx[1] * mpu, "z": mx[2] * mpu},
        "center": {
            "x": (mn[0] + mx[0]) / 2 * mpu,
            "y": (mn[1] + mx[1]) / 2 * mpu,
            "z": (mn[2] + mx[2]) / 2 * mpu,
        },
        "size": {
            "x": (mx[0] - mn[0]) * mpu,
            "y": (mx[1] - mn[1]) * mpu,
            "z": (mx[2] - mn[2]) * mpu,
        },
    }


def get_mpu(asset_dir: Path) -> float:
    """Return the asset's ``metersPerUnit`` (from ``geo.usda``), defaulting to 1.0."""
    geo_path = asset_dir / ASWFLayerNames.GEO
    return read_mpu(geo_path) if geo_path.exists() else 1.0


def unit_factor(asset_dir: Path) -> float:
    """Return the factor that converts meters into asset units."""
    mpu = get_mpu(asset_dir)
    return 1.0 / mpu if mpu > 0 else 1.0


def parse_nested_contents_path(prim_path: str) -> tuple[str, str] | None:
    """If *prim_path* is a nested-asset wrapper, return (group, prim_name)."""
    marker = "/asset/contents/"
    idx = prim_path.find(marker)
    if idx >= 0:
        suffix = prim_path[idx + len(marker):]
        parts = [p for p in suffix.split("/") if p]
        if len(parts) == 2:
            return parts[0], parts[1]
        msg = (
            f"Path {prim_path} is inside a nested asset's contents but "
            f"not at the wrapper level. Only the wrapper "
            f"(.../asset/contents/<group>/<name>) can be edited; deeper "
            f"prims live inside the referenced nested asset and editing "
            f"them at scene level would create per-instance overrides."
        )
        raise ValueError(msg)

    if "/asset/" in prim_path or prim_path.endswith("/asset"):
        msg = (
            f"Path {prim_path} is inside a referenced top-level asset. "
            f"Only the scene-level wrapper (/Scene/<Group>/<Name>) and "
            f"nested wrappers (.../asset/contents/<group>/<name>) can be "
            f"edited; everything else lives inside the referenced asset "
            f"and editing it at scene level would create per-instance "
            f"overrides."
        )
        raise ValueError(msg)

    return None
