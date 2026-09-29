# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Operations on any light prim: its UsdLux attributes, its light link, its texture."""

from __future__ import annotations

from typing import Any

from pxr import Sdf
from pxr import Usd
from pxr import UsdLux

from bowerbot.utils import usd


def write_attributes(
    stage: Usd.Stage, prim_path: str, attributes: dict[str, Any],
) -> None:
    """Write a UsdLux ``inputs:*`` dict onto an existing light prim."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")
    for name, value in attributes.items():
        attr = prim.GetAttribute(name)
        if not attr:
            continue
        usd.attributes.set_prim_attribute(
            stage, prim_path, name, value, expected_type=attr.GetTypeName(),
        )


def apply_light_link(light_prim: Usd.Prim, includes: list[str]) -> None:
    """Author the UsdLux light:link collection only when targets are provided."""
    if not includes:
        return
    binding = UsdLux.LightAPI(light_prim).GetLightLinkCollectionAPI()
    binding.CreateIncludesRel().SetTargets([Sdf.Path(p) for p in includes])
    binding.CreateIncludeRootAttr(False)


def get_texture(stage: Usd.Stage, prim_path: str) -> str | None:
    """Return the texture file path for a light prim, or ``None``."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return None
    tex_attr = prim.GetAttribute("inputs:texture:file")
    if not tex_attr or not tex_attr.Get():
        return None
    tex_val = tex_attr.Get()
    return tex_val.path if hasattr(tex_val, "path") else str(tex_val)
