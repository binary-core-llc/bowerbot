# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Packaging a stage into a ``.usdz``, and the AR Quick Look checks."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade
from pxr import UsdUtils

from bowerbot import constants
from bowerbot import schemas

logger = logging.getLogger(__name__)


def package(stage_path: str | Path, output_path: str | Path) -> Path:
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


# ── Helpers ──


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
