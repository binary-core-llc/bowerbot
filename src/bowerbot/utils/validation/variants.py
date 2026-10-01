# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Structural checks of an asset folder's variants."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import usd


def validate_asset(asset_dir: Path) -> list[schemas.ValidationIssue]:
    """Structural checks for variant authoring on a single asset folder."""

    issues: list[schemas.ValidationIssue] = []
    root_file = authoring.asset_folder.find_root_file(asset_dir)
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

    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    root_prim_spec = root_layer.GetPrimAtPath(f"/{default_prim_name}")
    has_ref = root_prim_spec is not None and (
        f"./{constants.ASWFLayerNames.VARIANTS}"
        in usd.references.reference_paths(root_prim_spec)
    )

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

    summary = authoring.asset_variants.get_variant_summary(asset_dir)
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
