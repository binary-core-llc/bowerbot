# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset-folder light primitives — author lights into ``lgt.usda``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux

from bowerbot.schemas import (
    AssetScopeNames,
    ASWFLayerNames,
    LightParams,
    LightRules,
    LightType,
    LightTypeSchemaInfo,
)
from bowerbot.schemas.transforms import Vec3
from bowerbot.utils.core.asset_folder import (
    ensure_layer_scope,
    ensure_root_reference,
    ensure_side_layer,
    keep_root_over,
    remove_empty_layer,
    resolve_default_prim_name,
    unit_factor,
)
from bowerbot.utils.core.attributes import set_prim_attribute
from bowerbot.utils.core.overrides import clear_orphan_variant_overs
from bowerbot.utils.core.schema_registry import schema_class, schema_properties
from bowerbot.utils.core.transforms import (
    read_translate_rotate,
    update_rotate_op,
    update_translate_op,
)
from bowerbot.utils.core.values import coerce_number
from bowerbot.utils.variants.asset import remove_variants_layer_if_empty

logger = logging.getLogger(__name__)



def list_light_type_properties(light_type: LightType) -> LightTypeSchemaInfo:
    """Live schema-registry view of every input the light type declares."""
    prim_def = Usd.SchemaRegistry().FindConcretePrimDefinition(light_type.value)
    if prim_def is None:
        raise ValueError(
            f"USD schema registry does not know {light_type.value}. "
            "USD build is missing UsdLux.",
        )
    names = [n for n in prim_def.GetPropertyNames() if n.startswith("inputs:")]
    return LightTypeSchemaInfo(
        light_type=light_type.value,
        properties=schema_properties(prim_def, names),
    )


def refuse_unknown_light_attributes(light_type: LightType, attributes: dict[str, Any]) -> None:
    """Raise if any attribute name is not a property the light type declares."""
    prim_def = Usd.SchemaRegistry().FindConcretePrimDefinition(light_type.value)
    valid = set(prim_def.GetPropertyNames()) if prim_def is not None else set()
    unknown = sorted(name for name in attributes if name not in valid)
    if unknown:
        msg = (
            f"Unknown {light_type.value} input(s) {unknown}. "
            "Call list_light_type_properties for the valid names."
        )
        raise ValueError(msg)


def scale_spatial_attributes(
    attributes: dict[str, Any], factor: float,
) -> dict[str, Any]:
    """Return *attributes* with spatial UsdLux inputs scaled by *factor*."""
    if factor == 1.0:
        return dict(attributes)
    return {
        name: (
            coerce_number(value, f"spatial light input '{name}'") * factor
            if name in LightRules.SPATIAL_INPUTS else value
        )
        for name, value in attributes.items()
    }


def spatial_defaults(
    light_type: LightType, given: dict[str, Any], factor: float,
) -> dict[str, Any]:
    """The light type's length inputs *given* leaves out, as USD's fallbacks read in meters.

    USD's fallbacks (radius 0.5, width 1 ...) carry no unit, so in a layer whose
    unit isn't the meter an unset size shrinks or grows with it: a 5 mm bulb in
    a centimeter scene, and (lights not being normalized) 10,000x less light.
    *factor* converts meters into the layer's units; at 1 nothing is added.
    """
    if factor == 1.0:
        return {}
    prim_def = Usd.SchemaRegistry().FindConcretePrimDefinition(light_type.value)
    defaults: dict[str, Any] = {}
    for name in sorted(LightRules.SPATIAL_INPUTS - set(given)):
        attr_def = prim_def.GetAttributeDefinition(name) if prim_def is not None else None
        fallback = attr_def.GetFallbackValue() if attr_def else None
        if fallback is not None:
            defaults[name] = float(fallback) * factor
    return defaults


