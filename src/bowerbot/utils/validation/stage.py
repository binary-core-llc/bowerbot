# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage checks — defaultPrim, units, axis, references, sublayers, bindings and asset variants."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pxr import Usd, UsdGeom, UsdShade

from bowerbot.schemas import Severity, ValidationIssue, ValidationResult
from bowerbot.utils.core.references import referenced_asset_dir
from bowerbot.utils.validation.asset_variants import validate_asset_variants
from bowerbot.utils.validation.compliance import run_usd_compliance_checker


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
    issues.extend(run_usd_compliance_checker(stage_path))

    is_valid = not any(i.severity == Severity.ERROR for i in issues)
    return ValidationResult(is_valid=is_valid, issues=issues)


def stage_report(
    stage_path: str | Path, *, expected_meters_per_unit: float, expected_up_axis: str,
) -> dict[str, Any]:
    """:func:`validate_stage` as the JSON a tool returns: validity, error count, issues."""
    result = validate_stage(
        stage_path,
        expected_meters_per_unit=expected_meters_per_unit,
        expected_up_axis=expected_up_axis,
    )
    return {
        "is_valid": result.is_valid,
        "error_count": result.error_count,
        "issues": [
            {"severity": i.severity.value, "message": i.message, "prim": i.prim_path}
            for i in result.issues
        ],
        "message": (
            "Scene is valid!" if result.is_valid else f"Found {result.error_count} error(s)."
        ),
    }


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
    """All external references must resolve to existing files.

    Each path resolves from the layer that authors it (a nested asset's
    ``../crate/crate.usda`` lives in its container's ``contents.usda``).
    """
    issues: list[ValidationIssue] = []
    for prim in stage.Traverse():
        unresolved: list[str] = []
        for spec in prim.GetPrimStack():
            refs = spec.referenceList
            for ref in (*refs.prependedItems, *refs.appendedItems, *refs.explicitItems):
                resolved = spec.layer.ComputeAbsolutePath(ref.assetPath) if ref.assetPath else ""
                if resolved and not Path(resolved).exists():
                    unresolved.append(ref.assetPath)
        issues.extend(
            ValidationIssue(
                severity=Severity.ERROR,
                message=f"Unresolved reference: {asset_path}",
                prim_path=str(prim.GetPath()),
            )
            for asset_path in dict.fromkeys(unresolved)
        )
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


def _check_scene_asset_variants(stage: Usd.Stage) -> list[ValidationIssue]:
    """Walk referenced asset folders and validate each one's variants."""
    seen: set[Path] = set()
    issues: list[ValidationIssue] = []
    for prim in stage.Traverse():
        asset_dir = referenced_asset_dir(prim)
        if asset_dir is None or asset_dir in seen:
            continue
        seen.add(asset_dir)
        issues.extend(validate_asset_variants(asset_dir))
    return issues
