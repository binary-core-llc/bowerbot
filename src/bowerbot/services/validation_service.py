# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Validation service — check a USD stage before packaging."""

from __future__ import annotations

from pathlib import Path

from pxr import Usd, UsdGeom, UsdShade

from bowerbot.schemas import Severity, ValidationIssue, ValidationResult
from bowerbot.utils.usd_utils import get_prim_ref_paths


def validate(
    stage_path: str | Path,
    *,
    expected_meters_per_unit: float = 1.0,
    expected_up_axis: str = "Y",
) -> ValidationResult:
    """Run all validation checks on the stage at *stage_path*."""
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

    is_valid = not any(i.severity == Severity.ERROR for i in issues)
    return ValidationResult(is_valid=is_valid, issues=issues)


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
