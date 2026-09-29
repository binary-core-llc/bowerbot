# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Where a physics write goes: into the asset (``phy.usda``) or into the scene."""

from __future__ import annotations

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
