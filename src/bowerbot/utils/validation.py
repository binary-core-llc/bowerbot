# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage validation + USDZ packaging primitives."""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path

from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade
from pxr import UsdUtils
from pxr import UsdValidation

from bowerbot import constants
from bowerbot import schemas
from bowerbot import utils
from bowerbot.utils import usd

logger = logging.getLogger(__name__)


def validate_for_ar_quick_look(
    stage_path: str | Path,
) -> schemas.ValidationResult:
    """Check the stage against Apple consumer USDZ constraints.

    Targets the strict subset that renders on every Apple platform —
    AR Quick Look on iOS (Files / Safari / iMessage), macOS Quick Look,
    iPadOS, and visionOS RealityKit. visionOS and iOS 18+ are permissive
    supersets but the strict rules below render everywhere.
    """
    stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        return schemas.ValidationResult(
            is_valid=False,
            issues=[schemas.ValidationIssue(
                severity=schemas.Severity.ERROR,
                message=f"Failed to open stage: {stage_path}",
            )],
        )

    issues: list[schemas.ValidationIssue] = []
    issues.extend(_check_ar_quick_look_textures(stage))
    issues.extend(_check_ar_quick_look_materials(stage))
    issues.extend(_check_ar_quick_look_subdivision(stage))

    is_valid = not any(i.severity == schemas.Severity.ERROR for i in issues)
    return schemas.ValidationResult(is_valid=is_valid, issues=issues)


def _check_ar_quick_look_textures(stage: Usd.Stage) -> list[schemas.ValidationIssue]:
    """Texture asset paths must be PNG/JPEG; UDIM is not supported."""
    issues: list[schemas.ValidationIssue] = []
    for prim in stage.Traverse():
        shader = UsdShade.Shader(prim)
        if not shader:
            continue
        for input_ in shader.GetInputs():
            value = input_.Get()
            if not isinstance(value, Sdf.AssetPath):
                continue
            asset_path = value.path or ""
            if "<UDIM>" in asset_path or "<udim>" in asset_path:
                issues.append(schemas.ValidationIssue(
                    severity=schemas.Severity.ERROR,
                    message=(
                        f"AR Quick Look does not support UDIM textures: "
                        f"{asset_path}"
                    ),
                    prim_path=str(prim.GetPath()),
                ))
                continue
            ext = Path(asset_path).suffix.lower()
            if ext and ext not in constants.AppleUSDZConstraints.TEXTURE_EXTENSIONS:
                issues.append(schemas.ValidationIssue(
                    severity=schemas.Severity.ERROR,
                    message=(
                        f"Texture '{asset_path}' uses '{ext}' which Apple "
                        f"consumer USDZ does not support; convert to PNG "
                        f"or JPEG before packaging."
                    ),
                    prim_path=str(prim.GetPath()),
                ))
    return issues


def _check_ar_quick_look_materials(stage: Usd.Stage) -> list[schemas.ValidationIssue]:
    """UsdPreviewSurface output is the safe baseline across iOS versions."""
    issues: list[schemas.ValidationIssue] = []
    for prim in stage.Traverse():
        material = UsdShade.Material(prim)
        if not material:
            continue
        preview_out = material.GetSurfaceOutput()
        if preview_out and preview_out.HasConnectedSource():
            continue
        mtlx_out = material.GetSurfaceOutput("mtlx")
        if mtlx_out and mtlx_out.HasConnectedSource():
            issues.append(schemas.ValidationIssue(
                severity=schemas.Severity.WARNING,
                message=(
                    f"Material '{prim.GetName()}' has only a MaterialX "
                    f"surface output. RealityKit 4 (iOS 18+, visionOS, "
                    f"macOS 15+) reads MaterialX, but legacy AR Quick "
                    f"Look (iOS 17 and earlier) needs UsdPreviewSurface. "
                    f"For broadest consumer compatibility, add a "
                    f"UsdPreviewSurface output."
                ),
                prim_path=str(prim.GetPath()),
            ))
    return issues


