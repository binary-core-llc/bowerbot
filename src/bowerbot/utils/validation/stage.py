# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""validate_scene's checks on a stage: defaultPrim, units, axis, references, bindings."""

from __future__ import annotations

from pathlib import Path

from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade

from bowerbot import constants
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
    issues.extend(
        _known_shader_note(issue)
        for issue in usd.compliance.run_usd_compliance_checker(stage_path)
    )

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
    if actual != usd.metrics.up_axis_token(expected):
        return [schemas.ValidationIssue(
            severity=schemas.Severity.WARNING,
            message=f"upAxis is '{actual}', expected '{expected}'",
        )]
    return []


def _check_references(stage: Usd.Stage) -> list[schemas.ValidationIssue]:
    """Every reference and payload must point to a file that exists."""
    return [
        schemas.ValidationIssue(
            severity=schemas.Severity.ERROR,
            message=f"Unresolved reference: {asset_path}",
            prim_path=prim_path,
        )
        for prim_path, asset_path, target in _referenced_files(stage)
        if not target.exists()
    ]


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
    for _prim_path, _asset_path, target in _referenced_files(stage):
        if not target.exists() or target.parent in seen:
            continue
        seen.add(target.parent)
        issues.extend(validation.variants.validate_asset(target.parent))
    return issues


def _referenced_files(stage: Usd.Stage) -> list[tuple[str, str, Path]]:
    """``(prim path, path as written, file it points to)`` for every reference and payload.

    Each path is read from the layer that wrote it, so a link an asset makes
    to a sibling asset (``../crate/crate.usda``) is followed from that asset.
    """
    found: dict[tuple[str, str], Path] = {}
    for prim in stage.Traverse():
        for spec in prim.GetPrimStack():
            base = Path(spec.layer.realPath).parent
            for asset_path in (
                *usd.references.reference_paths(spec), *usd.references.payload_paths(spec),
            ):
                found.setdefault((str(prim.GetPath()), asset_path), (base / asset_path).resolve())
    return [(prim_path, asset_path, target) for (prim_path, asset_path), target in found.items()]


def _known_shader_note(issue: schemas.ValidationIssue) -> schemas.ValidationIssue:
    """A shader BowerBot authors that this USD build cannot look up is a note, not an error.

    USD reports the MaterialX shader of a procedural material as missing when
    it was built without MaterialX; the scene is right, and a renderer with
    MaterialX reads it. Any other unknown shader stays an error.
    """
    if not issue.message.startswith("MissingShaderIdInRegistry"):
        return issue
    if not any(f"'{shader}'" in issue.message for shader in constants.MaterialXShaders.ALL):
        return issue
    return schemas.ValidationIssue(
        severity=schemas.Severity.WARNING,
        message=(
            "This USD build has no MaterialX support, so it cannot check the shader of a "
            f"procedural material; a renderer with MaterialX reads it. ({issue.message})"
        ),
        prim_path=issue.prim_path,
    )
