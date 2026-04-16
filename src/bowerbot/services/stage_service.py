# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage service — create, open, edit, and query USD stages.

All direct scene-level ``pxr`` calls live here. Services are stateless;
callers pass in the ``Usd.Stage`` they want to operate on.
"""

from __future__ import annotations

import os
from pathlib import Path

from pxr import Gf, Kind, Sdf, Usd, UsdGeom, UsdLux, UsdShade

from bowerbot.schemas import LightParams, SceneObject
from bowerbot.utils.usd_utils import LIGHT_CLASSES, get_prim_ref_paths


def create_empty_scene(path: str | Path) -> None:
    """Create a minimal scene file with BowerBot defaults.

    Writes ``metersPerUnit``, ``upAxis``, and a root ``/Scene`` Xform.
    Skips creation if the file already exists.
    """
    path = Path(path)
    if path.exists():
        return

    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    root = stage.DefinePrim("/Scene", "Xform")
    stage.SetDefaultPrim(root)
    Usd.ModelAPI(root).SetKind(Kind.Tokens.assembly)

    stage.Save()


def create_stage(path: str | Path) -> Usd.Stage:
    """Create a new scene on disk and return the open stage."""
    create_empty_scene(path)
    return Usd.Stage.Open(str(path))


def open_stage(path: str | Path) -> Usd.Stage:
    """Open an existing USD stage from disk."""
    return Usd.Stage.Open(str(path))


def save(stage: Usd.Stage) -> None:
    """Save the stage to its root layer."""
    stage.Save()


def add_reference(stage: Usd.Stage, scene_object: SceneObject) -> None:
    """Add a referenced asset to *stage* at ``scene_object.prim_path``.

    Uses a wrapper-prim pattern: BowerBot's translate/rotate/scale lives
    on the wrapper Xform, and the reference arc is placed on an
    ``/asset`` child so DCC export transforms inside the reference
    stay untouched.
    """
    asset_path = (
        scene_object.asset.file_path or scene_object.asset.source_id
    )

    unit_scale = _compute_unit_scale(stage, asset_path)

    wrapper = stage.DefinePrim(scene_object.prim_path, "Xform")
    xformable = UsdGeom.Xformable(wrapper)

    tx, ty, tz = scene_object.translate
    xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))

    rx, ry, rz = scene_object.rotate
    if any(v != 0.0 for v in (rx, ry, rz)):
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))

    if abs(unit_scale - 1.0) > 1e-6:
        xformable.AddScaleOp().Set(
            Gf.Vec3f(unit_scale, unit_scale, unit_scale),
        )
    else:
        sx, sy, sz = scene_object.scale
        if any(v != 1.0 for v in (sx, sy, sz)):
            xformable.AddScaleOp().Set(Gf.Vec3f(sx, sy, sz))

    asset_prim = stage.DefinePrim(
        f"{scene_object.prim_path}/asset", "Xform",
    )
    asset_prim.GetReferences().AddReference(asset_path)


def create_light(stage: Usd.Stage, prim_path: str, light: LightParams) -> None:
    """Create a USD light prim in *stage* at *prim_path*."""
    light_cls = LIGHT_CLASSES[light.light_type.value]
    light_prim = light_cls.Define(stage, prim_path)

    light_prim.CreateIntensityAttr(light.intensity)
    light_prim.CreateExposureAttr(light.exposure)
    light_prim.CreateColorAttr(Gf.Vec3f(*light.color))

    _set_light_type_attrs(light_prim, light)

    xformable = UsdGeom.Xformable(light_prim)
    xformable.ClearXformOpOrder()

    tx, ty, tz = light.translate
    xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))

    rx, ry, rz = light.rotate
    if any(v != 0.0 for v in (rx, ry, rz)):
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))


def update_light(
    stage: Usd.Stage,
    prim_path: str,
    *,
    intensity: float | None = None,
    exposure: float | None = None,
    color: tuple[float, float, float] | None = None,
    translate: tuple[float, float, float] | None = None,
    rotate: tuple[float, float, float] | None = None,
    **extra_attrs: float | None,
) -> None:
    """Update attributes of an existing scene-level light prim.

    Only modifies parameters that are not ``None``.
    """
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)

    if intensity is not None:
        _set_attr(prim, "inputs:intensity", intensity)
    if exposure is not None:
        _set_attr(prim, "inputs:exposure", exposure)
    if color is not None:
        _set_attr(prim, "inputs:color", Gf.Vec3f(*color))

    for attr_name, usd_attr in _LIGHT_SPATIAL_ATTRS.items():
        value = extra_attrs.get(attr_name)
        if value is not None:
            _set_attr(prim, usd_attr, float(value))

    if translate is not None:
        _update_translate_op(prim, Gf.Vec3d(*translate))
    if rotate is not None:
        _update_rotate_op(prim, Gf.Vec3f(*rotate))


def set_transform(
    stage: Usd.Stage,
    prim_path: str,
    translate: tuple[float, float, float],
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> None:
    """Update translate/rotate on an existing prim in place.

    Preserves BowerBot's other xform ops (e.g. unit-conversion scale)
    and does not touch the referenced geometry's own transforms.
    """
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)

    xformable = UsdGeom.Xformable(prim)
    tx, ty, tz = translate
    rx, ry, rz = rotate

    found_translate = False
    found_rotate = False
    for op in xformable.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            if op.GetOpName() == "xformOp:translate":
                op.Set(Gf.Vec3d(tx, ty, tz))
                found_translate = True
        elif op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            op.Set(Gf.Vec3f(rx, ry, rz))
            found_rotate = True

    if not found_translate:
        xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))
    if not found_rotate and any(v != 0.0 for v in (rx, ry, rz)):
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))


def list_prims(stage: Usd.Stage) -> list[dict]:
    """List all referenced assets and lights placed in *stage*."""
    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_],
    )

    results: list[dict] = []
    for prim in stage.Traverse():
        is_light = prim.HasAPI(UsdLux.LightAPI)
        has_refs = prim.GetMetadata("references") is not None

        if not has_refs and not is_light:
            continue

        position = _extract_position(prim)
        if is_light:
            results.append(_format_light_prim(prim, position))
        else:
            results.append(_format_geometry_prim(prim, position, bbox_cache))

    return results


def list_prim_children(stage: Usd.Stage, prim_path: str) -> list[dict]:
    """Return descendant prims that contain geometry under *prim_path*.

    Reports each descendant's USD type, mesh-ness, current material
    binding, and world-space bounds.
    """
    root_prim = stage.GetPrimAtPath(prim_path)
    if not root_prim.IsValid():
        return []

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_],
    )

    results: list[dict] = []
    for prim in Usd.PrimRange(root_prim):
        if str(prim.GetPath()) == prim_path:
            continue

        type_name = prim.GetTypeName()
        is_mesh = type_name == "Mesh"
        has_geometry = is_mesh or _has_mesh_descendant(prim)
        if not has_geometry:
            continue

        bound_mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        current_material = str(bound_mat.GetPath()) if bound_mat else None

        results.append({
            "prim_path": str(prim.GetPath()),
            "name": prim.GetName(),
            "type": type_name or "Xform",
            "is_mesh": is_mesh,
            "current_material": current_material,
            "bounds": _world_bounds(prim, bbox_cache),
        })

    return results


def get_all_ref_paths(stage: Usd.Stage) -> set[str]:
    """Collect every reference asset path authored on the stage."""
    refs: set[str] = set()
    for prim in stage.Traverse():
        refs.update(get_prim_ref_paths(prim))
    return refs


def get_light_texture(stage: Usd.Stage, prim_path: str) -> str | None:
    """Return the texture file path for a light prim, or ``None``."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return None
    tex_attr = prim.GetAttribute("inputs:texture:file")
    if not tex_attr or not tex_attr.Get():
        return None
    tex_val = tex_attr.Get()
    return tex_val.path if hasattr(tex_val, "path") else str(tex_val)


