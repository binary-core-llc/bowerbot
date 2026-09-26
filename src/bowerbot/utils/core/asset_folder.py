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
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pxr import Gf, Sdf, Usd, UsdGeom

from bowerbot.schemas import (
    AssetFormat,
    AssetScopeNames,
    ASWFLayerNames,
    DetectionOutcome,
    FolderDetection,
    IntakeRules,
    SceneNamespace,
)
from bowerbot.utils.core.bounds import bbox_cache, world_range
from bowerbot.utils.core.dependencies import resolve as resolve_dependencies
from bowerbot.utils.core.metrics import read_mpu, read_stage_metadata
from bowerbot.utils.core.references import count_scene_refs_to_asset_dir, get_prim_ref_paths

logger = logging.getLogger(__name__)


# ── Folder structure ──


def resolve_library_file(
    raw: str,
    *,
    library_dir: Path | None,
    project_dir: Path | None,
    first_dir: Path | None = None,
) -> Path:
    """The existing file or folder *raw* names in the asset library or the project.

    BowerBot takes source files only from the configured asset library, plus
    files it already copied into the project. An absolute path must lie
    inside one of them; a relative one is tried against *first_dir* (a
    layout file's folder), the project, then the library. Anything else is
    refused, and so is a path that exists nowhere.
    """
    roots = [_absolute(d) for d in (library_dir, project_dir) if d is not None]
    if library_dir is None:
        msg = "No asset library configured. Set 'assets_dir' in ~/.bowerbot/config.json."
        raise ValueError(msg)
    path = Path(raw).expanduser()
    if path.is_absolute():
        candidates = [path]
    else:
        candidates = [d / path for d in (first_dir, project_dir, library_dir) if d is not None]
    for candidate in candidates:
        if not candidate.exists():
            continue
        found = _absolute(candidate)
        if not any(found == root or root in found.parents for root in roots):
            msg = (
                f"{found} is outside the asset library ({_absolute(library_dir)}). "
                f"BowerBot only takes files from the library: copy it there first, "
                f"then use the library path."
            )
            raise ValueError(msg)
        return found
    searched = ", ".join(str(_absolute(c)) for c in candidates)
    msg = (
        f"'{raw}' was not found in the asset library or the project "
        f"(searched: {searched})."
    )
    raise ValueError(msg)


def _absolute(path: Path) -> Path:
    """*path* made absolute with '..' collapsed, without following symlinks."""
    return Path(os.path.abspath(path.expanduser()))


def require_folder_entry(folder: Path, name: str) -> Path:
    """The file or folder *name* directly inside *folder*; refuses a name that leads elsewhere.

    Every tool that deletes or rewrites something named by the caller goes
    through this: an empty name, '.', '..', or a nested or absolute path
    never reaches outside *folder*.
    """
    if name in ("", ".", "..") or Path(name).name != name:
        msg = (
            f"{name!r} is not an entry of {folder}: pass the name of a file or "
            f"folder directly inside it (e.g. 'chair')."
        )
        raise ValueError(msg)
    return folder / name


def validate_asset_file(path: Path) -> Path:
    """Return *path* when it is a USD file BowerBot can place; raise a clear error otherwise."""
    if path.is_dir():
        raise ValueError(asset_folder_hint(path))
    if not path.is_file():
        raise ValueError(f"Asset file not found: {path}")
    if path.suffix.lower() not in AssetFormat:
        formats = ", ".join(AssetFormat)
        raise ValueError(f"{path} is not a USD file; BowerBot places {formats} assets.")
    return path


