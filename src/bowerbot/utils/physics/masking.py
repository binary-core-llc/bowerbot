# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The refuse-or-acknowledge policy for scene opinions that would mask a ``phy.usda`` write."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pxr import Usd

from bowerbot import schemas
from bowerbot.utils import authoring


def enforce(
    stage: Usd.Stage,
    asset_dir: Path,
    asset_local_path: str,
    api_name: schemas.PhysicsApiName,
    attributes: dict[str, Any] | None,
    relationships: dict[str, list[str]] | None,
    *,
    clear: bool,
    confirm: bool,
) -> list[tuple[str, str, str]]:
    """Detect / clear / refuse scene.usda opinions that would mask a phy.usda write.

    Returns the list of opinions that were cleared (empty when none or when
    *confirm* was used). Raises ``ValueError`` with a per-opinion breakdown
    when masking exists and neither *clear* nor *confirm* is set.
    """
    masking = authoring.opinions.find_physics_masking_opinions(
        stage, asset_dir, asset_local_path,
        attributes=attributes, relationships=relationships,
    )
    if not masking:
        return []
    if clear:
        authoring.opinions.clear_physics_masking_opinions(stage, masking)
        return masking
    if confirm:
        return []
    raise ValueError(format_error(api_name, masking))


def format_error(
    api_name: schemas.PhysicsApiName, masking: list[tuple[str, str, str]],
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