def _check_ar_quick_look_subdivision(stage: Usd.Stage) -> list[schemas.ValidationIssue]:
    """Subdivision works on iOS 18+ but not on iOS 17- AR Quick Look."""
    issues: list[schemas.ValidationIssue] = []
    for prim in stage.Traverse():
        mesh = UsdGeom.Mesh(prim)
        if not mesh:
            continue
        scheme = mesh.GetSubdivisionSchemeAttr().Get()
        if scheme and scheme != UsdGeom.Tokens.none:
            issues.append(schemas.ValidationIssue(
                severity=schemas.Severity.WARNING,
                message=(
                    f"Mesh '{prim.GetName()}' has subdivisionScheme="
                    f"'{scheme}'. RealityKit 4 (iOS 18+, visionOS) reads "
                    f"this; iOS 17 and earlier AR Quick Look expects "
                    f"'none' (pre-tessellated)."
                ),
                prim_path=str(prim.GetPath()),
            ))
    return issues


def package_to_usdz(stage_path: str | Path, output_path: str | Path) -> Path:
    """Bundle a stage and its dependencies into a ``.usdz``."""
    stage_path = Path(stage_path)
    output_path = Path(output_path).with_suffix(".usdz")

    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)

    try:
        success = UsdUtils.CreateNewUsdzPackage(
            str(stage_path.resolve()),
            str(output_path.resolve()),
        )
    finally:
        os.dup2(old_stderr, 2)
        os.close(devnull)
        os.close(old_stderr)

    if not success:
        msg = f"Failed to package {stage_path} into {output_path}"
        raise RuntimeError(msg)

    logger.info("Packaged %s -> %s", stage_path, output_path)
    return output_path


def validate_stage(
    stage_path: str | Path,
    *,
    expected_meters_per_unit: float = 1.0,
    expected_up_axis: str = "Y",
) -> schemas.ValidationResult:
    """Run defaultPrim, units, axis, refs, sublayers, and binding checks."""
    stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        return schemas.ValidationResult(
            is_valid=False,
            issues=[
                schemas.ValidationIssue(
                    severity=schemas.Severity.ERROR,
                    message=f"Failed to open stage: {stage_path}",
                ),
            ],
        )

    issues: list[schemas.ValidationIssue] = []
    issues.extend(_check_default_prim(stage))
    issues.extend(_check_meters_per_unit(stage, expected_meters_per_unit))
    issues.extend(_check_up_axis(stage, expected_up_axis))
    issues.extend(_check_references(stage))
    issues.extend(_check_sublayers(stage))
    issues.extend(_check_material_bindings(stage))
    issues.extend(_check_scene_asset_variants(stage))
    issues.extend(_run_usd_compliance_checker(str(stage_path)))

    is_valid = not any(i.severity == schemas.Severity.ERROR for i in issues)
    return schemas.ValidationResult(is_valid=is_valid, issues=issues)


def run_usd_compliance_checker(file_path: str | Path) -> list[schemas.ValidationIssue]:
    """Run USD's ComplianceChecker against *file_path* and surface issues."""
    return _run_usd_compliance_checker(str(file_path))


def _check_default_prim(stage: Usd.Stage) -> list[schemas.ValidationIssue]:
    """Every stage must have a ``defaultPrim``."""
    if not stage.GetDefaultPrim():
        return [schemas.ValidationIssue(
            severity=schemas.Severity.ERROR,
            message="Stage has no defaultPrim set.",
        )]
    return []


def _check_meters_per_unit(
    stage: Usd.Stage, expected: float,
) -> list[schemas.ValidationIssue]:
    """``metersPerUnit`` must match the expected value."""
    actual = UsdGeom.GetStageMetersPerUnit(stage)
    if abs(actual - expected) > 1e-6:
        return [schemas.ValidationIssue(
            severity=schemas.Severity.ERROR,
            message=f"metersPerUnit is {actual}, expected {expected}",
        )]
    return []


