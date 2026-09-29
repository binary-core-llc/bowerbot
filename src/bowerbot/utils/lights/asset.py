# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Lights in an asset folder's ``lgt.usda``: adding, updating and removing them."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Gf
from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdLux

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import lights
from bowerbot.utils import usd

logger = logging.getLogger(__name__)


def add(
    asset_dir: Path,
    light_name: str,
    light: schemas.LightParams,
) -> str:
    """Add a light to *asset_dir*'s ``lgt.usda`` and return its prim path."""
    lgt_path = asset_dir / constants.ASWFLayerNames.LGT
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)

    if lgt_path.exists():
        lgt_layer = Sdf.Layer.FindOrOpen(str(lgt_path))
    else:
        lgt_layer = Sdf.Layer.CreateNew(str(lgt_path))
        lgt_layer.defaultPrim = default_prim_name

    lgt_scope_path = Sdf.Path(f"/{default_prim_name}/lgt")
    authoring.asset_folder.ensure_layer_scope(lgt_layer, default_prim_name, "lgt", "Xform")
    lgt_layer.Save()

    _apply_inverse_transform(asset_dir, lgt_path, lgt_scope_path)

    stage = Usd.Stage.Open(str(lgt_path))
    if stage is None:
        msg = f"Cannot open lgt layer: {lgt_path}"
        raise RuntimeError(msg)

    light_prim_path = f"/{default_prim_name}/lgt/{light_name}"
    light_cls = constants.LightUsd.CLASSES.get(light.light_type.value)
    if light_cls is None:
        msg = f"Unknown light type: {light.light_type.value}"
        raise ValueError(msg)

    light_prim = light_cls.Define(stage, light_prim_path).GetPrim()
    factor = authoring.asset_folder.unit_factor(asset_dir)

    lights.prim.write_attributes(
        stage, light_prim_path,
        scale_spatial_attributes(light.attributes, factor),
    )
    if light.texture is not None:
        tex_attr = light_prim.GetAttribute("inputs:texture:file")
        if tex_attr:
            tex_attr.Set(Sdf.AssetPath(light.texture))
    lights.prim.apply_light_link(light_prim, light.light_link_includes)

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
    authoring.asset_folder.ensure_root_reference(asset_dir, constants.ASWFLayerNames.LGT)

    logger.info(
        "Added light %s (%s) to %s",
        light_name, light.light_type.value, asset_dir.name,
    )
    return light_prim_path


def update(
    asset_dir: Path,
    light_name: str,
    *,
    translate: tuple[float, float, float] | None = None,
    rotate: tuple[float, float, float] | None = None,
    texture: str | None = None,
) -> None:
    """Update a light's xform / HDRI texture in *asset_dir*'s ``lgt.usda``."""
    lgt_path = asset_dir / constants.ASWFLayerNames.LGT
    if not lgt_path.exists():
        msg = f"No lights authored in {asset_dir.name}/{constants.ASWFLayerNames.LGT}"
        raise ValueError(msg)

    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    light_prim_path = f"/{default_prim_name}/lgt/{light_name}"

    stage = Usd.Stage.Open(str(lgt_path))
    if stage is None:
        msg = f"Cannot open lgt layer: {lgt_path}"
        raise RuntimeError(msg)

    prim = stage.GetPrimAtPath(light_prim_path)
    if not prim.IsValid():
        msg = (
            f"Light '{light_name}' not found in "
            f"{asset_dir.name}/{constants.ASWFLayerNames.LGT}"
        )
        raise ValueError(msg)

    if texture is not None:
        tex_attr = prim.GetAttribute("inputs:texture:file")
        if tex_attr:
            tex_attr.Set(Sdf.AssetPath(texture))

    factor = authoring.asset_folder.unit_factor(asset_dir)
    if translate is not None:
        usd.transforms.update_translate_op(
            prim,
            Gf.Vec3d(
                translate[0] * factor,
                translate[1] * factor,
                translate[2] * factor,
            ),
        )
    if rotate is not None:
        usd.transforms.update_rotate_op(prim, Gf.Vec3f(*rotate))

    stage.Save()
    logger.info(
        "Updated light %s in %s/%s",
        light_name, asset_dir.name, constants.ASWFLayerNames.LGT,
    )


def remove(asset_dir: Path, light_name: str) -> None:
    """Remove *light_name* from *asset_dir*'s ``lgt.usda``.

    Deletes the layer entirely when no lights remain.
    """
    lgt_path = asset_dir / constants.ASWFLayerNames.LGT
    if not lgt_path.exists():
        return

    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    light_prim_path = Sdf.Path(f"/{default_prim_name}/lgt/{light_name}")

    lgt_layer = Sdf.Layer.FindOrOpen(str(lgt_path))
    if lgt_layer is None:
        return

    if lgt_layer.GetPrimAtPath(light_prim_path):
        edit = Sdf.BatchNamespaceEdit()
        edit.Add(light_prim_path, Sdf.Path.emptyPath)
        lgt_layer.Apply(edit)
        lgt_layer.Save()

    variants_path = asset_dir / constants.ASWFLayerNames.VARIANTS
    if variants_path.exists():
        variants_layer = Sdf.Layer.FindOrOpen(str(variants_path))
        if variants_layer is not None:
            usd.namespace.clear_orphan_variant_overs(variants_layer, str(light_prim_path))
        authoring.asset_variants.cleanup_if_empty(asset_dir)

    authoring.asset_folder.remove_empty_layer(
        lgt_path, asset_dir, lambda p: p.HasAPI(UsdLux.LightAPI),
    )


def scale_spatial_attributes(
    attributes: dict[str, Any], factor: float,
) -> dict[str, Any]:
    """Return *attributes* with spatial UsdLux inputs scaled by *factor*."""
    if factor == 1.0:
        return dict(attributes)
    return {
        name: (
            usd.values.coerce_number(value, f"spatial light input '{name}'") * factor
            if name in constants.LightRules.SPATIAL_INPUTS else value
        )
        for name, value in attributes.items()
    }


# ── Helpers ──


def _apply_inverse_transform(
    asset_dir: Path,
    lgt_path: Path,
    lgt_scope_path: Sdf.Path,
) -> None:
    """Cancel the geometry root transform on the lgt scope."""
    geo_path = asset_dir / constants.ASWFLayerNames.GEO
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
