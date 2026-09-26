# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset variant checks — how an asset folder authors and references its variants."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf

from bowerbot.schemas import ASWFLayerNames, Severity, ValidationIssue
from bowerbot.utils.core.asset_folder import find_root_file, resolve_default_prim_name
from bowerbot.utils.core.naming import is_valid_variant_name
from bowerbot.utils.variants.inspection import get_variant_summary


def validate_asset_variants(asset_dir: Path) -> list[ValidationIssue]:
    """Structural checks for variant authoring on a single asset folder."""
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

    summary = get_variant_summary(asset_dir)
    for vset in summary.variant_sets:
        if not is_valid_variant_name(vset.name):
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=(
                    f"Invalid variant set name {vset.name!r} in "
                    f"{asset_dir.name} (no whitespace or path separators)."
                ),
            ))
        for v in vset.variants:
            if not is_valid_variant_name(v):
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
