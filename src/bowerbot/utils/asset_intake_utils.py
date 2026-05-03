# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset intake primitives — bring source folders into the project.

USD-write side of the asset domain: folder copy + canonicalize +
localize external dependencies, plus loose-file ASWF folder creation
and ASWF compliance repair, plus nested asset reference authoring.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdUtils

from bowerbot.schemas import (
    ASWFLayerNames,
    DetectionOutcome,
    IntakeReport,
    TransformParams,
)
from bowerbot.utils.asset_folder_utils import (
    detect_folder_root,
    ensure_layer_scope,
    ensure_root_reference,
    read_asset_mpu_from_file,
    read_stage_metadata,
    rebuild_root_references,
    remove_empty_layer,
    resolve_default_prim_name,
)
from bowerbot.utils.geometry_utils import get_mpu

logger = logging.getLogger(__name__)


# ── Folder intake ──


def intake_folder(source_folder: Path, project_assets_dir: Path) -> IntakeReport:
    """Copy *source_folder* into *project_assets_dir* as a self-contained asset.

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

        _normalize_root_metadata(canonical_root, target_folder.name)
        rebuild_root_references(target_folder)
        warnings = _validate_self_contained(canonical_root, target_folder)
    except Exception:
        shutil.rmtree(target_folder, ignore_errors=True)
        raise

    logger.info(
        "Intaked %s -> %s (%d file(s), %d localized)",
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


def intake_usdz(asset_path: Path, assets_dir: Path) -> IntakeReport:
    """Copy a USDZ into *assets_dir* as-is."""
    local_copy = assets_dir / asset_path.name
    copied = 0
    if not local_copy.exists():
        shutil.copy2(asset_path, local_copy)
        copied = 1
    return IntakeReport(
        scene_ref_path=f"assets/{asset_path.name}",
        asset_folder_name=asset_path.stem,
        root_original_name=asset_path.name,
        root_canonical_name=asset_path.name,
        was_renamed=False,
        files_copied=copied,
    )


# ── Loose-file wrapping ──


def create_asset_folder(
    output_dir: Path,
    asset_name: str,
    geometry_file: Path,
) -> Path:
    """Create an ASWF asset folder with root + ``geo.usda``."""
    asset_dir = output_dir / asset_name
    asset_dir.mkdir(parents=True, exist_ok=True)

    mpu, up = read_stage_metadata(geometry_file)

    geo_path = asset_dir / ASWFLayerNames.GEO
    if not geo_path.exists():
        _create_geo_layer(geo_path, geometry_file)

    root_path = asset_dir / f"{asset_name}.usda"
    if not root_path.exists():
        _create_root_file(root_path, mpu, up)

    logger.info("Created ASWF asset folder: %s", asset_dir)
    return root_path


def ensure_aswf_compliance(
    geometry_file: Path,
    *,
    fix_root_prim: bool = False,
    fix_root_transforms: bool = False,
) -> None:
    """Validate and (optionally) repair a geometry file for ASWF compliance."""
    layer = Sdf.Layer.FindOrOpen(str(geometry_file))
    if layer is None:
        msg = f"Cannot open geometry file: {geometry_file.name}"
        raise ValueError(msg)

    root_prims = list(layer.rootPrims)

    if not root_prims:
        msg = (
            f"Asset '{geometry_file.name}' contains no geometry. "
            f"Export it from your DCC with geometry under a root prim."
        )
        raise ValueError(msg)

    if not layer.defaultPrim:
        if len(root_prims) == 1:
            layer.defaultPrim = root_prims[0].name
            layer.Save()
            logger.info(
                "Auto-set defaultPrim to '%s' in %s",
                root_prims[0].name, geometry_file.name,
            )
        else:
            prim_names = ", ".join(p.name for p in root_prims)
            msg = (
                f"Asset '{geometry_file.name}' has multiple root prims "
                f"({prim_names}) and no defaultPrim. Export it from your "
                f"DCC with a single root Xform."
            )
            raise ValueError(msg)

    root_spec = layer.GetPrimAtPath(Sdf.Path(f"/{layer.defaultPrim}"))
    if root_spec is None:
        msg = (
            f"Asset '{geometry_file.name}' has defaultPrim "
            f"'{layer.defaultPrim}' but that prim does not exist."
        )
        raise ValueError(msg)

    if root_spec.typeName not in ("Xform", ""):
        if not fix_root_prim:
            msg = (
                f"Asset '{geometry_file.name}' has a {root_spec.typeName} "
                f"as its root prim instead of an Xform. Per ASWF USD "
                f"guidelines, the root prim should be an Xform with "
                f"geometry as children. Ask the user if they want to "
                f"fix this automatically, then call place_asset again "
                f"with fix_root_prim set to true."
            )
            raise ValueError(msg)
        _wrap_root_prim(geometry_file)
        logger.info(
            "Wrapped %s root prim in Xform for ASWF compliance",
            geometry_file.name,
        )

    if not _root_transform_is_identity(geometry_file):
        if not fix_root_transforms:
            msg = (
                f"Asset '{geometry_file.name}' has non-identity transforms "
                f"baked on its root prim (translate/rotate/scale/pivot from "
                f"an unfrozen DCC export). Production USD assets must have "
                f"identity root transforms or nested placement breaks. Ask "
                f"the user if they want BowerBot to bake the transforms into "
                f"vertex data automatically — this only modifies the project "
                f"copy, the user's original source file is untouched. If they "
                f"confirm, call place_asset again with fix_root_transforms=true. "
                f"Alternatively, advise them to re-export from their DCC with "
                f"transforms frozen ('Bake Transforms' in Maya USD export, "
                f"'Pre-freeze' in Houdini)."
            )
            raise ValueError(msg)
        bake_root_transforms(geometry_file)
        logger.info("Baked root transforms in %s", geometry_file.name)


def bake_root_transforms(geometry_file: Path) -> bool:
    """Bake the root prim's local transform into descendant geometry."""
    stage = Usd.Stage.Open(str(geometry_file))
    if stage is None:
        return False

    root_prim = stage.GetDefaultPrim()
    if not root_prim or not root_prim.IsValid():
        return False

    xformable = UsdGeom.Xformable(root_prim)
    if not xformable:
        return False

    matrix = xformable.GetLocalTransformation()
    if _matrix_is_identity(matrix):
        return False

    normal_matrix = matrix.GetInverse().GetTranspose()

    for prim in Usd.PrimRange(root_prim):
        pb = UsdGeom.PointBased(prim)
        if not pb:
            continue
        _bake_into_point_based(pb, matrix, normal_matrix)

    xformable.ClearXformOpOrder()
    for prop_name in list(root_prim.GetPropertyNames()):
        if prop_name.startswith("xformOp:") or prop_name == "xformOpOrder":
            root_prim.RemoveProperty(prop_name)

    stage.Save()
    return True


