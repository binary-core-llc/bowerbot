# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Bringing a library asset into the project: copy it, then check its geometry."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from pxr import Sdf
from pxr import UsdUtils

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import usd

logger = logging.getLogger(__name__)

# ── Bringing an asset into the project ──


def prepare_asset(
    asset_path: Path,
    assets_dir: Path,
    *,
    library_dir: Path | None,
    project_mpu: float,
    project_up_axis: str,
    fix_root_prim: bool = False,
    fix_root_transforms: bool = False,
) -> schemas.IntakeReport:
    """Bring a library asset into the project: a .usdz, an asset folder or a geometry file."""
    authoring.accepted_shapes.require(asset_path, library_dir)
    if asset_path.suffix.lower() == ".usdz":
        return intake_usdz(asset_path, assets_dir)

    if library_dir is not None:
        package_dir = authoring.accepted_shapes.asset_folder_for(asset_path, library_dir)
        if package_dir is not None:
            report = intake_folder(
                package_dir, assets_dir,
                project_mpu=project_mpu, project_up_axis=project_up_axis,
            )
            _validate_intake(
                report, assets_dir,
                fix_root_prim=fix_root_prim,
                fix_root_transforms=fix_root_transforms,
            )
            return report

    folder_name = asset_path.stem
    root_file = authoring.asset_folder.create_asset_folder(
        output_dir=assets_dir,
        asset_name=folder_name,
        geometry_file=asset_path,
        project_mpu=project_mpu,
        project_up_axis=project_up_axis,
    )
    report = schemas.IntakeReport(
        scene_ref_path=f"assets/{folder_name}/{root_file.name}",
        asset_folder_name=folder_name,
        root_original_name=asset_path.name,
        root_canonical_name=root_file.name,
        was_renamed=asset_path.name != root_file.name,
        files_copied=1,
    )
    _validate_intake(
        report, assets_dir,
        fix_root_prim=fix_root_prim,
        fix_root_transforms=fix_root_transforms,
    )
    return report


def intake_target_name(asset_path: Path, library_dir: Path | None) -> str:
    """Return the assets/ entry name prepare_asset would stage for *asset_path*."""
    if asset_path.suffix.lower() == ".usdz":
        return asset_path.name
    if library_dir is not None:
        package_dir = authoring.accepted_shapes.asset_folder_for(asset_path, library_dir)
        if package_dir is not None:
            return package_dir.name
    return asset_path.stem


def intake_folder(
    source_folder: Path,
    project_assets_dir: Path,
    *,
    project_mpu: float,
    project_up_axis: str,
) -> schemas.IntakeReport:
    """Copy the asset folder *source_folder* and the files its root depends on into the project."""
    source_folder = source_folder.resolve()
    project_assets_dir = project_assets_dir.resolve()
    source_root = authoring.accepted_shapes.folder_root_file(source_folder)
    if source_root is None:
        msg = f"{source_folder.name}/ has no root file named like the folder."
        raise ValueError(msg)
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

    layer_sources = [Path(lyr.realPath).resolve() for lyr in layers]
    path_map = {
        src: target_folder / src.relative_to(source_folder)
        for src in (*layer_sources, *(Path(a).resolve() for a in assets))
    }
    layer_targets = [path_map[src] for src in layer_sources]

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

        authoring.asset_folder.normalize_root_metadata(canonical_root, target_folder.name)
        authoring.asset_folder.declare_missing_metrics(
            canonical_root, project_mpu=project_mpu, project_up_axis=project_up_axis,
        )
        authoring.asset_folder.rebuild_root_references(target_folder)
        warnings = _validate_self_contained(canonical_root, target_folder)
    except Exception:
        shutil.rmtree(target_folder, ignore_errors=True)
        raise

    logger.info(
        "Intaked %s -> %s (%d file(s))",
        source_folder.name, target_folder.name, files_copied,
    )
    return schemas.IntakeReport(
        scene_ref_path=f"assets/{target_folder.name}/{canonical_root.name}",
        asset_folder_name=target_folder.name,
        root_original_name=source_root.name,
        root_canonical_name=canonical_root.name,
        was_renamed=was_renamed,
        files_copied=files_copied,
        warnings=warnings,
    )


def intake_usdz(asset_path: Path, assets_dir: Path) -> schemas.IntakeReport:
    """Copy a USDZ into *assets_dir* as-is."""
    local_copy = assets_dir / asset_path.name
    copied = 0
    if not local_copy.exists():
        shutil.copy2(asset_path, local_copy)
        copied = 1
    return schemas.IntakeReport(
        scene_ref_path=f"assets/{asset_path.name}",
        asset_folder_name=asset_path.stem,
        root_original_name=asset_path.name,
        root_canonical_name=asset_path.name,
        was_renamed=False,
        files_copied=copied,
    )


# ── Checking and repairing geometry ──


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

    if not usd.transforms.root_transform_is_identity(geometry_file):
        if not fix_root_transforms:
            msg = (
                f"Asset '{geometry_file.name}' has non-identity transforms "
                f"baked on its root prim (translate/rotate/scale/pivot from "
                f"an unfrozen DCC export). Production USD assets must have "
                f"identity root transforms, or adding one to another asset breaks. Ask "
                f"the user if they want BowerBot to bake the transforms into "
                f"vertex data automatically — this only modifies the project "
                f"copy, the user's original source file is untouched. If they "
                f"confirm, call place_asset again with fix_root_transforms=true. "
                f"Alternatively, advise them to re-export from their DCC with "
                f"transforms frozen ('Bake Transforms' in Maya USD export, "
                f"'Pre-freeze' in Houdini)."
            )
            raise ValueError(msg)
        usd.transforms.bake_root_transforms(geometry_file)
        logger.info("Baked root transforms in %s", geometry_file.name)


