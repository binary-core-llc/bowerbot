# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Where a physics write goes: into the asset (``phy.usda``) or into the scene."""

from __future__ import annotations

from pathlib import Path

from pxr import Usd

from bowerbot.utils import authoring


def validate(scope: str) -> str:
    """Refuse any value other than ``'asset'`` or ``'scene'``."""
    if scope not in ("asset", "scene"):
        raise ValueError(
            f"Invalid scope {scope!r}; must be 'asset' or 'scene'.",
        )
    return scope


def autodetect(stage: Usd.Stage, prim_path: str) -> str:
    """Return ``'asset'`` if *prim_path* resolves through an ASWF placement; else ``'scene'``."""
    try:
        authoring.placement.require_asset_context(stage, prim_path)
    except ValueError:
        return "scene"
    return "asset"


def resolve(stage: Usd.Stage, prim_path: str, explicit: str | None) -> str:
    """The scope a write goes to: *explicit* when given, else detected from *prim_path*."""
    return validate(explicit) if explicit else autodetect(stage, prim_path)


def require_asset_target(
    stage: Usd.Stage, prim_path: str, *, scene_retry: str,
) -> tuple[Path, str]:
    """The asset folder behind *prim_path* and the prim's path inside that asset.

    A prim authored in the scene is refused; *scene_retry* says what retrying
    with ``scope='scene'`` would do (e.g. ``"author physics on this prim"``).
    """
    try:
        asset_dir, ref_prim_path = authoring.placement.require_asset_context(stage, prim_path)
    except ValueError as exc:
        raise ValueError(
            f"{exc} This prim is authored directly in scene.usda, not as "
            "an asset placement. Retry the call with scope='scene' to "
            f"{scene_retry} directly in scene.usda.",
        ) from None
    return asset_dir, authoring.placement.normalize_asset_prim_path(
        prim_path, ref_prim_path, authoring.asset_folder.resolve_default_prim_name(asset_dir),
    )
