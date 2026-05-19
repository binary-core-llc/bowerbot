# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage validation + USDZ packaging primitives."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdShade, UsdUtils, UsdValidation

from bowerbot.schemas import (
    AppleUSDZConstraints,
    Severity,
    ValidationIssue,
    ValidationResult,
)
from bowerbot.utils.stage_utils import get_prim_ref_paths

logger = logging.getLogger(__name__)


def validate_for_ar_quick_look(
    stage_path: str | Path,
) -> ValidationResult:
    """Check the stage against Apple consumer USDZ constraints.

    Targets the strict subset that renders on every Apple platform —
    AR Quick Look on iOS (Files / Safari / iMessage), macOS Quick Look,
    iPadOS, and visionOS RealityKit. visionOS and iOS 18+ are permissive
    supersets but the strict rules below render everywhere.
    """
    stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        return ValidationResult(
            is_valid=False,
            issues=[ValidationIssue(
                severity=Severity.ERROR,
                message=f"Failed to open stage: {stage_path}",
            )],
        )

    issues: list[ValidationIssue] = []
    issues.extend(_check_ar_quick_look_textures(stage))
    issues.extend(_check_ar_quick_look_materials(stage))
    issues.extend(_check_ar_quick_look_subdivision(stage))

    is_valid = not any(i.severity == Severity.ERROR for i in issues)
    return ValidationResult(is_valid=is_valid, issues=issues)


def _check_ar_quick_look_textures(stage: Usd.Stage) -> list[ValidationIssue]:
    """Texture asset paths must be PNG/JPEG; UDIM is not supported."""
    issues: list[ValidationIssue] = []
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
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=(
                        f"AR Quick Look does not support UDIM textures: "
                        f"{asset_path}"
                    ),
                    prim_path=str(prim.GetPath()),
                ))
                continue
            ext = Path(asset_path).suffix.lower()
            if ext and ext not in AppleUSDZConstraints.TEXTURE_EXTENSIONS:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=(
                        f"Texture '{asset_path}' uses '{ext}' which Apple "
                        f"consumer USDZ does not support; convert to PNG "
                        f"or JPEG before packaging."
                    ),
                    prim_path=str(prim.GetPath()),
                ))
    return issues


def _check_ar_quick_look_materials(stage: Usd.Stage) -> list[ValidationIssue]:
    """UsdPreviewSurface output is the safe baseline across iOS versions."""
    issues: list[ValidationIssue] = []
    for prim in stage.Traverse():
        material = UsdShade.Material(prim)
        if not material:
            continue
        preview_out = material.GetSurfaceOutput()
        if preview_out and preview_out.HasConnectedSource():
            continue
        mtlx_out = material.GetSurfaceOutput("mtlx")
        if mtlx_out and mtlx_out.HasConnectedSource():
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
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


def _check_ar_quick_look_subdivision(stage: Usd.Stage) -> list[ValidationIssue]:
    """Subdivision works on iOS 18+ but not on iOS 17- AR Quick Look."""
    issues: list[ValidationIssue] = []
    for prim in stage.Traverse():
        mesh = UsdGeom.Mesh(prim)
        if not mesh:
            continue
        scheme = mesh.GetSubdivisionSchemeAttr().Get()
        if scheme and scheme != UsdGeom.Tokens.none:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
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
) -> ValidationResult:
    """Run defaultPrim, units, axis, refs, sublayers, and binding checks."""
    stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        return ValidationResult(
            is_valid=False,
            issues=[
                ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Failed to open stage: {stage_path}",
                ),
            ],
        )

    issues: list[ValidationIssue] = []
    issues.extend(_check_default_prim(stage))
    issues.extend(_check_meters_per_unit(stage, expected_meters_per_unit))
    issues.extend(_check_up_axis(stage, expected_up_axis))
    issues.extend(_check_references(stage))
    issues.extend(_check_sublayers(stage))
    issues.extend(_check_material_bindings(stage))
    issues.extend(_check_scene_asset_variants(stage))
    issues.extend(_run_usd_compliance_checker(str(stage_path)))

    is_valid = not any(i.severity == Severity.ERROR for i in issues)
    return ValidationResult(is_valid=is_valid, issues=issues)


