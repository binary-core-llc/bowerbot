# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Describing what is in the scene: list_scene entries for every kind of prim, a prim's parts."""

from __future__ import annotations

from typing import Any

from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdLux
from pxr import UsdPhysics
from pxr import UsdShade

from bowerbot import constants
from bowerbot.utils import usd

# ── Listing the scene ──


def list_prims(stage: Usd.Stage) -> list[dict]:
    """List every meaningful prim in the scene, classified by kind."""
    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_],
    )

    results: list[dict] = []
    seen: set[str] = set()
    iterator = iter(stage.Traverse())
    for prim in iterator:
        entry: dict[str, Any] | None
        if prim.IsA(UsdGeom.PointInstancer):
            # Prototypes live under the instancer; they are not scene objects.
            iterator.PruneChildren()
            entry = format_scatter_prim(prim, bbox_cache)
        else:
            entry = _classify(prim, bbox_cache)
        if entry is None:
            continue
        if entry["prim_path"] in seen:
            continue
        seen.add(entry["prim_path"])
        results.append(entry)
    return results


# ── A prim's parts ──


def list_prim_children(stage: Usd.Stage, prim_path: str) -> list[dict]:
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


# ── Entries for each kind of prim ──


def format_camera_prim(prim: Usd.Prim) -> dict:
    """Format a Camera prim for ``list_prims``."""
    camera = UsdGeom.Camera(prim)
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "camera",
        "type": str(prim.GetTypeName()),
        "projection": str(camera.GetProjectionAttr().Get()),
        "focal_length": float(camera.GetFocalLengthAttr().Get()),
        "position": usd.transforms.extract_position(prim),
    }


def format_light_prim(
    prim: Usd.Prim, position: dict[str, float] | None,
) -> dict:
    """Format a light prim for ``list_prims``."""
    data: dict = {
        "prim_path": str(prim.GetPath()),
        "kind": "light",
        "light_type": prim.GetTypeName(),
        "position": position,
    }
    intensity_attr = prim.GetAttribute("inputs:intensity")
    if intensity_attr:
        data["intensity"] = intensity_attr.Get()
    exposure_attr = prim.GetAttribute("inputs:exposure")
    if exposure_attr:
        data["exposure"] = exposure_attr.Get()
    color_attr = prim.GetAttribute("inputs:color")
    if color_attr:
        c = color_attr.Get()
        data["color"] = {
            "r": round(c[0], 3), "g": round(c[1], 3), "b": round(c[2], 3),
        }
    return data


def format_physics_scene_prim(prim: Usd.Prim) -> dict:
    """Format a ``UsdPhysics.Scene`` for ``list_prims``."""
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "physics_scene",
        "type": str(prim.GetTypeName()),
    }


def format_joint_prim(prim: Usd.Prim) -> dict:
    """Format a UsdPhysics joint for ``list_prims``."""
    body0_rel = prim.GetRelationship("physics:body0")
    body1_rel = prim.GetRelationship("physics:body1")
    body0 = [str(t) for t in body0_rel.GetTargets()] if body0_rel else []
    body1 = [str(t) for t in body1_rel.GetTargets()] if body1_rel else []
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "joint",
        "type": str(prim.GetTypeName()),
        "body0": body0[0] if body0 else None,
        "body1": body1[0] if body1 else None,
    }


def format_collision_group_prim(prim: Usd.Prim) -> dict:
    """Format a ``UsdPhysics.CollisionGroup`` for ``list_prims``."""
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "collision_group",
        "type": str(prim.GetTypeName()),
        "name": prim.GetName(),
    }


def format_scatter_prim(prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache) -> dict[str, Any]:
    """``list_scene`` entry for a scatter PointInstancer."""
    instancer = UsdGeom.PointInstancer(prim)
    indices = instancer.GetProtoIndicesAttr().Get() or []
    stage = prim.GetStage()
    prototypes = []
    for target in instancer.GetPrototypesRel().GetTargets():
        proto = stage.GetPrimAtPath(target)
        child = proto.GetChild("asset") if proto.IsValid() else proto
        refs = usd.references.get_prim_ref_paths(child) if child and child.IsValid() else []
        prototypes.append(refs[0] if refs else str(target))
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "scatter",
        "type": "PointInstancer",
        "instances": len(indices),
        "prototypes": prototypes,
        "position": usd.transforms.extract_position(prim),
        "bounds": usd.bounds.world_bounds(prim, bbox_cache),
    }


# ── Physics prim types ──


def is_physics_scene(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is a ``UsdPhysics.Scene``."""
    return prim is not None and prim.IsA(UsdPhysics.Scene)


def is_joint(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is one of the supported UsdPhysics joint typed prims."""
    return prim is not None and any(prim.IsA(c) for c in constants.PhysicsUsd.JOINTS.values())


def is_collision_group(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is a ``UsdPhysics.CollisionGroup``."""
    return prim is not None and prim.IsA(UsdPhysics.CollisionGroup)


# ── Helpers ──


def _classify(
    prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache,
) -> dict | None:
    """Return the formatted ``list_prims`` entry for *prim*, or None."""
    if is_physics_scene(prim):
        return format_physics_scene_prim(prim)
    if is_joint(prim):
        return format_joint_prim(prim)
    if is_collision_group(prim):
        return format_collision_group_prim(prim)
    if prim.IsA(UsdGeom.Camera):
        return format_camera_prim(prim)

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
    ref_paths = usd.references.get_prim_ref_paths(prim)
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "asset" if ref_paths else "geometry",
        "type": str(prim.GetTypeName()) or None,
        "asset": ref_paths[0] if ref_paths else None,
        "position": position,
        "bounds": usd.bounds.world_bounds(prim, bbox_cache),
    }
