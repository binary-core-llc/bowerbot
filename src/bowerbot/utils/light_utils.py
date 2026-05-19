# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset-folder light primitives — author lights into ``lgt.usda``."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux

from bowerbot.schemas import ASWFLayerNames, LightParams
from bowerbot.utils.asset_folder_utils import (
    ensure_layer_scope,
    ensure_root_reference,
    find_root_file,
    remove_empty_layer,
    resolve_default_prim_name,
)
from bowerbot.utils.geometry_utils import unit_factor
from bowerbot.utils.stage_utils import LIGHT_CLASSES, clear_orphan_variant_overs
from bowerbot.utils.variant_utils import cleanup_if_empty

logger = logging.getLogger(__name__)

_LIGHT_EXTRA_ATTRS: dict[str, str] = {
    "angle": "inputs:angle",
    "texture": "inputs:texture:file",
    "radius": "inputs:radius",
    "width": "inputs:width",
    "height": "inputs:height",
    "length": "inputs:length",
}


def add_light_to_folder(
    asset_dir: Path,
    light_name: str,
    light: LightParams,
) -> str:
    """Add a light to *asset_dir*'s ``lgt.usda`` and return its prim path.

    Spatial inputs (translate, radius, width, height, length) are
    converted from meters to the asset's native units.
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


def remove_light_from_folder(asset_dir: Path, light_name: str) -> None:
    """Remove *light_name* from *asset_dir*'s ``lgt.usda``.

    Deletes the layer entirely when no lights remain.
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

    variants_path = asset_dir / ASWFLayerNames.VARIANTS
    if variants_path.exists():
        variants_layer = Sdf.Layer.FindOrOpen(str(variants_path))
        if variants_layer is not None:
            clear_orphan_variant_overs(variants_layer, str(light_prim_path))
        cleanup_if_empty(asset_dir)

    remove_empty_layer(
        lgt_path, asset_dir, lambda p: p.HasAPI(UsdLux.LightAPI),
    )


def list_lights_in_folder(asset_dir: Path) -> list[dict]:
    """List all lights declared in *asset_dir*'s ``lgt.usda``."""
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


def stage_asset_texture(asset_dir: Path, texture: str | None) -> str | None:
    """Copy an HDRI into the asset's ``maps/`` dir; return the ref path."""
    if not texture:
        return texture

    maps_dir = asset_dir / ASWFLayerNames.MAPS
    maps_dir.mkdir(exist_ok=True)
    tex_path = Path(texture)
    if tex_path.exists():
        dest = maps_dir / tex_path.name
        if not dest.exists():
            shutil.copy2(tex_path, dest)
        return f"./{ASWFLayerNames.MAPS}/{tex_path.name}"
    return texture


# ── Internal helpers ──


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


def _apply_inverse_transform(
    asset_dir: Path,
    lgt_path: Path,
    lgt_scope_path: Sdf.Path,
) -> None:
    """Cancel the geometry root transform on the lgt scope."""
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
