# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant masking — refusing, confirming or clearing scene overrides of a variant."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pxr import Usd

from bowerbot.schemas.overrides import MaskingOpinion, OpinionKind
from bowerbot.utils.core.overrides import (
    find_masking_opinions,
    placement_paths,
    settle_masking,
)


def enforce_no_masking_overrides(
    stage: Usd.Stage,
    asset_dir: Path,
    target_map: dict[str, Iterable[str]],
    kind: OpinionKind,
    variant_kind: str,
    *,
    clear: bool,
    confirm: bool,
) -> bool:
    """Detect/clear/refuse masking scene opinions; return True if stage needs reload."""
    masking = find_masking_opinions(stage, [
        (scene_path, kind, target_map[asset_path])
        for asset_path, scene_path in placement_paths(stage, asset_dir, target_map)
    ])
    return settle_masking(
        stage, masking, clear=clear, confirm=confirm,
        refusal=variant_masking_error(variant_kind, masking),
    )


def enforce_no_scene_masking_overrides(
    stage: Usd.Stage,
    target_map: dict[str, Iterable[str]],
    kind: OpinionKind,
    variant_kind: str,
    *,
    clear: bool,
    confirm: bool,
) -> bool:
    """Refuse / clear direct scene opinions that mask a scene-level variant body."""
    masking = find_masking_opinions(
        stage, [(scene_path, kind, keys) for scene_path, keys in target_map.items()],
    )
    return settle_masking(
        stage, masking, clear=clear, confirm=confirm,
        refusal=variant_masking_error(variant_kind, masking),
    )


def variant_masking_error(
    variant_kind: str, masking: list[MaskingOpinion],
) -> str:
    """Render a masking-override conflict into a user-facing error message."""
    lines = [
        f"Cannot author this {variant_kind} variant: {len(masking)} "
        "per-instance scene opinion(s) would mask it. Per LIVRPS the "
        "variant body would be silently overridden at composition time. "
        "Conflicting (placement, opinion):",
    ]
    for prim_path, _kind, key in masking:
        lines.append(f"  {prim_path}.{key}")
    lines.append(
        "Retry with clear_masking_overrides=true to remove these scene "
        "opinions, OR with confirm_masked=true to author anyway (variant "
        "will only take effect on placements without prior overrides).",
    )
    return "\n".join(lines)