def get_container_world_inverse(
    stage: Usd.Stage, container_prim_path: str,
) -> Gf.Matrix4d | None:
    """Return the inverse world transform of a container's wrapper.

    BowerBot places references under an Xform wrapper with the scene
    transform, and the reference arc on an ``/asset`` child. The
    wrapper's inverse is what converts world-space input coordinates
    into the asset's internal coordinate frame. Accepts either the
    wrapper path or the ``/asset`` child path.
    """
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


def rename_prim(stage: Usd.Stage, old_path: str, new_path: str) -> bool:
    """Rename/move a prim to a new path in the stage hierarchy.

    Creates intermediate parents as Xforms when needed. Saves on
    success. The caller should reopen the stage afterwards to pick
    up the namespace change.
    """
    old_prim = stage.GetPrimAtPath(old_path)
    if not old_prim.IsValid():
        msg = f"Prim not found: {old_path}"
        raise ValueError(msg)

    parent_path = str(Sdf.Path(new_path).GetParentPath())
    if parent_path and parent_path != "/":
        parent_prim = stage.GetPrimAtPath(parent_path)
        if not parent_prim.IsValid():
            stage.DefinePrim(parent_path, "Xform")

    edit = Sdf.BatchNamespaceEdit()
    edit.Add(old_path, new_path)
    success = stage.GetRootLayer().Apply(edit)
    if success:
        stage.Save()
    return success