def create_light(stage: Usd.Stage, prim_path: str, light: LightParams) -> None:
    """Create a USD light prim in *stage* at *prim_path*.

    Sizes the caller leaves out are USD's defaults in meters, in scene units.
    """
    light_cls = schema_class(light.light_type)
    light_prim = light_cls.Define(stage, prim_path).GetPrim()

    factor = 1.0 / UsdGeom.GetStageMetersPerUnit(stage)
    write_light_attributes(stage, prim_path, {
        **spatial_defaults(light.light_type, light.attributes, factor), **light.attributes,
    })
    if light.texture is not None:
        tex_attr = light_prim.GetAttribute("inputs:texture:file")
        if tex_attr:
            tex_attr.Set(Sdf.AssetPath(light.texture))
    apply_light_link(light_prim, light.light_link_includes)

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
    translate: tuple[float, float, float] | None = None,
    rotate: tuple[float, float, float] | None = None,
    texture: str | None = None,
) -> None:
    """Update an existing scene-level light's xform / HDRI texture."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)

    if texture is not None:
        tex_attr = prim.GetAttribute("inputs:texture:file")
        if tex_attr:
            tex_attr.Set(Sdf.AssetPath(texture))

    if translate is not None:
        update_translate_op(prim, Gf.Vec3d(*translate))
    if rotate is not None:
        update_rotate_op(prim, Gf.Vec3f(*rotate))


def write_light_attributes(
    stage: Usd.Stage, prim_path: str, attributes: dict[str, Any],
) -> None:
    """Write a UsdLux ``inputs:*`` dict onto an existing light prim."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")
    for name, value in attributes.items():
        attr = prim.GetAttribute(name)
        if not attr:
            continue
        set_prim_attribute(
            stage, prim_path, name, value, expected_type=attr.GetTypeName(),
        )


def apply_light_link(light_prim: Usd.Prim, includes: list[str]) -> None:
    """Author the UsdLux light:link collection only when targets are provided."""
    if not includes:
        return
    binding = UsdLux.LightAPI(light_prim).GetLightLinkCollectionAPI()
    binding.CreateIncludesRel().SetTargets([Sdf.Path(p) for p in includes])
    binding.CreateIncludeRootAttr(False)


def require_light(stage: Usd.Stage, prim_path: str) -> Usd.Prim:
    """Return the UsdLux light at *prim_path* or raise."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")
    if not prim.HasAPI(UsdLux.LightAPI):
        msg = (
            f"{prim_path} is not a light ({prim.GetTypeName() or 'a typeless prim'}). "
            "To remove a group or any other prim, use remove_prim."
        )
        raise ValueError(msg)
    return prim


def format_light_prim(
    prim: Usd.Prim, position: dict[str, float] | None,
) -> dict[str, Any]:
    """Format a light prim for ``list_prims``."""
    data: dict[str, Any] = {
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


def add_light_to_folder(
    asset_dir: Path,
    light_name: str,
    light: LightParams,
) -> str:
    """Add a light to *asset_dir*'s ``lgt.usda`` and return its prim path."""
    lgt_path = ensure_side_layer(asset_dir, ASWFLayerNames.LGT)
    default_prim_name = resolve_default_prim_name(asset_dir)
    lgt_layer = Sdf.Layer.FindOrOpen(str(lgt_path))

    lgt_scope_path = Sdf.Path(f"/{default_prim_name}/{AssetScopeNames.LIGHTS}")
    ensure_layer_scope(lgt_layer, default_prim_name, AssetScopeNames.LIGHTS, "Xform")
    lgt_layer.Save()

    _apply_inverse_transform(asset_dir, lgt_path, lgt_scope_path)

    stage = Usd.Stage.Open(str(lgt_path))
    if stage is None:
        msg = f"Cannot open lgt layer: {lgt_path}"
        raise RuntimeError(msg)

    light_prim_path = f"/{default_prim_name}/{AssetScopeNames.LIGHTS}/{light_name}"
    light_cls = schema_class(light.light_type)

    light_prim = light_cls.Define(stage, light_prim_path).GetPrim()
    factor = unit_factor(asset_dir)

    write_light_attributes(stage, light_prim_path, {
        **spatial_defaults(light.light_type, light.attributes, factor),
        **scale_spatial_attributes(light.attributes, factor),
    })
    if light.texture is not None:
        tex_attr = light_prim.GetAttribute("inputs:texture:file")
        if tex_attr:
            tex_attr.Set(Sdf.AssetPath(light.texture))
    apply_light_link(light_prim, light.light_link_includes)

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

    keep_root_over(stage.GetRootLayer())
    stage.Save()
    ensure_root_reference(asset_dir, ASWFLayerNames.LGT)

    logger.info(
        "Added light %s (%s) to %s",
        light_name, light.light_type.value, asset_dir.name,
    )
    return light_prim_path