def _root_transform_is_identity(geometry_file: Path) -> bool:
    """Return True if the file's defaultPrim has identity local transform."""
    stage = Usd.Stage.Open(str(geometry_file))
    if stage is None:
        return True
    prim = stage.GetDefaultPrim()
    if not prim or not prim.IsValid():
        return True
    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        return True
    return _matrix_is_identity(xformable.GetLocalTransformation())


def _matrix_is_identity(matrix: Gf.Matrix4d, epsilon: float = 1e-5) -> bool:
    """Return True if *matrix* is the identity matrix within *epsilon*."""
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            if abs(matrix[i, j] - expected) > epsilon:
                return False
    return True


def _bake_into_point_based(
    pb: UsdGeom.PointBased,
    matrix: Gf.Matrix4d,
    normal_matrix: Gf.Matrix4d,
) -> None:
    """Apply *matrix* to a PointBased prim's points / normals / extent."""
    points_attr = pb.GetPointsAttr()
    points = points_attr.Get()
    if points is None or len(points) == 0:
        return

    new_points = [matrix.Transform(p) for p in points]
    points_attr.Set(new_points)

    normals_attr = pb.GetNormalsAttr()
    normals = normals_attr.Get()
    if normals is not None and len(normals) > 0:
        new_normals = [
            normal_matrix.TransformDir(n).GetNormalized() for n in normals
        ]
        normals_attr.Set(new_normals)

    extent_attr = pb.GetExtentAttr()
    if extent_attr.HasAuthoredValue():
        xs = [p[0] for p in new_points]
        ys = [p[1] for p in new_points]
        zs = [p[2] for p in new_points]
        extent_attr.Set([
            Gf.Vec3f(min(xs), min(ys), min(zs)),
            Gf.Vec3f(max(xs), max(ys), max(zs)),
        ])


# ── Nested references ──


