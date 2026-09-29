# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""A prim's bindable parts: every Gprim at or under it, with its bound material."""

from __future__ import annotations

from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade

from bowerbot.utils import usd


def list_bindable_parts(stage: Usd.Stage, prim_path: str) -> list[dict]:
    """Return every bindable Gprim at or under *prim_path*."""
    root_prim = stage.GetPrimAtPath(prim_path)
    if not root_prim.IsValid():
        return []

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_],
    )

    results: list[dict] = []
    for prim in Usd.PrimRange(root_prim):
        if not prim.IsA(UsdGeom.Gprim):
            continue
        bound_mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        type_name = prim.GetTypeName()
        results.append({
            "prim_path": str(prim.GetPath()),
            "name": prim.GetName(),
            "type": type_name or "Xform",
            "is_mesh": type_name == "Mesh",
            "is_bindable": True,
            "current_material": str(bound_mat.GetPath()) if bound_mat else None,
            "bounds": usd.bounds.world_bounds(prim, bbox_cache),
        })
    return results