def _check_up_axis(
    stage: Usd.Stage, expected: str,
) -> list[schemas.ValidationIssue]:
    """``upAxis`` must match the expected value."""
    actual = UsdGeom.GetStageUpAxis(stage)
    expected_token = (
        UsdGeom.Tokens.y if expected == "Y" else UsdGeom.Tokens.z
    )
    if actual != expected_token:
        return [schemas.ValidationIssue(
            severity=schemas.Severity.WARNING,
            message=f"upAxis is '{actual}', expected '{expected}'",
        )]
    return []


def _check_references(stage: Usd.Stage) -> list[schemas.ValidationIssue]:
    """All external references must resolve to existing files."""
    issues: list[schemas.ValidationIssue] = []
    stage_dir = Path(stage.GetRootLayer().realPath).parent

    for prim in stage.Traverse():
        for asset_path in utils.stage.get_prim_ref_paths(prim):
            if Path(asset_path).exists():
                continue
            if (stage_dir / asset_path).exists():
                continue
            issues.append(schemas.ValidationIssue(
                severity=schemas.Severity.ERROR,
                message=f"Unresolved reference: {asset_path}",
                prim_path=str(prim.GetPath()),
            ))
    return issues


def _check_sublayers(stage: Usd.Stage) -> list[schemas.ValidationIssue]:
    """All sublayers must resolve to existing files."""
    issues: list[schemas.ValidationIssue] = []
    root_layer = stage.GetRootLayer()
    stage_dir = Path(root_layer.realPath).parent

    for sub_path in root_layer.subLayerPaths:
        if not (stage_dir / sub_path).exists():
            issues.append(schemas.ValidationIssue(
                severity=schemas.Severity.ERROR,
                message=f"Unresolved sublayer: {sub_path}",
            ))
    return issues


def validate_asset_variants(asset_dir: Path) -> list[schemas.ValidationIssue]:
    """Structural checks for variant authoring on a single asset folder."""
    from bowerbot import utils

    issues: list[schemas.ValidationIssue] = []
    root_file = utils.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        return issues

    variants_path = asset_dir / constants.ASWFLayerNames.VARIANTS
    root_layer = Sdf.Layer.FindOrOpen(str(root_file))
    if root_layer is None:
        return issues

    sublayers = list(root_layer.subLayerPaths)
    sublayered = any(s == f"./{constants.ASWFLayerNames.VARIANTS}" for s in sublayers)
    if sublayered:
        issues.append(schemas.ValidationIssue(
            severity=schemas.Severity.ERROR,
            message=(
                f"variants.usda must be referenced, not sublayered, in "
                f"{asset_dir.name} (LIVRPS strength order)."
            ),
        ))

    default_prim_name = utils.asset_folder.resolve_default_prim_name(asset_dir)
    root_prim_spec = root_layer.GetPrimAtPath(f"/{default_prim_name}")
    has_ref = False
    if root_prim_spec is not None:
        ref_list = root_prim_spec.referenceList
        for items in (
            ref_list.prependedItems,
            ref_list.appendedItems,
            ref_list.addedItems,
            ref_list.explicitItems,
            ref_list.orderedItems,
        ):
            if any(r.assetPath == f"./{constants.ASWFLayerNames.VARIANTS}" for r in items):
                has_ref = True
                break

    if variants_path.exists() and not has_ref:
        issues.append(schemas.ValidationIssue(
            severity=schemas.Severity.ERROR,
            message=(
                f"variants.usda exists in {asset_dir.name} but is not "
                "referenced from the asset root."
            ),
        ))
    if has_ref and not variants_path.exists():
        issues.append(schemas.ValidationIssue(
            severity=schemas.Severity.ERROR,
            message=(
                f"Asset root references variants.usda but the file does "
                f"not exist in {asset_dir.name} (orphaned reference)."
            ),
        ))

    if not variants_path.exists():
        return issues

    summary = utils.variants.get_variant_summary(asset_dir)
    for vset in summary.variant_sets:
        if not usd.naming.is_valid_variant_set_name(vset.name):
            issues.append(schemas.ValidationIssue(
                severity=schemas.Severity.ERROR,
                message=(
                    f"Invalid variant set name {vset.name!r} in "
                    f"{asset_dir.name} (no whitespace or path separators)."
                ),
            ))
        for v in vset.variants:
            if not usd.naming.is_valid_variant_set_name(v):
                issues.append(schemas.ValidationIssue(
                    severity=schemas.Severity.ERROR,
                    message=(
                        f"Invalid variant name {v!r} in set {vset.name!r} "
                        f"in {asset_dir.name}."
                    ),
                ))
        if vset.selection is None:
            issues.append(schemas.ValidationIssue(
                severity=schemas.Severity.WARNING,
                message=(
                    f"Variant set {vset.name!r} on {asset_dir.name} has "
                    "no default selection; consumers will see whatever "
                    "the first authored variant is."
                ),
            ))
        elif vset.selection not in vset.variants:
            issues.append(schemas.ValidationIssue(
                severity=schemas.Severity.ERROR,
                message=(
                    f"Default variant {vset.selection!r} for set "
                    f"{vset.name!r} on {asset_dir.name} does not exist."
                ),
            ))
    return issues