def add_nested_asset_reference(
    container_dir: Path,
    group: str,
    prim_name: str,
    ref_asset_path: str,
    transform: TransformParams,
) -> str:
    """Author a nested asset reference inside a container's ``contents.usda``."""
    contents_path = container_dir / ASWFLayerNames.CONTENTS
    default_prim_name = resolve_default_prim_name(container_dir)

    if contents_path.exists():
        contents_layer = Sdf.Layer.FindOrOpen(str(contents_path))
    else:
        contents_layer = Sdf.Layer.CreateNew(str(contents_path))
        contents_layer.defaultPrim = default_prim_name

    ensure_layer_scope(contents_layer, default_prim_name, "contents", "Xform")
    _ensure_group_scope(contents_layer, default_prim_name, group)
    contents_layer.Save()

    stage = Usd.Stage.Open(str(contents_path))
    if stage is None:
        msg = f"Cannot open contents layer: {contents_path}"
        raise RuntimeError(msg)

    wrapper_path = f"/{default_prim_name}/contents/{group}/{prim_name}"
    wrapper = UsdGeom.Xform.Define(stage, wrapper_path)

    container_mpu = get_mpu(container_dir)
    factor = 1.0 / container_mpu if container_mpu > 0 else 1.0

    ref_full_path = (container_dir / ref_asset_path).resolve()
    nested_mpu = (
        read_asset_mpu_from_file(ref_full_path)
        if ref_full_path.exists() else container_mpu
    )
    unit_scale = (
        nested_mpu / container_mpu if container_mpu > 0 else 1.0
    )

    sx, sy, sz = transform.scale
    final_scale = (sx * unit_scale, sy * unit_scale, sz * unit_scale)

    xformable = UsdGeom.Xformable(wrapper)
    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(
        Gf.Vec3d(
            transform.translate[0] * factor,
            transform.translate[1] * factor,
            transform.translate[2] * factor,
        ),
    )
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(*transform.rotate))
    xformable.AddScaleOp().Set(Gf.Vec3f(*final_scale))

    asset_inner = stage.DefinePrim(f"{wrapper_path}/asset", "Xform")
    asset_inner.GetReferences().AddReference(ref_asset_path)

    stage.Save()
    ensure_root_reference(container_dir, ASWFLayerNames.CONTENTS)

    logger.info(
        "Added nested asset %s -> %s in %s/%s",
        prim_name, ref_asset_path, container_dir.name, ASWFLayerNames.CONTENTS,
    )
    return wrapper_path


def update_nested_asset_transform(
    container_dir: Path,
    group: str,
    prim_name: str,
    translate: tuple[float, float, float],
    rotate: tuple[float, float, float],
) -> bool:
    """Update translate/rotate on a nested-asset wrapper in ``contents.usda``."""
    contents_path = container_dir / ASWFLayerNames.CONTENTS
    if not contents_path.exists():
        return False

    default_prim_name = resolve_default_prim_name(container_dir)
    wrapper_path = f"/{default_prim_name}/contents/{group}/{prim_name}"

    stage = Usd.Stage.Open(str(contents_path))
    if stage is None:
        return False
    wrapper = stage.GetPrimAtPath(wrapper_path)
    if not wrapper or not wrapper.IsValid():
        return False

    container_mpu = get_mpu(container_dir)
    factor = 1.0 / container_mpu if container_mpu > 0 else 1.0

    xformable = UsdGeom.Xformable(wrapper)
    existing_scale_op = next(
        (op for op in xformable.GetOrderedXformOps()
         if op.GetOpType() == UsdGeom.XformOp.TypeScale),
        None,
    )
    existing_scale = (
        existing_scale_op.Get() if existing_scale_op is not None
        else Gf.Vec3f(1.0, 1.0, 1.0)
    )

    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(
        Gf.Vec3d(translate[0] * factor, translate[1] * factor, translate[2] * factor),
    )
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(*rotate))
    xformable.AddScaleOp().Set(existing_scale)

    stage.Save()
    logger.info(
        "Updated nested transform %s in %s/%s",
        prim_name, container_dir.name, ASWFLayerNames.CONTENTS,
    )
    return True


