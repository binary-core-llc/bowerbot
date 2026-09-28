# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Placing asset references in the scene, finding placements, and listing a prim's bindable parts.

The scene file itself (create, open, save, snapshots) is in ``authoring.stage``.
"""

from __future__ import annotations

from pathlib import Path

from pxr import Gf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade

from bowerbot import schemas
from bowerbot.utils import usd

# ── References ──


def add_reference(stage: Usd.Stage, scene_object: schemas.SceneObject) -> None:
    """Reference an asset under a wrapper Xform, conformed to the scene's units and up-axis."""
    add_references(stage, [scene_object])


def add_references(stage: Usd.Stage, scene_objects: list[schemas.SceneObject]) -> None:
    """Author a batch of asset references, computing conform once per unique asset."""
    conform: dict[str, tuple[float, float | None]] = {}
    for scene_object in scene_objects:
        asset_path = (
            scene_object.asset.file_path or scene_object.asset.source_id
        )
        if asset_path not in conform:
            conform[asset_path] = usd.metrics.asset_conform(stage, asset_path)
        unit_scale, up_axis_correction = conform[asset_path]

        wrapper = stage.DefinePrim(scene_object.prim_path, "Xform")
        xformable = UsdGeom.Xformable(wrapper)

        tx, ty, tz = scene_object.translate
        rx, ry, rz = scene_object.rotate
        sx, sy, sz = scene_object.scale
        final_scale = (sx * unit_scale, sy * unit_scale, sz * unit_scale)

        xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))
        xformable.AddScaleOp().Set(Gf.Vec3f(*final_scale))

        asset_prim = stage.DefinePrim(
            f"{scene_object.prim_path}/asset", "Xform",
        )
        if up_axis_correction is not None:
            UsdGeom.Xformable(asset_prim).AddRotateXOp().Set(up_axis_correction)
        asset_prim.GetReferences().AddReference(asset_path)


# ── Inspection ──


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


def count_scene_refs_to_asset_dir(stage: Usd.Stage, asset_dir: Path) -> int:
    """Count how many prims in the scene reference *asset_dir*."""
    return len(find_asset_placements(stage, asset_dir))


def find_asset_placements(stage: Usd.Stage, asset_dir: Path) -> list[str]:
    """Return scene prim paths of every wrapper-asset child referencing *asset_dir*."""
    root_path = stage.GetRootLayer().realPath
    if not root_path:
        return []
    stage_dir = Path(root_path).parent
    target_dir = asset_dir.resolve()
    placements: list[str] = []
    for prim in stage.Traverse():
        for ref_path in usd.references.get_prim_ref_paths(prim):
            resolved = (stage_dir / ref_path).resolve()
            if resolved.exists() and resolved.parent == target_dir:
                placements.append(str(prim.GetPath()))
                break
    return placements


def get_container_world_inverse(
    stage: Usd.Stage, container_prim_path: str,
) -> Gf.Matrix4d | None:
    """Return the inverse world transform of a container's wrapper Xform."""
    prim = stage.GetPrimAtPath(container_prim_path)
    if not prim or not prim.IsValid():
        return None

    wrapper = prim
    if prim.GetName() == "asset":
        parent = prim.GetParent()
        if parent and parent.IsValid():
            wrapper = parent

    xform_cache = UsdGeom.XformCache()
    return xform_cache.GetLocalToWorldTransform(wrapper).GetInverse()


def parse_nested_contents_path(prim_path: str) -> tuple[str, str] | None:
    """If *prim_path* is a nested-asset wrapper, return (group, prim_name)."""
    marker = "/asset/contents/"
    idx = prim_path.find(marker)
    if idx >= 0:
        suffix = prim_path[idx + len(marker):]
        parts = [p for p in suffix.split("/") if p]
        if len(parts) == 2:
            return parts[0], parts[1]
        msg = (
            f"Path {prim_path} is inside a nested asset's contents but "
            f"not at the wrapper level. Only the wrapper "
            f"(.../asset/contents/<group>/<name>) can be edited; deeper "
            f"prims live inside the referenced nested asset and editing "
            f"them at scene level would create per-instance overrides."
        )
        raise ValueError(msg)

    if "/asset/" in prim_path or prim_path.endswith("/asset"):
        msg = (
            f"Path {prim_path} is inside a referenced top-level asset. "
            f"Only the scene-level wrapper (/Scene/<Group>/<Name>) and "
            f"nested wrappers (.../asset/contents/<group>/<name>) can be "
            f"edited; everything else lives inside the referenced asset "
            f"and editing it at scene level would create per-instance "
            f"overrides."
        )
        raise ValueError(msg)

    return None


def world_to_local_point(
    stage: Usd.Stage,
    container_prim_path: str,
    x: float, y: float, z: float,
) -> tuple[float, float, float] | None:
    """Convert a world-space point into a container's local frame."""
    inv = get_container_world_inverse(stage, container_prim_path)
    if inv is None:
        return None
    local = inv.Transform(Gf.Vec3d(x, y, z))
    return float(local[0]), float(local[1]), float(local[2])