def update_light_in_folder(
    asset_dir: Path,
    light_name: str,
    *,
    translate: tuple[float, float, float] | None = None,
    rotate: tuple[float, float, float] | None = None,
    texture: str | None = None,
) -> None:
    """Update a light's xform / HDRI texture in *asset_dir*'s ``lgt.usda``."""
    stage, prim = _open_folder_light(asset_dir, light_name)

    if texture is not None:
        tex_attr = prim.GetAttribute("inputs:texture:file")
        if tex_attr:
            tex_attr.Set(Sdf.AssetPath(texture))

    factor = unit_factor(asset_dir)
    if translate is not None:
        update_translate_op(
            prim,
            Gf.Vec3d(
                translate[0] * factor,
                translate[1] * factor,
                translate[2] * factor,
            ),
        )
    if rotate is not None:
        update_rotate_op(prim, Gf.Vec3f(*rotate))

    stage.Save()
    logger.info(
        "Updated light %s in %s/%s",
        light_name, asset_dir.name, ASWFLayerNames.LGT,
    )


def light_xform_in_folder(asset_dir: Path, light_name: str) -> tuple[Vec3, Vec3]:
    """Return a folder light's ``(translate, rotate)``: asset-local meters and degrees."""
    _, prim = _open_folder_light(asset_dir, light_name)
    translate, rotate = read_translate_rotate(prim)
    factor = unit_factor(asset_dir)
    tx, ty, tz = (v / factor for v in translate)
    return (tx, ty, tz), rotate


def remove_light_from_folder(asset_dir: Path, light_name: str) -> bool:
    """Remove *light_name* from *asset_dir*'s ``lgt.usda``.

    Deletes the layer entirely when no lights remain. Returns False when
    ``lgt.usda`` holds no light of that name.
    """
    lgt_path = asset_dir / ASWFLayerNames.LGT
    if not lgt_path.exists():
        return False

    default_prim_name = resolve_default_prim_name(asset_dir)
    light_prim_path = Sdf.Path(f"/{default_prim_name}/{AssetScopeNames.LIGHTS}/{light_name}")

    lgt_layer = Sdf.Layer.FindOrOpen(str(lgt_path))
    if lgt_layer is None or not lgt_layer.GetPrimAtPath(light_prim_path):
        return False

    edit = Sdf.BatchNamespaceEdit()
    edit.Add(light_prim_path, Sdf.Path.emptyPath)
    lgt_layer.Apply(edit)
    lgt_layer.Save()

    variants_path = asset_dir / ASWFLayerNames.VARIANTS
    if variants_path.exists():
        variants_layer = Sdf.Layer.FindOrOpen(str(variants_path))
        if variants_layer is not None:
            clear_orphan_variant_overs(variants_layer, str(light_prim_path))
        remove_variants_layer_if_empty(asset_dir)

    remove_empty_layer(
        lgt_path, asset_dir, lambda p: p.HasAPI(UsdLux.LightAPI),
    )
    return True


# ── Internal helpers ──


def _open_folder_light(asset_dir: Path, light_name: str) -> tuple[Usd.Stage, Usd.Prim]:
    """Open *asset_dir*'s ``lgt.usda`` and return it with the light prim *light_name*."""
    lgt_path = asset_dir / ASWFLayerNames.LGT
    if not lgt_path.exists():
        msg = f"No lights authored in {asset_dir.name}/{ASWFLayerNames.LGT}"
        raise ValueError(msg)

    default_prim_name = resolve_default_prim_name(asset_dir)
    light_prim_path = f"/{default_prim_name}/{AssetScopeNames.LIGHTS}/{light_name}"

    stage = Usd.Stage.Open(str(lgt_path))
    if stage is None:
        msg = f"Cannot open lgt layer: {lgt_path}"
        raise RuntimeError(msg)

    prim = stage.GetPrimAtPath(light_prim_path)
    if not prim.IsValid():
        msg = (
            f"Light '{light_name}' not found in "
            f"{asset_dir.name}/{ASWFLayerNames.LGT}"
        )
        raise ValueError(msg)
    return stage, prim


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
