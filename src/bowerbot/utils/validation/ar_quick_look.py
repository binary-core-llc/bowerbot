# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Apple AR Quick Look checks — textures, materials and subdivision for consumer USDZ."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdShade

from bowerbot.schemas import AppleUSDZConstraints, Severity, ValidationIssue, ValidationResult


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