def remove_nested_asset_reference(
    container_dir: Path,
    group: str,
    prim_name: str,
) -> bool:
    """Remove a nested asset reference from a container's ``contents.usda``.

    Idempotent: returns True whether the spec was deleted or was already
    absent. Returns False only on a real error (cannot open the layer).
    Empty group scopes and an empty contents layer are cleaned up
    automatically via :func:`cleanup_unused_contents_in_folder`.
    """
    contents_path = container_dir / ASWFLayerNames.CONTENTS
    if not contents_path.exists():
        return True

    layer = Sdf.Layer.FindOrOpen(str(contents_path))
    if layer is None:
        return False

    default_prim_name = resolve_default_prim_name(container_dir)
    parent_path = Sdf.Path(f"/{default_prim_name}/contents/{group}")
    parent_spec = layer.GetPrimAtPath(parent_path)
    if parent_spec is not None and prim_name in parent_spec.nameChildren:
        del parent_spec.nameChildren[prim_name]
        layer.Save()
        logger.info(
            "Removed nested asset %s from %s/%s",
            prim_name, container_dir.name, ASWFLayerNames.CONTENTS,
        )

    cleanup_unused_contents_in_folder(container_dir)
    return True


def cleanup_unused_contents_in_folder(container_dir: Path) -> list[str]:
    """Drop empty group scopes in *container_dir*'s ``contents.usda``.

    Mirrors :func:`bowerbot.utils.material_utils.cleanup_unused_in_folder`:
    removes per-prim entries that no longer carry meaningful data, then
    deletes the layer file when it has nothing left and rebuilds the
    root references without it. For contents, "meaningful" means a
    reference arc; empty group scopes (``Props``, ``Furniture``, etc.)
    are the unused entries.
    """
    contents_path = container_dir / ASWFLayerNames.CONTENTS
    if not contents_path.exists():
        return []

    layer = Sdf.Layer.FindOrOpen(str(contents_path))
    if layer is None:
        return []

    default_prim_name = resolve_default_prim_name(container_dir)
    contents_scope_path = Sdf.Path(f"/{default_prim_name}/contents")
    contents_spec = layer.GetPrimAtPath(contents_scope_path)

    removed: list[str] = []
    if contents_spec is not None:
        empty_groups = [
            child_name for child_name in list(contents_spec.nameChildren.keys())
            if len(contents_spec.nameChildren[child_name].nameChildren) == 0
        ]
        for child_name in empty_groups:
            del contents_spec.nameChildren[child_name]
            removed.append(child_name)
        if removed:
            layer.Save()

    remove_empty_layer(
        contents_path, container_dir, lambda p: p.HasAuthoredReferences(),
    )

    if removed:
        logger.info(
            "Cleaned %d empty group(s) from %s/%s",
            len(removed), container_dir.name, ASWFLayerNames.CONTENTS,
        )
    return removed


# ── Internal: intake helpers ──


def _reuse_existing_target(target_folder: Path, source_root: Path) -> IntakeReport:
    """Build an IntakeReport for a target folder that already exists."""
    canonical = target_folder / f"{target_folder.name}.usda"
    if not canonical.exists():
        msg = (
            f"Target folder {target_folder} exists but has no canonical "
            f"root '{canonical.name}'. Delete it and retry."
        )
        raise RuntimeError(msg)
    _normalize_root_metadata(canonical, target_folder.name)
    return IntakeReport(
        scene_ref_path=f"assets/{target_folder.name}/{canonical.name}",
        asset_folder_name=target_folder.name,
        root_original_name=source_root.name,
        root_canonical_name=canonical.name,
        was_renamed=source_root.name != canonical.name,
        files_copied=0,
        warnings=["target folder already existed; source was not re-copied"],
    )


def _plan_copies(
    source_folder: Path,
    target_folder: Path,
    layer_sources: Iterable[Path],
    asset_sources: Iterable[Path],
) -> tuple[dict[Path, Path], list[Path], list[str], list[str]]:
    """Return ``(path_map, layer_targets, localized_layers, localized_assets)``."""
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


def _normalize_root_metadata(root_file: Path, asset_name: str) -> None:
    """Ensure the intaken asset's root prim has Kind + assetInfo set."""
    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return
    root_prim = stage.GetDefaultPrim()
    if not root_prim or not root_prim.IsValid():
        return

    apply_aswf_root_metadata(
        root_prim,
        asset_name=asset_name,
        asset_identifier=f"./{root_file.name}",
    )
    stage.Save()


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


# ── Internal: nested + folder-creation helpers ──