def _check_scene_asset_variants(stage: Usd.Stage) -> list[schemas.ValidationIssue]:
    """Walk referenced asset folders and validate each one's variants."""
    seen: set[Path] = set()
    issues: list[schemas.ValidationIssue] = []
    stage_dir = Path(stage.GetRootLayer().realPath).parent

    for prim in stage.Traverse():
        for ref_path in utils.stage.get_prim_ref_paths(prim):
            resolved = (stage_dir / ref_path).resolve()
            if not resolved.exists():
                continue
            asset_dir = resolved.parent
            if asset_dir in seen:
                continue
            seen.add(asset_dir)
            issues.extend(validate_asset_variants(asset_dir))
    return issues


@functools.cache
def _validation_context() -> UsdValidation.ValidationContext:
    """Build a ValidationContext with all registered validators, once.

    A failed build raises and is not cached, so the next call tries again.
    """
    registry = UsdValidation.ValidationRegistry()
    validators = registry.GetOrLoadAllValidators()
    return UsdValidation.ValidationContext(validators)


def _get_validation_context() -> UsdValidation.ValidationContext | None:
    """The shared ValidationContext, or ``None`` when it cannot be built."""
    try:
        return _validation_context()
    except Exception as exc:
        logger.warning("Failed to build USD validation context: %s", exc)
        return None


def _run_usd_compliance_checker(file_path: str) -> list[schemas.ValidationIssue]:
    """Run USD's modern ValidationFramework against *file_path*."""
    ctx = _get_validation_context()
    if ctx is None:
        return []

    stage = Usd.Stage.Open(file_path)
    if stage is None:
        return []

    try:
        errors = ctx.Validate(stage)
    except Exception as exc:
        logger.warning("USD validation failed on %s: %s", file_path, exc)
        return []

    issues: list[schemas.ValidationIssue] = []
    for err in errors:
        severity = (
            schemas.Severity.ERROR
            if err.GetType() == UsdValidation.ValidationErrorType.Error
            else schemas.Severity.WARNING
        )
        sites = err.GetSites()
        prim_path = (
            str(sites[0].GetPrim().GetPath())
            if sites and sites[0].GetPrim() else None
        )
        issues.append(schemas.ValidationIssue(
            severity=severity,
            message=f"{err.GetName()}: {err.GetMessage()}",
            prim_path=prim_path,
        ))
    return issues


def _check_material_bindings(stage: Usd.Stage) -> list[schemas.ValidationIssue]:
    """Material bindings must resolve to valid Material prims."""
    issues: list[schemas.ValidationIssue] = []
    for prim in stage.Traverse():
        binding_rel = prim.GetRelationship("material:binding")
        if not binding_rel or not binding_rel.HasAuthoredTargets():
            continue

        bound_mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        if bound_mat:
            continue

        for target in binding_rel.GetTargets():
            issues.append(schemas.ValidationIssue(
                severity=schemas.Severity.ERROR,
                message=f"Unresolved material binding: {target}",
                prim_path=str(prim.GetPath()),
            ))
    return issues
