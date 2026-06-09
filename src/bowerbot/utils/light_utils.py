# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset-folder light primitives — author lights into ``lgt.usda``."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux

from bowerbot.schemas import (
    ASWFLayerNames,
    LightParams,
    LightPropertySpec,
    LightType,
    LightTypeSchemaInfo,
)
from bowerbot.utils.asset_folder_utils import (
    ensure_layer_scope,
    ensure_root_reference,
    find_root_file,
    remove_empty_layer,
    resolve_default_prim_name,
)
from bowerbot.utils.geometry_utils import unit_factor
from bowerbot.utils.stage_utils import (
    clear_orphan_variant_overs,
    set_prim_attribute,
    update_rotate_op,
    update_translate_op,
)
from bowerbot.utils.usd_schema_utils import property_doc, to_jsonable
from bowerbot.utils.variant_utils import cleanup_if_empty

LIGHT_CLASSES: dict[str, type] = {
    LightType.DISTANT: UsdLux.DistantLight,
    LightType.DOME: UsdLux.DomeLight,
    LightType.SPHERE: UsdLux.SphereLight,
    LightType.RECT: UsdLux.RectLight,
    LightType.DISK: UsdLux.DiskLight,
    LightType.CYLINDER: UsdLux.CylinderLight,
}

SCENE_ONLY_LIGHT_TYPES: frozenset[LightType] = frozenset({
    LightType.DOME,
    LightType.DISTANT,
})

logger = logging.getLogger(__name__)

# UsdLux inputs measured in stage units (scaled by asset MPU at write time).
SPATIAL_LIGHT_INPUTS: frozenset[str] = frozenset({
    "inputs:radius",
    "inputs:width",
    "inputs:height",
    "inputs:length",
})


def list_light_type_properties(light_type: LightType) -> LightTypeSchemaInfo:
    """Live schema-registry view of every input the light type declares."""
    prim_def = Usd.SchemaRegistry().FindConcretePrimDefinition(light_type.value)
    if prim_def is None:
        raise ValueError(
            f"USD schema registry does not know {light_type.value}. "
            "USD build is missing UsdLux.",
        )

    properties: list[LightPropertySpec] = []
    for prop_name in prim_def.GetPropertyNames():
        if not prop_name.startswith("inputs:"):
            continue
        attr_spec = prim_def.GetSchemaAttributeSpec(prop_name)
        if attr_spec is None:
            continue
        properties.append(LightPropertySpec(
            name=prop_name,
            kind="attribute",
            type_name=str(attr_spec.typeName),
            default=to_jsonable(attr_spec.default),
            allowed_tokens=[
                str(t) for t in (attr_spec.allowedTokens or [])
            ],
            documentation=property_doc(prim_def, prop_name, attr_spec),
        ))

    return LightTypeSchemaInfo(
        light_type=light_type.value,
        properties=properties,
    )


def scale_spatial_attributes(
    attributes: dict[str, Any], factor: float,
) -> dict[str, Any]:
    """Return *attributes* with spatial UsdLux inputs scaled by *factor*."""
    if factor == 1.0:
        return dict(attributes)
    return {
        name: (value * factor if name in SPATIAL_LIGHT_INPUTS else value)
        for name, value in attributes.items()
    }


def create_light(stage: Usd.Stage, prim_path: str, light: LightParams) -> None:
    """Create a USD light prim in *stage* at *prim_path*."""
    light_cls = LIGHT_CLASSES[light.light_type.value]
    light_prim = light_cls.Define(stage, prim_path).GetPrim()

    write_light_attributes(stage, prim_path, light.attributes)
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


def add_light_to_folder(
    asset_dir: Path,
    light_name: str,
    light: LightParams,
) -> str:
    """Add a light to *asset_dir*'s ``lgt.usda`` and return its prim path."""
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

    light_prim = light_cls.Define(stage, light_prim_path).GetPrim()
    factor = unit_factor(asset_dir)

    write_light_attributes(
        stage, light_prim_path,
        scale_spatial_attributes(light.attributes, factor),
    )
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
    lgt_path = asset_dir / ASWFLayerNames.LGT
    if not lgt_path.exists():
        msg = f"No lights authored in {asset_dir.name}/{ASWFLayerNames.LGT}"
        raise ValueError(msg)

    default_prim_name = resolve_default_prim_name(asset_dir)
    light_prim_path = f"/{default_prim_name}/lgt/{light_name}"

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