def freeze_one_asset(assets_dir: Path, name: str) -> dict:
    """Bake root transforms in a single asset folder; raise if folder/geo missing."""
    asset_dir = assets_dir / name
    if not asset_dir.exists() or not asset_dir.is_dir():
        msg = f"Asset folder not found: {name}"
        raise ValueError(msg)

    geo_path = asset_dir / constants.ASWFLayerNames.GEO
    if not geo_path.exists():
        msg = f"No {constants.ASWFLayerNames.GEO} in asset folder '{name}'"
        raise ValueError(msg)

    baked = usd.transforms.bake_root_transforms(geo_path)
    return {"name": name, "baked": baked}


# ── Reporting an intake ──


def intake_summary(report: schemas.IntakeReport) -> dict:
    """Condense an intake report into the fields surfaced to the LLM."""
    return {
        "asset_folder": report.asset_folder_name,
        "root_canonical_name": report.root_canonical_name,
        "was_renamed": report.was_renamed,
        "root_original_name": (
            report.root_original_name if report.was_renamed else None
        ),
        "files_copied": report.files_copied,
        "warnings": report.warnings,
    }


def placement_message(
    asset_name: str, prim_path: str, report: schemas.IntakeReport,
) -> str:
    """Format a placement message that narrates intake normalization."""
    parts = [f"Placed {asset_name} at {prim_path}."]
    if report.was_renamed:
        parts.append(
            f"Normalized on intake: {report.root_original_name} -> "
            f"{report.root_canonical_name} (ASWF convention).",
        )
    return " ".join(parts)


# ── Helpers ──


def _validate_intake(
    report: schemas.IntakeReport,
    assets_dir: Path,
    *,
    fix_root_prim: bool,
    fix_root_transforms: bool,
) -> None:
    """Validate the intaken asset's geo.usda; rollback target on failure."""
    target_folder = assets_dir / report.asset_folder_name
    geo_path = target_folder / constants.ASWFLayerNames.GEO
    if not geo_path.exists():
        return
    try:
        ensure_aswf_compliance(
            geo_path,
            fix_root_prim=fix_root_prim,
            fix_root_transforms=fix_root_transforms,
        )
    except (ValueError, RuntimeError):
        if target_folder.exists():
            shutil.rmtree(target_folder, ignore_errors=True)
        raise

    canonical_root = target_folder / report.root_canonical_name
    if canonical_root.exists():
        compliance_issues = usd.compliance.run_usd_compliance_checker(canonical_root)
        for issue in compliance_issues:
            report.warnings.append(issue.message)
            logger.info(
                "ComplianceChecker on %s: %s",
                report.asset_folder_name, issue.message,
            )


def _reuse_existing_target(target_folder: Path, source_root: Path) -> schemas.IntakeReport:
    """Build an IntakeReport for a target folder that already exists."""
    canonical = target_folder / f"{target_folder.name}.usda"
    if not canonical.exists():
        msg = (
            f"Target folder {target_folder} exists but has no canonical "
            f"root '{canonical.name}'. Delete it and retry."
        )
        raise RuntimeError(msg)
    authoring.asset_folder.normalize_root_metadata(canonical, target_folder.name)
    return schemas.IntakeReport(
        scene_ref_path=f"assets/{target_folder.name}/{canonical.name}",
        asset_folder_name=target_folder.name,
        root_original_name=source_root.name,
        root_canonical_name=canonical.name,
        was_renamed=source_root.name != canonical.name,
        files_copied=0,
        warnings=["target folder already existed; source was not re-copied"],
    )


def _is_inside(path: Path, folder: Path) -> bool:
    """Return True if *path* is a descendant of *folder*."""
    try:
        path.relative_to(folder)
    except ValueError:
        return False
    return True


def _rewrite_asset_paths(
    layer_targets: list[Path], path_map: dict[Path, Path],
) -> None:
    """Point every asset path in *layer_targets* that names a copied file at its copy."""
    resolved_map = {src.resolve(): dst.resolve() for src, dst in path_map.items()}
    source_of = {dst: src for src, dst in resolved_map.items()}

    for layer_path in layer_targets:
        layer = Sdf.Layer.FindOrOpen(str(layer_path))
        if layer is None:
            msg = f"Could not open copied layer for rewrite: {layer_path}"
            raise RuntimeError(msg)

        layer_dir = layer_path.parent.resolve()
        source = source_of.get(layer_path.resolve())
        source_dir = source.parent if source is not None else layer_dir

        def _rewrite(
            asset_path: str, _layer_dir: Path = layer_dir, _source_dir: Path = source_dir,
        ) -> str:
            if not asset_path:
                return asset_path
            try:
                target = resolved_map.get((_source_dir / asset_path).resolve())
                already_there = (
                    target is not None and (_layer_dir / asset_path).resolve() == target
                )
            except (OSError, ValueError):
                return asset_path
            if target is None or already_there:
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
            f"path(s) became unresolved after the copy."
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
            f"still point outside the asset folder after the copy."
        )
        raise RuntimeError(msg)

    return []


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
