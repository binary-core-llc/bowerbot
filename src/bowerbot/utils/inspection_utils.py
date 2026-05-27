# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Cross-domain stage inspection (``list_prims`` and friends)."""

from __future__ import annotations

from pxr import Sdf, Usd, UsdGeom, UsdLux

from bowerbot.utils import physics_typing_utils
from bowerbot.utils.light_utils import format_light_prim
from bowerbot.utils.physics_utils import (
    format_collision_group_prim,
    format_joint_prim,
    format_physics_scene_prim,
)
from bowerbot.utils.stage_utils import (
    extract_position,
    get_prim_ref_paths,
    world_bounds,
)


def list_prims(stage: Usd.Stage) -> list[dict]:
    """List every meaningful prim: placements, lights, geometry, physics."""
    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_],
    )

    results: list[dict] = []
    seen: set[str] = set()
    for prim in stage.Traverse():
        entry = _classify(prim, bbox_cache)
        if entry is None:
            continue
        if entry["prim_path"] in seen:
            continue
        seen.add(entry["prim_path"])
        results.append(entry)
    return results


def _classify(
    prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache,
) -> dict | None:
    """Return the formatted ``list_prims`` entry for *prim*, or None."""
    if physics_typing_utils.is_physics_scene(prim):
        return format_physics_scene_prim(prim)
    if physics_typing_utils.is_joint(prim):
        return format_joint_prim(prim)
    if physics_typing_utils.is_collision_group(prim):
        return format_collision_group_prim(prim)

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
    position = extract_position(target)
    if is_light:
        return format_light_prim(target, position)
    return _format_geometry_prim(target, position, bbox_cache)


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


def _format_geometry_prim(
    prim: Usd.Prim,
    position: dict[str, float] | None,
    bbox_cache: UsdGeom.BBoxCache,
) -> dict:
    """Format a referenced-asset or scene-authored Gprim for ``list_prims``."""
    ref_paths = get_prim_ref_paths(prim)
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "asset" if ref_paths else "geometry",
        "type": str(prim.GetTypeName()) or None,
        "asset": ref_paths[0] if ref_paths else None,
        "position": position,
        "bounds": world_bounds(prim, bbox_cache),
    }