def _ensure_group_scope(
    layer: Sdf.Layer, default_prim_name: str, group: str,
) -> None:
    """Ensure ``/{root}/contents/{group}`` exists as an Xform."""
    group_path = Sdf.Path(f"/{default_prim_name}/contents/{group}")
    if layer.GetPrimAtPath(group_path):
        return
    Sdf.CreatePrimInLayer(layer, group_path)
    group_prim = layer.GetPrimAtPath(group_path)
    group_prim.specifier = Sdf.SpecifierDef
    group_prim.typeName = "Xform"


def _create_geo_layer(geo_dest: Path, geometry_source: Path) -> None:
    """Copy geometry into ``geo.usda`` using Sdf layer copy."""
    source_layer = Sdf.Layer.FindOrOpen(str(geometry_source))
    if source_layer is None:
        msg = f"Cannot open geometry source: {geometry_source}"
        raise RuntimeError(msg)

    dest_layer = Sdf.Layer.CreateNew(str(geo_dest))
    for prim_spec in source_layer.rootPrims:
        Sdf.CopySpec(
            source_layer, prim_spec.path, dest_layer, prim_spec.path,
        )
    dest_layer.defaultPrim = source_layer.defaultPrim
    dest_layer.Save()


def _create_root_file(
    root_path: Path,
    meters_per_unit: float,
    up_axis: str,
) -> None:
    """Write the root .usd that references ``geo.usda``."""
    geo_path = root_path.parent / ASWFLayerNames.GEO
    default_prim_name = root_path.parent.name
    if geo_path.exists():
        geo_layer = Sdf.Layer.FindOrOpen(str(geo_path))
        if geo_layer and geo_layer.defaultPrim:
            default_prim_name = geo_layer.defaultPrim

    stage = Usd.Stage.CreateNew(str(root_path))
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    UsdGeom.SetStageUpAxis(
        stage, UsdGeom.Tokens.y if up_axis == "Y" else UsdGeom.Tokens.z,
    )

    root_prim = stage.DefinePrim(f"/{default_prim_name}", "Xform")
    stage.SetDefaultPrim(root_prim)
    root_prim.GetPayloads().AddPayload(f"./{ASWFLayerNames.GEO}")

    apply_aswf_root_metadata(
        root_prim,
        asset_name=root_path.parent.name,
        asset_identifier=f"./{root_path.name}",
        force=True,
    )

    stage.Save()


def apply_aswf_root_metadata(
    prim: Usd.Prim,
    *,
    asset_name: str,
    asset_identifier: str,
    kind: str = "component",
    version: str = "1.0",
    force: bool = False,
) -> None:
    """Apply ASWF-canonical Kind + assetInfo to an asset root prim.

    When *force* is False, only fills missing fields, preserving any
    metadata already authored upstream (DCC, asset-management system).
    """
    model_api = Usd.ModelAPI(prim)
    if force or not model_api.GetKind():
        model_api.SetKind(kind)

    existing = prim.GetAssetInfo() or {}
    info = dict(existing) if not force else {}
    info.setdefault("identifier", Sdf.AssetPath(asset_identifier))
    info.setdefault("name", asset_name)
    info.setdefault("version", version)
    if force:
        info["identifier"] = Sdf.AssetPath(asset_identifier)
        info["name"] = asset_name
        info["version"] = version
    prim.SetAssetInfo(info)


def _wrap_root_prim(geometry_file: Path) -> None:
    """Wrap a non-Xform root prim under an Xform parent in place."""
    source_layer = Sdf.Layer.FindOrOpen(str(geometry_file))
    if source_layer is None:
        return

    default_prim_name = source_layer.defaultPrim
    if not default_prim_name:
        return

    root_path = Sdf.Path(f"/{default_prim_name}")
    root_spec = source_layer.GetPrimAtPath(root_path)
    if root_spec is None or root_spec.typeName in ("Xform", ""):
        return

    with tempfile.NamedTemporaryFile(suffix=".usda", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        dest_layer = Sdf.Layer.CreateNew(str(tmp_path))

        Sdf.CreatePrimInLayer(dest_layer, root_path)
        wrapper = dest_layer.GetPrimAtPath(root_path)
        wrapper.specifier = Sdf.SpecifierDef
        wrapper.typeName = "Xform"

        child_path = Sdf.Path(f"/{default_prim_name}/mesh")
        Sdf.CopySpec(source_layer, root_path, dest_layer, child_path)

        dest_layer.defaultPrim = default_prim_name
        dest_layer.Save()

        shutil.move(str(tmp_path), str(geometry_file))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
