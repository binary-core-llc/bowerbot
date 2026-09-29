# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""validate_scene's checks on a stage: defaultPrim, units, axis, references, bindings."""

from __future__ import annotations

from pathlib import Path

from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade

from bowerbot import schemas
from bowerbot.utils import usd
from bowerbot.utils import validation


def validate(
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
    issues.extend(usd.compliance.run_usd_compliance_checker(stage_path))

    is_valid = not any(i.severity == schemas.Severity.ERROR for i in issues)
    return schemas.ValidationResult(is_valid=is_valid, issues=issues)


# ── Helpers ──


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
        for asset_path in usd.references.get_prim_ref_paths(prim):
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


def _check_scene_asset_variants(stage: Usd.Stage) -> list[schemas.ValidationIssue]:
    """Walk referenced asset folders and validate each one's variants."""
    seen: set[Path] = set()
    issues: list[schemas.ValidationIssue] = []
    stage_dir = Path(stage.GetRootLayer().realPath).parent

    for prim in stage.Traverse():
        for ref_path in usd.references.get_prim_ref_paths(prim):
            resolved = (stage_dir / ref_path).resolve()
            if not resolved.exists():
                continue
            asset_dir = resolved.parent
            if asset_dir in seen:
                continue
            seen.add(asset_dir)
            issues.extend(validation.variants.validate_asset(asset_dir))
    return issues
