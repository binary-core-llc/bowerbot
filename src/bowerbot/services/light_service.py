# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Light service — add, update, remove lights inside ASWF asset folders.

Scene-level light writes live in ``stage_service``; this module handles
the lights that live under an asset's ``lgt.usda``. Values flow in as
meters and are converted to the asset's native units here, because
asset layers hold coordinates in their own ``metersPerUnit`` frame.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux

from bowerbot.schemas import ASWFLayerNames, LightParams
from bowerbot.services.asset_service import (
    ensure_layer_scope,
    ensure_root_reference,
    find_root_file,
    remove_empty_layer,
    resolve_default_prim_name,
)
from bowerbot.services.geometry_service import meters_to_asset_units, unit_factor
from bowerbot.utils.usd_utils import LIGHT_CLASSES

logger = logging.getLogger(__name__)

_LIGHT_EXTRA_ATTRS: dict[str, str] = {
    "angle": "inputs:angle",
    "texture": "inputs:texture:file",
    "radius": "inputs:radius",
    "width": "inputs:width",
    "height": "inputs:height",
    "length": "inputs:length",
}
_SPATIAL_LIGHT_ATTRS: frozenset[str] = frozenset(
    {"radius", "width", "height", "length"},
)


def add_light(
    asset_dir: Path,
    light_name: str,
    light: LightParams,
) -> str:
    """Add a light to an asset folder's ``lgt.usda``.

    Creates the layer if needed, applies an inverse-transform op on the
    ``lgt/`` scope so lights sit in clean world-aligned space, and
    converts spatial inputs (translate, radius, width, height, length)
    from meters to the asset's units.

    Returns the light prim path in the composed stage.
    """
    lgt_path = asset_dir / ASWFLayerNames.LGT
    default_prim_name = resolve_default_prim_name(asset_dir)

    if lgt_path.exists():
        lgt_layer = Sdf.Layer.FindOrOpen(str(lgt_path))
    else:
        lgt_layer = Sdf.Layer.CreateNew(str(lgt_path))
        lgt_layer.defaultPrim = default_prim_name

    lgt_scope_path = Sdf.Path(f"/{default_prim_name}/lgt")
    ensure_layer_scope(lgt_layer, default_prim_name, "lgt", "Xform")
    lgt_layer.Save()

    _apply_inverse_transform(asset_dir, lgt_path, lgt_scope_path)

    stage = Usd.Stage.Open(str(lgt_path))
    if stage is None:
        msg = f"Cannot open lgt layer: {lgt_path}"
        raise RuntimeError(msg)

    light_prim_path = f"/{default_prim_name}/lgt/{light_name}"
    light_cls = LIGHT_CLASSES.get(light.light_type.value)
    if light_cls is None:
        msg = f"Unknown light type: {light.light_type.value}"
        raise ValueError(msg)

    light_schema = light_cls.Define(stage, light_prim_path)
    light_schema.CreateIntensityAttr(light.intensity)
    light_schema.CreateExposureAttr(light.exposure)
    light_schema.CreateColorAttr(Gf.Vec3f(*light.color))

    factor = unit_factor(asset_dir)
    light_prim = light_schema.GetPrim()
    _set_extra_attrs(
        light_prim,
        {
            "angle": light.angle,
            "texture": light.texture,
            "radius": _scale_or_none(light.radius, factor),
            "width": _scale_or_none(light.width, factor),
            "height": _scale_or_none(light.height, factor),
            "length": _scale_or_none(light.length, factor),
        },
    )

    xformable = UsdGeom.Xformable(light_prim)
    xformable.AddTranslateOp().Set(
        Gf.Vec3d(
            light.translate[0] * factor,
            light.translate[1] * factor,
            light.translate[2] * factor,
        ),
    )
    if any(v != 0.0 for v in light.rotate):
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(*light.rotate))

    stage.Save()
    ensure_root_reference(asset_dir, ASWFLayerNames.LGT)

    logger.info(
        "Added light %s (%s) to %s",
        light_name, light.light_type.value, asset_dir.name,
    )
    return light_prim_path


def update_light(
    asset_dir: Path,
    light_name: str,
    *,
    translate: tuple[float, float, float] | None = None,
    rotate: tuple[float, float, float] | None = None,
    intensity: float | None = None,
    exposure: float | None = None,
    color: tuple[float, float, float] | None = None,
    **extra_attrs: float | str | None,
) -> None:
    """Update an asset-folder light's attributes in place.

    Spatial extras (radius, width, height, length) and translate are
    converted from meters into the asset's native units. Only fields
    that are not ``None`` are modified.
    """
    lgt_path = asset_dir / ASWFLayerNames.LGT
    if not lgt_path.exists():
        msg = f"No {ASWFLayerNames.LGT} found in asset folder"
        raise ValueError(msg)

    default_prim_name = resolve_default_prim_name(asset_dir)
    light_prim_path = f"/{default_prim_name}/lgt/{light_name}"

    stage = Usd.Stage.Open(str(lgt_path))
    if stage is None:
        msg = f"Cannot open lgt layer: {lgt_path}"
        raise RuntimeError(msg)

    prim = stage.GetPrimAtPath(light_prim_path)
    if not prim.IsValid():
        msg = f"Light not found: {light_name}"
        raise ValueError(msg)

    if intensity is not None:
        prim.GetAttribute("inputs:intensity").Set(intensity)
    if exposure is not None:
        prim.GetAttribute("inputs:exposure").Set(exposure)
    if color is not None:
        prim.GetAttribute("inputs:color").Set(Gf.Vec3f(*color))

    _update_extra_attrs(prim, asset_dir, extra_attrs)

    if translate is not None:
        _set_translate(prim, translate, unit_factor(asset_dir))
    if rotate is not None:
        _set_rotate(prim, rotate)

    stage.Save()
    logger.info("Updated light %s in %s", light_name, asset_dir.name)


