# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics scope — whether a request targets an asset's phy.usda or the scene."""

from __future__ import annotations

from pxr import Usd

from bowerbot.utils.core.asset_folder import require_asset_context


def validate_scope(scope: str) -> str:
    """Refuse any value other than ``'asset'`` or ``'scene'``."""
    if scope not in ("asset", "scene"):
        raise ValueError(
            f"Invalid scope {scope!r}; must be 'asset' or 'scene'.",
        )
    return scope


def autodetect_scope(stage: Usd.Stage, prim_path: str) -> str:
    """Return ``'asset'`` if *prim_path* resolves through an ASWF placement; else ``'scene'``."""
    try:
        require_asset_context(stage, prim_path)
    except ValueError:
        return "scene"
    return "asset"
