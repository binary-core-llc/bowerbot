# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset intake — bringing a file or folder into the project as an ASWF asset."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from bowerbot.schemas import (
    AssetFormat,
    ASWFLayerNames,
    IntakeReport,
)
from bowerbot.utils.assets.aswf import create_asset_folder, ensure_aswf_compliance
from bowerbot.utils.assets.folders import intake_folder
from bowerbot.utils.library_utils import find_package_for
from bowerbot.utils.validation_utils import run_usd_compliance_checker

logger = logging.getLogger(__name__)


def prepare_asset(
    asset_path: Path,
    assets_dir: Path,
    *,
    library_dir: Path | None,
    fix_root_prim: bool = False,
    fix_root_transforms: bool = False,
) -> IntakeReport:
    """Route an input file to USDZ / library-package / loose-file intake."""
    if asset_path.suffix.lower() == AssetFormat.USDZ:
        return intake_usdz(asset_path, assets_dir)

    if library_dir is not None:
        package_dir = find_package_for(asset_path, library_dir)
        if package_dir is not None:
            report = intake_folder(package_dir, assets_dir)
            _validate_intake(
                report, assets_dir,
                fix_root_prim=fix_root_prim,
                fix_root_transforms=fix_root_transforms,
            )
            return report

    folder_name = asset_path.stem
    root_file = create_asset_folder(
        output_dir=assets_dir,
        asset_name=folder_name,
        geometry_file=asset_path,
    )
    report = IntakeReport(
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
    if asset_path.suffix.lower() == AssetFormat.USDZ:
        return asset_path.name
    if library_dir is not None:
        package_dir = find_package_for(asset_path, library_dir)
        if package_dir is not None:
            return package_dir.name
    return asset_path.stem


def _validate_intake(
    report: IntakeReport,
    assets_dir: Path,
    *,
    fix_root_prim: bool,
    fix_root_transforms: bool,
) -> None:
    """Validate the intaken asset's geo.usda; rollback target on failure."""
    target_folder = assets_dir / report.asset_folder_name
    geo_path = target_folder / ASWFLayerNames.GEO
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
        compliance_issues = run_usd_compliance_checker(canonical_root)
        for issue in compliance_issues:
            report.warnings.append(issue.message)
            logger.info(
                "ComplianceChecker on %s: %s",
                report.asset_folder_name, issue.message,
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


def intake_summary(report: IntakeReport) -> dict:
    """Condense an intake report into the fields surfaced to the LLM."""
    return {
        "asset_folder": report.asset_folder_name,
        "root_canonical_name": report.root_canonical_name,
        "was_renamed": report.was_renamed,
        "root_original_name": (
            report.root_original_name if report.was_renamed else None
        ),
        "files_copied": report.files_copied,
        "localized_layers": report.localized_layers,
        "localized_assets": report.localized_assets,
        "warnings": report.warnings,
    }


def placement_message(
    asset_name: str, prim_path: str, report: IntakeReport,
) -> str:
    """Format a placement message that narrates intake normalization."""
    parts = [f"Placed {asset_name} at {prim_path}."]
    if report.was_renamed:
        parts.append(
            f"Normalized on intake: {report.root_original_name} -> "
            f"{report.root_canonical_name} (ASWF convention).",
        )
    localized = len(report.localized_layers) + len(report.localized_assets)
    if localized:
        parts.append(
            f"Localized {localized} external dependency/ies into the asset folder.",
        )
    return " ".join(parts)
