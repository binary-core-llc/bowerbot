# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scene-level lights: creating and updating them."""

from __future__ import annotations

from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import lights
from bowerbot.utils import usd


def create(stage: Usd.Stage, prim_path: str, light: schemas.LightParams) -> None:
    """Create a USD light prim in *stage* at *prim_path*."""
    light_cls = constants.LightUsd.CLASSES[light.light_type.value]
    light_prim = light_cls.Define(stage, prim_path).GetPrim()

    lights.prim.write_attributes(stage, prim_path, light.attributes)
    if light.texture is not None:
        tex_attr = light_prim.GetAttribute("inputs:texture:file")
        if tex_attr:
            tex_attr.Set(Sdf.AssetPath(light.texture))
    lights.prim.apply_light_link(light_prim, light.light_link_includes)

    UsdGeom.Xformable(light_prim).ClearXformOpOrder()
    usd.transforms.set_xform(
        light_prim,
        translate=light.translate,
        rotate=light.rotate if any(v != 0.0 for v in light.rotate) else None,
    )


def update(
    stage: Usd.Stage,
    prim_path: str,
    *,
    translate: schemas.PartialVec3 | None = None,
    rotate: schemas.PartialVec3 | None = None,
    texture: str | None = None,
) -> None:
    """Update an existing scene-level light's xform / HDRI texture.

    An axis left out of *translate* or *rotate* keeps its value.
    """
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)

    if texture is not None:
        tex_attr = prim.GetAttribute("inputs:texture:file")
        if tex_attr:
            tex_attr.Set(Sdf.AssetPath(texture))

    usd.transforms.set_xform(prim, translate=translate, rotate=rotate)