def run_usd_compliance_checker(file_path: str | Path) -> list[ValidationIssue]:
    """Run USD's ComplianceChecker against *file_path* and surface issues."""
    return _run_usd_compliance_checker(str(file_path))


def _check_default_prim(stage: Usd.Stage) -> list[ValidationIssue]:
    """Every stage must have a ``defaultPrim``."""
    if not stage.GetDefaultPrim():
        return [ValidationIssue(
            severity=Severity.ERROR,
            message="Stage has no defaultPrim set.",
        )]
    return []


def _check_meters_per_unit(
    stage: Usd.Stage, expected: float,
) -> list[ValidationIssue]:
    """``metersPerUnit`` must match the expected value."""
    actual = UsdGeom.GetStageMetersPerUnit(stage)
    if abs(actual - expected) > 1e-6:
        return [ValidationIssue(
            severity=Severity.ERROR,
            message=f"metersPerUnit is {actual}, expected {expected}",
        )]
    return []


def _check_up_axis(
    stage: Usd.Stage, expected: str,
) -> list[ValidationIssue]:
    """``upAxis`` must match the expected value."""
    actual = UsdGeom.GetStageUpAxis(stage)
    expected_token = (
        UsdGeom.Tokens.y if expected == "Y" else UsdGeom.Tokens.z
    )
    if actual != expected_token:
        return [ValidationIssue(
            severity=Severity.WARNING,
            message=f"upAxis is '{actual}', expected '{expected}'",
        )]
    return []


def _check_references(stage: Usd.Stage) -> list[ValidationIssue]:
    """All external references must resolve to existing files."""
    issues: list[ValidationIssue] = []
    stage_dir = Path(stage.GetRootLayer().realPath).parent

    for prim in stage.Traverse():
        for asset_path in get_prim_ref_paths(prim):
            if Path(asset_path).exists():
                continue
            if (stage_dir / asset_path).exists():
                continue
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Unresolved reference: {asset_path}",
                prim_path=str(prim.GetPath()),
            ))
    return issues


def _check_sublayers(stage: Usd.Stage) -> list[ValidationIssue]:
    """All sublayers must resolve to existing files."""
    issues: list[ValidationIssue] = []
    root_layer = stage.GetRootLayer()
    stage_dir = Path(root_layer.realPath).parent

    for sub_path in root_layer.subLayerPaths:
        if not (stage_dir / sub_path).exists():
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Unresolved sublayer: {sub_path}",
            ))
    return issues


