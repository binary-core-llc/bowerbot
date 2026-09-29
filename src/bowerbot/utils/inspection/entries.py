# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The list_scene entry for each kind of prim, and the physics prim type checks."""

from __future__ import annotations

from typing import Any

from pxr import Usd
from pxr import UsdGeom
from pxr import UsdPhysics

from bowerbot import constants
from bowerbot.utils import usd


def format_geometry_prim(
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


def is_physics_scene(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is a ``UsdPhysics.Scene``."""
    return prim is not None and prim.IsA(UsdPhysics.Scene)


def is_joint(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is one of the supported UsdPhysics joint typed prims."""
    return prim is not None and any(prim.IsA(c) for c in constants.PhysicsUsd.JOINTS.values())


def is_collision_group(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is a ``UsdPhysics.CollisionGroup``."""
    return prim is not None and prim.IsA(UsdPhysics.CollisionGroup)
