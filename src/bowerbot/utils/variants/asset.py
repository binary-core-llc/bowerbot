# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Adding a variant to an asset's variants.usda, and checking its attribute overrides."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pxr import Sdf
from pxr import Usd

from bowerbot import constants
from bowerbot.utils import authoring
from bowerbot.utils import usd


def add(
    asset_dir: Path,
    variant_set: str,
    variant_name: str,
    author_fn: Callable[[Usd.Stage, str], None],
    set_as_default: bool = False,
) -> None:
    """End-to-end variant authoring: layer, reference, opinions, default selection."""
    authoring.asset_folder.ensure_over_layer(asset_dir, constants.ASWFLayerNames.VARIANTS)
    authoring.asset_folder.ensure_root_reference(asset_dir, constants.ASWFLayerNames.VARIANTS)
    stage = authoring.asset_variants.open_variants_stage(asset_dir)
    usd.variant_sets.author_in_variant(
        stage, f"/{authoring.asset_folder.resolve_default_prim_name(asset_dir)}",
        variant_set, variant_name, author_fn,
    )

    summary = authoring.asset_variants.get_variant_summary(asset_dir)
    existing = next(
        (s for s in summary.variant_sets if s.name == variant_set), None,
    )
    needs_default = set_as_default or (existing is not None and not existing.selection)
    if needs_default:
        authoring.asset_variants.set_default_variant(asset_dir, variant_set, variant_name)


def resolve_attribute_types_for_overrides(
    asset_dir: Path,
    overrides: dict[str, dict[str, object]],
) -> dict[str, dict[str, Sdf.ValueTypeName | None]]:
    """Look up each override attribute's declared type from the asset's composed stage."""
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    stage = Usd.Stage.Open(str(root_file)) if root_file is not None else None
    return usd.attributes.resolve_attribute_types(stage, overrides)


def refuse_unknown_attributes(
    asset_dir: Path,
    resolved_types: dict[str, dict[str, Sdf.ValueTypeName | None]],
) -> None:
    """Refuse override attributes that do not exist on the asset's composed prims."""
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    stage = Usd.Stage.Open(str(root_file)) if root_file is not None else None
    usd.attributes.refuse_unknown_attributes(stage, resolved_types)
