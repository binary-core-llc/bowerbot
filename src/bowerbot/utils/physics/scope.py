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


def asset_relationship_targets(
    stage: Usd.Stage, asset_dir: Path, relationships: dict[str, list[str]],
) -> dict[str, list[str]]:
    """*relationships* with every target as a path inside the asset.

    A relationship written in an asset's file can only reach prims of that
    asset: a target outside it would be written and then point at nothing.
    Such a target is refused.
    """
    default_prim = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    inside: dict[str, list[str]] = {}
    for name, targets in relationships.items():
        inside[name] = []
        for target in targets:
            if target == f"/{default_prim}" or target.startswith(f"/{default_prim}/"):
                inside[name].append(target)
                continue
            target_dir, ref_prim_path = authoring.placement.resolve_asset_dir_for_prim(
                stage, target,
            )
            if target_dir != asset_dir or ref_prim_path is None:
                raise ValueError(
                    f"{name} -> {target}: with scope='asset' a relationship can only point "
                    f"to a prim of the same asset ({asset_dir.name}); the asset's files "
                    "cannot reach a prim outside it. Use scope='scene' for this.",
                )
            inside[name].append(
                authoring.placement.normalize_asset_prim_path(target, ref_prim_path, default_prim),
            )
    return inside


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
