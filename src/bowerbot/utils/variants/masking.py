# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The refuse-or-acknowledge policy for scene opinions that would mask a variant."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pxr import Usd

from bowerbot import schemas
from bowerbot.utils import authoring


def enforce_in_asset(
    stage: Usd.Stage,
    asset_dir: Path,
    default_prim: str,
    target_map: dict[str, Iterable[str]],
    kind: schemas.OpinionKind,
    variant_kind: str,
    *,
    clear: bool,
    confirm: bool,
) -> bool:
    """Detect/clear/refuse masking scene opinions; return True if stage needs reload."""
    masking = authoring.opinions.find_variant_masking_opinions(
        stage, asset_dir, default_prim, target_map, kind,
    )
    if not masking:
        return False
    if clear:
        authoring.opinions.clear_variant_masking_opinions(stage, masking, kind)
        return True
    if not confirm:
        raise ValueError(format_error(variant_kind, masking))
    return False


def enforce_in_scene(
    stage: Usd.Stage,
    target_map: dict[str, Iterable[str]],
    kind: schemas.OpinionKind,
    variant_kind: str,
    *,
    clear: bool,
    confirm: bool,
) -> bool:
    """Refuse / clear direct scene opinions that mask a scene-level variant body."""
    masking = authoring.opinions.find_masking_scene_opinions_direct(stage, target_map, kind)
    if not masking:
        return False
    if clear:
        authoring.opinions.clear_variant_masking_opinions(stage, masking, kind)
        return True
    if not confirm:
        raise ValueError(format_error(variant_kind, masking))
    return False


def format_error(
    variant_kind: str, masking: list[tuple[str, str]],
) -> str:
    """Render a masking-override conflict into a user-facing error message."""
    lines = [
        f"Cannot author this {variant_kind} variant: {len(masking)} "
        "per-instance scene opinion(s) would mask it. Per LIVRPS the "
        "variant body would be silently overridden at composition time. "
        "Conflicting (placement, opinion):",
    ]
    for prim_path, key in masking:
        lines.append(f"  {prim_path}.{key}")
    lines.append(
        "Retry with clear_masking_overrides=true to remove these scene "
        "opinions, OR with confirm_masked=true to author anyway (variant "
        "will only take effect on placements without prior overrides).",
    )
    return "\n".join(lines)