def remove_prim(stage: Usd.Stage, prim_path: str) -> bool:
    """Remove a prim from *stage* and save on success."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)

    removed = stage.RemovePrim(prim_path)
    if removed:
        stage.Save()
    return removed


_LIGHT_SPATIAL_ATTRS: dict[str, str] = {
    "radius": "inputs:radius",
    "angle": "inputs:angle",
    "width": "inputs:width",
    "height": "inputs:height",
    "length": "inputs:length",
}

_LIGHT_TYPE_ATTRS: dict[str, str] = {
    "angle": "CreateAngleAttr",
    "texture": "CreateTextureFileAttr",
    "radius": "CreateRadiusAttr",
    "width": "CreateWidthAttr",
    "height": "CreateHeightAttr",
    "length": "CreateLengthAttr",
}


def _set_light_type_attrs(light_prim: UsdLux.LightAPI, light: LightParams) -> None:
    """Set type-specific attributes on a freshly defined light prim."""
    for field_name, create_method in _LIGHT_TYPE_ATTRS.items():
        value = getattr(light, field_name, None)
        if value is not None and hasattr(light_prim, create_method):
            getattr(light_prim, create_method)().Set(value)


def _set_attr(prim: Usd.Prim, name: str, value: object) -> None:
    """Set an authored attribute on *prim* if it exists."""
    attr = prim.GetAttribute(name)
    if attr:
        attr.Set(value)


def _update_translate_op(prim: Usd.Prim, value: Gf.Vec3d) -> None:
    """Update the first translate xform op on *prim*."""
    xformable = UsdGeom.Xformable(prim)
    for op in xformable.GetOrderedXformOps():
        if op.GetOpName() == "xformOp:translate":
            op.Set(value)
            return


def _update_rotate_op(prim: Usd.Prim, value: Gf.Vec3f) -> None:
    """Update the first rotateXYZ xform op on *prim*."""
    xformable = UsdGeom.Xformable(prim)
    for op in xformable.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            op.Set(value)
            return


def _compute_unit_scale(stage: Usd.Stage, asset_path: str) -> float:
    """Return the factor to scale an asset into the stage's unit space."""
    if not os.path.isabs(asset_path):
        stage_dir = os.path.dirname(stage.GetRootLayer().realPath)
        asset_path = os.path.join(stage_dir, asset_path)

    asset_stage = Usd.Stage.Open(asset_path)
    if asset_stage is None:
        return 1.0

    asset_mpu = UsdGeom.GetStageMetersPerUnit(asset_stage)
    scene_mpu = UsdGeom.GetStageMetersPerUnit(stage)
    if scene_mpu == 0:
        return 1.0
    return asset_mpu / scene_mpu


def _extract_position(prim: Usd.Prim) -> dict[str, float] | None:
    """Return the translate component of a prim's local transform."""
    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        return None
    t = xformable.GetLocalTransformation().ExtractTranslation()
    return {"x": round(t[0], 2), "y": round(t[1], 2), "z": round(t[2], 2)}


def _format_light_prim(
    prim: Usd.Prim, position: dict[str, float] | None,
) -> dict:
    """Format a light prim for ``list_prims``."""
    data: dict = {
        "prim_path": str(prim.GetPath()),
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


def _format_geometry_prim(
    prim: Usd.Prim,
    position: dict[str, float] | None,
    bbox_cache: UsdGeom.BBoxCache,
) -> dict:
    """Format a referenced-asset prim for ``list_prims``."""
    ref_paths = get_prim_ref_paths(prim)
    return {
        "prim_path": str(prim.GetPath()),
        "asset": ref_paths[0] if ref_paths else None,
        "position": position,
        "bounds": _world_bounds(prim, bbox_cache),
    }


def _world_bounds(
    prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache,
) -> dict | None:
    """Compute world-aligned AABB for a prim, rounded to 4 decimals."""
    rng = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
    if rng.IsEmpty():
        return None
    mn, mx = rng.GetMin(), rng.GetMax()
    return {
        "min": {"x": round(mn[0], 4), "y": round(mn[1], 4), "z": round(mn[2], 4)},
        "max": {"x": round(mx[0], 4), "y": round(mx[1], 4), "z": round(mx[2], 4)},
    }


def _has_mesh_descendant(prim: Usd.Prim) -> bool:
    """Return True if any descendant of *prim* is a Mesh."""
    for child in Usd.PrimRange(prim):
        if child.GetTypeName() == "Mesh":
            return True
    return False