def remove_light(asset_dir: Path, light_name: str) -> None:
    """Remove a light from an asset folder's ``lgt.usda``.

    When no lights remain, deletes the layer and rebuilds the root
    references.
    """
    lgt_path = asset_dir / ASWFLayerNames.LGT
    if not lgt_path.exists():
        return

    default_prim_name = resolve_default_prim_name(asset_dir)
    light_prim_path = Sdf.Path(f"/{default_prim_name}/lgt/{light_name}")

    lgt_layer = Sdf.Layer.FindOrOpen(str(lgt_path))
    if lgt_layer is None:
        return

    if lgt_layer.GetPrimAtPath(light_prim_path):
        edit = Sdf.BatchNamespaceEdit()
        edit.Add(light_prim_path, Sdf.Path.emptyPath)
        lgt_layer.Apply(edit)
        lgt_layer.Save()

    remove_empty_layer(
        lgt_path, asset_dir, lambda p: p.HasAPI(UsdLux.LightAPI),
    )


def list_lights(asset_dir: Path) -> list[dict]:
    """List all lights declared in an asset folder's ``lgt.usda``."""
    lgt_path = asset_dir / ASWFLayerNames.LGT
    if not lgt_path.exists():
        return []

    root_file = find_root_file(asset_dir)
    if root_file is None:
        return []

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return []

    return [
        {
            "prim_path": str(prim.GetPath()),
            "name": prim.GetName(),
            "type": prim.GetTypeName(),
        }
        for prim in stage.Traverse()
        if prim.HasAPI(UsdLux.LightAPI)
    ]


def _scale_or_none(value: float | None, factor: float) -> float | None:
    """Multiply *value* by *factor*, preserving ``None``."""
    return value * factor if value is not None else None


def _set_extra_attrs(
    light_prim: Usd.Prim,
    values: dict[str, float | str | None],
) -> None:
    """Set type-specific attributes on a newly created light prim."""
    for attr_name, usd_attr in _LIGHT_EXTRA_ATTRS.items():
        value = values.get(attr_name)
        if value is not None:
            attr = light_prim.GetAttribute(usd_attr)
            if attr:
                attr.Set(value)


def _update_extra_attrs(
    prim: Usd.Prim,
    asset_dir: Path,
    values: dict[str, float | str | None],
) -> None:
    """Update type-specific attributes on an existing light prim.

    Spatial attributes (radius, width, height, length) are converted
    from meters into the asset's native units.
    """
    for attr_name, usd_attr in _LIGHT_EXTRA_ATTRS.items():
        value = values.get(attr_name)
        if value is None:
            continue
        if attr_name in _SPATIAL_LIGHT_ATTRS:
            value = meters_to_asset_units(asset_dir, float(value))
        attr = prim.GetAttribute(usd_attr)
        if attr:
            attr.Set(value)


def _set_translate(
    prim: Usd.Prim,
    translate: tuple[float, float, float],
    factor: float,
) -> None:
    """Set or update a translate xform op on a prim."""
    converted = Gf.Vec3d(
        translate[0] * factor,
        translate[1] * factor,
        translate[2] * factor,
    )
    xformable = UsdGeom.Xformable(prim)
    for op in xformable.GetOrderedXformOps():
        if op.GetOpName() == "xformOp:translate":
            op.Set(converted)
            return
    xformable.AddTranslateOp().Set(converted)


def _set_rotate(
    prim: Usd.Prim, rotate: tuple[float, float, float],
) -> None:
    """Set or update a rotateXYZ xform op on a prim."""
    xformable = UsdGeom.Xformable(prim)
    for op in xformable.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            op.Set(Gf.Vec3f(*rotate))
            return
    if any(v != 0.0 for v in rotate):
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(*rotate))


def _apply_inverse_transform(
    asset_dir: Path,
    lgt_path: Path,
    lgt_scope_path: Sdf.Path,
) -> None:
    """Apply the inverse of the geometry root transform on the lgt Xform.

    Cancels the inherited transform from the root prim so lights
    authored under ``lgt/`` sit in clean world-aligned space.
    """
    geo_path = asset_dir / ASWFLayerNames.GEO
    if not geo_path.exists():
        return

    geo_stage = Usd.Stage.Open(str(geo_path))
    if geo_stage is None:
        return

    root = geo_stage.GetDefaultPrim()
    if root is None:
        return

    local_xform = UsdGeom.Xformable(root).GetLocalTransformation()
    if local_xform == Gf.Matrix4d(1.0):
        return

    inverse = local_xform.GetInverse()

    lgt_stage = Usd.Stage.Open(str(lgt_path))
    if lgt_stage is None:
        return

    scope_prim = lgt_stage.GetPrimAtPath(str(lgt_scope_path))
    if not scope_prim.IsValid():
        return

    scope_xf = UsdGeom.Xformable(scope_prim)
    if not scope_xf.GetOrderedXformOps():
        scope_xf.AddTransformOp().Set(inverse)

    lgt_stage.Save()
