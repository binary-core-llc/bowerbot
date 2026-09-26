# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics masking — refusing, confirming or clearing scene overrides of phy.usda."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pxr import Usd

from bowerbot.schemas import (
    PhysicsApiName,
)
from bowerbot.schemas.overrides import MaskingOpinion, OpinionKind
from bowerbot.utils.core.overrides import (
    find_masking_opinions,
    placement_paths,
    settle_masking,
)

logger = logging.getLogger(__name__)


def enforce_masking_policy(
    stage: Usd.Stage,
    asset_dir: Path,
    asset_local_path: str,
    api_name: PhysicsApiName,
    attributes: dict[str, Any] | None,
    relationships: dict[str, list[str]] | None,
    *,
    clear: bool,
    confirm: bool,
) -> list[MaskingOpinion]:
    """Detect / clear / refuse scene.usda opinions that would mask a phy.usda write.

    Returns the list of opinions that were cleared (empty when none or when
    *confirm* was used). Raises ``ValueError`` with a per-opinion breakdown
    when masking exists and neither *clear* nor *confirm* is set.
    """
    attr_names = set((attributes or {}).keys())
    rel_names = set((relationships or {}).keys())
    if not attr_names and not rel_names:
        return []
    targets: list[tuple[str, OpinionKind, Iterable[str]]] = []
    for _, path in placement_paths(stage, asset_dir, [asset_local_path]):
        targets.append((path, "attribute", attr_names))
        targets.append((path, "relationship", rel_names))
    masking = find_masking_opinions(stage, targets)
    cleared = settle_masking(
        stage, masking, clear=clear, confirm=confirm,
        refusal=physics_masking_error(api_name, masking),
    )
    return masking if cleared else []


def physics_masking_error(
    api_name: PhysicsApiName, masking: list[MaskingOpinion],
) -> str:
    """Render a refuse-or-acknowledge error listing every masking opinion."""
    lines = [
        f"Cannot author {api_name.value} on phy.usda: "
        f"{len(masking)} scene.usda opinion(s) would mask it. Per LIVRPS, "
        "the asset opinions would be silently overridden at composition "
        "time. Conflicts:",
    ]
    for prim_path, kind, key in masking:
        lines.append(f"  {prim_path}.{key} ({kind})")
    lines.append(
        "Retry with clear_masking_overrides=true to remove these scene "
        "opinions and write to phy.usda, OR confirm_masked=true to write "
        "anyway (scene overrides will keep winning on those placements).",
    )
    return "\n".join(lines)