def validate_asset_variants(asset_dir: Path) -> list[ValidationIssue]:
    """Structural checks for variant authoring on a single asset folder."""
    from bowerbot.schemas import ASWFLayerNames
    from bowerbot.utils import variant_utils
    from bowerbot.utils.asset_folder_utils import (
        find_root_file,
        resolve_default_prim_name,
    )

    issues: list[ValidationIssue] = []
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return issues

    variants_path = asset_dir / ASWFLayerNames.VARIANTS
    root_layer = Sdf.Layer.FindOrOpen(str(root_file))
    if root_layer is None:
        return issues

    sublayers = list(root_layer.subLayerPaths)
    sublayered = any(s == f"./{ASWFLayerNames.VARIANTS}" for s in sublayers)
    if sublayered:
        issues.append(ValidationIssue(
            severity=Severity.ERROR,
            message=(
                f"variants.usda must be referenced, not sublayered, in "
                f"{asset_dir.name} (LIVRPS strength order)."
            ),
        ))

    default_prim_name = resolve_default_prim_name(asset_dir)
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
            if any(r.assetPath == f"./{ASWFLayerNames.VARIANTS}" for r in items):
                has_ref = True
                break

    if variants_path.exists() and not has_ref:
        issues.append(ValidationIssue(
            severity=Severity.ERROR,
            message=(
                f"variants.usda exists in {asset_dir.name} but is not "
                "referenced from the asset root."
            ),
        ))
    if has_ref and not variants_path.exists():
        issues.append(ValidationIssue(
            severity=Severity.ERROR,
            message=(
                f"Asset root references variants.usda but the file does "
                f"not exist in {asset_dir.name} (orphaned reference)."
            ),
        ))

    if not variants_path.exists():
        return issues

    summary = variant_utils.get_variant_summary(asset_dir)
    for vset in summary.variant_sets:
        if not variant_utils.is_valid_variant_set_name(vset.name):
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=(
                    f"Invalid variant set name {vset.name!r} in "
                    f"{asset_dir.name} (no whitespace or path separators)."
                ),
            ))
        for v in vset.variants:
            if not variant_utils.is_valid_variant_set_name(v):
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=(
                        f"Invalid variant name {v!r} in set {vset.name!r} "
                        f"in {asset_dir.name}."
                    ),
                ))
        if vset.selection is None:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message=(
                    f"Variant set {vset.name!r} on {asset_dir.name} has "
                    "no default selection; consumers will see whatever "
                    "the first authored variant is."
                ),
            ))
        elif vset.selection not in vset.variants:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=(
                    f"Default variant {vset.selection!r} for set "
                    f"{vset.name!r} on {asset_dir.name} does not exist."
                ),
            ))
    return issues


def _check_scene_asset_variants(stage: Usd.Stage) -> list[ValidationIssue]:
    """Walk referenced asset folders and validate each one's variants."""
    seen: set[Path] = set()
    issues: list[ValidationIssue] = []
    stage_dir = Path(stage.GetRootLayer().realPath).parent

    for prim in stage.Traverse():
        for ref_path in get_prim_ref_paths(prim):
            resolved = (stage_dir / ref_path).resolve()
            if not resolved.exists():
                continue
            asset_dir = resolved.parent
            if asset_dir in seen:
                continue
            seen.add(asset_dir)
            issues.extend(validate_asset_variants(asset_dir))
    return issues


_VALIDATION_CONTEXT: UsdValidation.ValidationContext | None = None


def _get_validation_context() -> UsdValidation.ValidationContext | None:
    """Lazily build a singleton ValidationContext with all registered validators."""
    global _VALIDATION_CONTEXT
    if _VALIDATION_CONTEXT is not None:
        return _VALIDATION_CONTEXT
    try:
        registry = UsdValidation.ValidationRegistry()
        validators = registry.GetOrLoadAllValidators()
        _VALIDATION_CONTEXT = UsdValidation.ValidationContext(validators)
    except Exception as exc:
        logger.warning("Failed to build USD validation context: %s", exc)
        return None
    return _VALIDATION_CONTEXT


def _run_usd_compliance_checker(file_path: str) -> list[ValidationIssue]:
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

    issues: list[ValidationIssue] = []
    for err in errors:
        severity = (
            Severity.ERROR
            if err.GetType() == UsdValidation.ValidationErrorType.Error
            else Severity.WARNING
        )
        sites = err.GetSites()
        prim_path = (
            str(sites[0].GetPrim().GetPath())
            if sites and sites[0].GetPrim() else None
        )
        issues.append(ValidationIssue(
            severity=severity,
            message=f"{err.GetName()}: {err.GetMessage()}",
            prim_path=prim_path,
        ))
    return issues


def _check_material_bindings(stage: Usd.Stage) -> list[ValidationIssue]:
    """Material bindings must resolve to valid Material prims."""
    issues: list[ValidationIssue] = []
    for prim in stage.Traverse():
        binding_rel = prim.GetRelationship("material:binding")
        if not binding_rel or not binding_rel.HasAuthoredTargets():
            continue

        bound_mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        if bound_mat:
            continue

        for target in binding_rel.GetTargets():
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Unresolved material binding: {target}",
                prim_path=str(prim.GetPath()),
            ))
    return issues
