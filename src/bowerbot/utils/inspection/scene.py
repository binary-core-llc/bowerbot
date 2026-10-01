# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Listing everything in the scene, classified by kind (the list_scene tool)."""

from __future__ import annotations

from typing import Any

from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdLux

from bowerbot.utils import inspection
from bowerbot.utils import usd


def list_prims(stage: Usd.Stage) -> list[dict]:
    """List every meaningful prim in the scene, classified by kind."""
    bbox_cache = usd.bounds.bounds_cache()

    results: list[dict] = []
    seen: set[str] = set()
    iterator = iter(stage.Traverse())
    for prim in iterator:
        entry: dict[str, Any] | None
        if prim.IsA(UsdGeom.PointInstancer):
            # Prototypes live under the instancer; they are not scene objects.
            iterator.PruneChildren()
            entry = inspection.entries.format_scatter_prim(prim, bbox_cache)
        else:
            entry = _classify(prim, bbox_cache)
        if entry is None:
            continue
        if entry["prim_path"] in seen:
            continue
        seen.add(entry["prim_path"])
        results.append(entry)
    return results


# ── Helpers ──


def _classify(
    prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache,
) -> dict | None:
    """Return the formatted ``list_prims`` entry for *prim*, or None."""
    if usd.prim_types.is_physics_scene(prim):
        return inspection.entries.format_physics_scene_prim(prim)
    if usd.prim_types.is_joint(prim):
        return inspection.entries.format_joint_prim(prim)
    if usd.prim_types.is_collision_group(prim):
        return inspection.entries.format_collision_group_prim(prim)
    if prim.IsA(UsdGeom.Camera):
        return inspection.entries.format_camera_prim(prim)

    is_light = prim.HasAPI(UsdLux.LightAPI)
    has_refs = prim.GetMetadata("references") is not None
    scene_gprim = (
        prim.IsA(UsdGeom.Gprim) and not _has_referenced_ancestor(prim)
    )
    if not (has_refs or is_light or scene_gprim):
        return None

    target = (
        _placement_ancestor(prim)
        if scene_gprim and not has_refs and not is_light
        else prim
    )
    position = usd.transforms.extract_position(target)
    if is_light:
        return inspection.entries.format_light_prim(target, position)
    return inspection.entries.format_geometry_prim(target, position, bbox_cache)


def _placement_ancestor(prim: Usd.Prim) -> Usd.Prim:
    """Walk up to the topmost Xform ancestor whose parent is ``/Scene``."""
    candidate = prim
    cursor = prim.GetParent()
    while (
        cursor and cursor.IsValid()
        and cursor.GetPath() != Sdf.Path.absoluteRootPath
        and str(cursor.GetPath()) != "/Scene"
    ):
        if cursor.IsA(UsdGeom.Xform):
            candidate = cursor
        cursor = cursor.GetParent()
    return candidate


def _has_referenced_ancestor(prim: Usd.Prim) -> bool:
    """Whether any ancestor of *prim* carries an authored references arc."""
    cursor = prim.GetParent()
    while (
        cursor and cursor.IsValid()
        and cursor.GetPath() != Sdf.Path.absoluteRootPath
    ):
        if cursor.GetMetadata("references") is not None:
            return True
        cursor = cursor.GetParent()
    return False
