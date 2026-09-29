# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scene-level variants on a carrier prim, such as the lighting carrier."""

from __future__ import annotations

from collections.abc import Callable

from pxr import Usd
from pxr import UsdLux

from bowerbot import constants
from bowerbot.utils import usd


def add(
    stage: Usd.Stage,
    carrier_prim_path: str,
    variant_set: str,
    variant_name: str,
    author_fn: Callable[[Usd.Stage, str], None],
    set_as_default: bool = False,
) -> None:
    """Author a scene-level variant on a carrier prim; preserve prior default unless overridden."""
    prior_selection = ""
    prim = stage.GetPrimAtPath(carrier_prim_path)
    if prim and prim.IsValid():
        vset = prim.GetVariantSets().GetVariantSet(variant_set)
        if vset.IsValid():
            prior_selection = vset.GetVariantSelection() or ""

    usd.variant_sets.author_in_variant(
        stage, carrier_prim_path, variant_set, variant_name, author_fn,
    )

    prim = stage.GetPrimAtPath(carrier_prim_path)
    if not prim or not prim.IsValid():
        return
    if not prim.GetVariantSets().GetVariantSet(variant_set).IsValid():
        return

    if set_as_default:
        target = variant_name
    elif prior_selection:
        target = prior_selection
    else:
        target = variant_name
    usd.variant_sets.set_scene_variant_default(
        stage, carrier_prim_path, variant_set, target,
    )


def require_lighting_carrier(stage: Usd.Stage) -> str:
    """Return the lighting carrier path or raise if it does not exist yet."""
    if stage is None:
        raise ValueError("No scene stage is open.")
    carrier = constants.SceneNamespace.LIGHTING
    prim = stage.GetPrimAtPath(carrier)
    if not prim or not prim.IsValid():
        raise ValueError(
            f"No lighting carrier at {carrier}. Create at least one scene "
            "light before authoring a lighting variant.",
        )
    return carrier


def validate_lighting_targets(
    stage: Usd.Stage, carrier: str, paths,
) -> None:
    """Refuse target paths outside the carrier or not UsdLux lights."""
    for path in paths:
        if not path.startswith(carrier + "/"):
            raise ValueError(
                f"Lighting variant targets must be under {carrier}. Got: {path}",
            )
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.IsValid():
            raise ValueError(f"Prim not found: {path}")
        if not prim.HasAPI(UsdLux.LightAPI):
            raise ValueError(
                f"{path} is not a UsdLux light. Lighting variants target "
                "UsdLux prims only.",
            )