def asset_folder_hint(folder: Path) -> str:
    """Explain that *folder* is not a placeable file, naming the file to pass instead."""
    root_file = find_root_file(folder)
    if root_file is not None:
        return f"{folder} is a folder, not a USD file; pass its root file instead: {root_file}"
    usd_files = sorted(p.name for p in folder.iterdir() if p.suffix.lower() in AssetFormat)
    if usd_files:
        return (
            f"{folder} is a folder, not a USD file, and has no root file named after it; "
            f"pass one of its USD files instead: {', '.join(usd_files)}"
        )
    return f"{folder} is a folder with no USD file in it; pass the asset's root file instead."


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
    stage: Usd.Stage, asset_dir: Path, params: dict[str, Any], *, op_label: str,
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
    """Strip the scene namespace then anchor under the asset's default prim.

    The prim carrying the reference and its parent (a placement's wrapper,
    whose ``asset`` child references the asset) both map to the asset's root.
    """
    ref = Sdf.Path(ref_prim_path)
    wrapper = ref.GetParentPath() if ref.name == SceneNamespace.ASSET_CHILD else ref
    if prim_path in (ref_prim_path, str(wrapper)):
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
    """Reference ``./<layer_file>`` from the asset root, leaving every other arc as authored.

    BowerBot's side layers sit first in the root's reference list, in
    ``ASWFLayerNames.REFERENCE_ORDER``, so they are stronger than any
    reference the asset shipped with; payloads are never touched.
    """
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
    references = prim_spec.referenceList
    if any(ref.assetPath == target for ref in references.GetAddedOrExplicitItems()):
        return

    order = {f"./{name}": index for index, name in enumerate(ASWFLayerNames.REFERENCE_ORDER)}
    items = list(references.explicitItems if references.isExplicit else references.prependedItems)
    side_layers = [ref for ref in items if ref.assetPath in order] + [Sdf.Reference(target)]
    side_layers.sort(key=lambda ref: order[ref.assetPath])
    ordered = side_layers + [ref for ref in items if ref.assetPath not in order]
    if references.isExplicit:
        references.explicitItems = ordered
    else:
        references.prependedItems = ordered
    layer.Save()


def remove_empty_layer(
    layer_path: Path,
    asset_dir: Path,
    has_content: Callable[[Usd.Prim], bool],
) -> None:
    """Delete *layer_path* and its root reference when no prim in it satisfies *has_content*."""
    stage = Usd.Stage.Open(str(layer_path))
    if stage:
        for prim in stage.Traverse():
            if has_content(prim):
                return
    del stage
    delete_side_layer(asset_dir, layer_path.name)
    logger.info("Removed empty %s from %s", layer_path.name, asset_dir.name)


# ── Stage metadata ──


def read_stage_metadata_from_dir(asset_dir: Path) -> tuple[float, str]:
    """Return ``(metersPerUnit, upAxis)`` of the asset, read from its root file.

    The root is what a scene references, so its metadata is what the
    placement conforms to, whatever layers the asset keeps its geometry in.
    """
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return 1.0, "Y"
    return read_stage_metadata(root_file)


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
            default_prim: str = layer.defaultPrim
            return default_prim
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
    """Return the bounds of the asset's own geometry in meters, or ``None``.

    Read from the composed root, so geometry in any layer counts (a
    ``geo.usdc`` payload, the selected LOD variant); lights and nested
    ``contents`` placements do not.
    """
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return None
    stage = Usd.Stage.Open(str(root_file))
    root = stage.GetDefaultPrim() if stage is not None else None
    if not root:
        return None

    rng = _own_geometry_range(root, bbox_cache())
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


def _own_geometry_range(root: Usd.Prim, cache: UsdGeom.BBoxCache) -> Gf.Range3d | None:
    """Union of the gprims and point instancers under *root*, skipping ``contents``."""
    contents = root.GetPath().AppendChild(AssetScopeNames.CONTENTS)
    total = Gf.Range3d()
    prims = iter(Usd.PrimRange(root))
    for prim in prims:
        if prim.GetPath() == contents:
            prims.PruneChildren()
            continue
        if prim.IsA(UsdGeom.Gprim) or prim.IsA(UsdGeom.PointInstancer):
            rng = world_range(prim, cache)
            if rng is not None:
                total.UnionWith(rng)
            prims.PruneChildren()
    return None if total.IsEmpty() else total


def get_mpu(asset_dir: Path) -> float:
    """Return the asset's ``metersPerUnit`` (from its root file), defaulting to 1.0."""
    root_file = find_root_file(asset_dir)
    return read_mpu(root_file) if root_file is not None else 1.0


def unit_factor(asset_dir: Path) -> float:
    """Return the factor that converts meters into asset units."""
    mpu = get_mpu(asset_dir)
    return 1.0 / mpu if mpu > 0 else 1.0


def parse_nested_contents_path(prim_path: str) -> tuple[str, str] | None:
    """If *prim_path* is a nested-asset wrapper, return (group, prim_name)."""
    marker = f"/{SceneNamespace.ASSET_CHILD}/{AssetScopeNames.CONTENTS}/"
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

    marker = f"/{SceneNamespace.ASSET_CHILD}"
    if f"{marker}/" in prim_path or prim_path.endswith(marker):
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
