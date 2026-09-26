# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Attributes — reading and authoring prim attributes from JSON-shaped values."""

from __future__ import annotations

from typing import Any

from pxr import Sdf, Sdr, Usd, UsdGeom, UsdShade

from bowerbot.schemas import MaterialXShaders, PreviewSurfaceShader
from bowerbot.utils.core.overrides import prune_empty_overrides
from bowerbot.utils.core.values import infer_sdf_type, json_to_usd, usd_to_json


def list_prim_attributes(
    stage: Usd.Stage, prim_path: str,
) -> list[dict[str, object]]:
    """Return every attribute on the prim with type, current value, authored flag."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")

    out: list[dict[str, object]] = []
    for attr in prim.GetAttributes():
        entry: dict[str, object] = {
            "name": attr.GetName(),
            "type": str(attr.GetTypeName()),
            "value": usd_to_json(attr.Get()),
            "authored": attr.HasAuthoredValue(),
        }
        allowed = attr.GetMetadata("allowedTokens")
        if allowed:
            entry["allowed_tokens"] = [str(t) for t in allowed]
        out.append(entry)
    return out


def set_prim_attribute(
    stage: Usd.Stage,
    prim_path: str,
    attribute_name: str,
    value: object,
    *,
    expected_type: Sdf.ValueTypeName | None = None,
) -> None:
    """Author or clear an attribute opinion at the stage's current edit target.

    When *expected_type* is provided it overrides value-shape inference and
    the schema-registry lookup; callers that know the declared type from a
    separate composition (e.g. variant body authoring against an asset's
    composed stage) should pass it to avoid the wrong type being authored.
    """
    prim = _require_prim(stage, prim_path)

    if value is None:
        layer = stage.GetEditTarget().GetLayer()
        prim_spec = layer.GetPrimAtPath(prim_path)
        if prim_spec is None:
            return
        attr_spec = prim_spec.attributes.get(attribute_name)
        if attr_spec is not None:
            prim_spec.RemoveProperty(attr_spec)
            prune_empty_overrides(layer, prim_path)
        return

    attr, new_type, type_name, converted = _typed_value(
        prim, attribute_name, value, expected_type,
    )
    if new_type is not None:
        attr = _create_attribute(prim, attribute_name, new_type)
    try:
        attr.Set(converted)
    except (TypeError, RuntimeError):
        msg = (
            f"value {value!r} does not match {attribute_name}'s "
            f"declared type {type_name}."
        )
        raise ValueError(msg) from None


def attribute_type(
    stage: Usd.Stage, prim_path: str, attribute_name: str,
) -> Sdf.ValueTypeName | None:
    """The type *attribute_name* has on the prim, or would get from its schema; else ``None``."""
    prim = _require_prim(stage, prim_path)
    attr = prim.GetAttribute(attribute_name)
    if attr.IsValid():
        return attr.GetTypeName()
    if attribute_name.startswith("inputs:") and prim.IsA(UsdShade.Shader):
        return _resolve_shader_input_type(
            UsdShade.Shader(prim), attribute_name[len("inputs:"):],
        )
    return None


def check_attribute_value(
    stage: Usd.Stage, prim_path: str, attribute_name: str, value: object,
) -> None:
    """Raise ``ValueError`` if :func:`set_prim_attribute` would refuse *value*; author nothing."""
    prim = _require_prim(stage, prim_path)
    if value is not None:
        _typed_value(prim, attribute_name, value, None)


def twin_shader_input(
    stage: Usd.Stage, prim_path: str, attribute_name: str,
) -> tuple[str, str] | None:
    """The same value's input on the other network of a BowerBot hybrid material.

    *prim_path* is the material's ``standard_surface`` or ``preview_surface``
    shader; ``None`` when it isn't, or when the input has no twin.
    """
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid() or not prim.IsA(UsdShade.Shader):
        return None
    material = prim.GetParent()
    if not material.IsA(UsdShade.Material):
        return None
    name = attribute_name.removeprefix("inputs:")
    if name == attribute_name:
        return None
    to_preview = MaterialXShaders.PREVIEW_TWIN_INPUTS
    to_standard = {preview: standard for standard, preview in to_preview.items()}
    shader_id = UsdShade.Shader(prim).GetIdAttr().Get()
    if shader_id == MaterialXShaders.STANDARD_SURFACE and name in to_preview:
        twin = material.GetChild(PreviewSurfaceShader.SURFACE_PRIM)
        twin_id, twin_name = PreviewSurfaceShader.SURFACE_ID, to_preview[name]
    elif shader_id == PreviewSurfaceShader.SURFACE_ID and name in to_standard:
        twin = material.GetChild(MaterialXShaders.STANDARD_SURFACE_PRIM)
        twin_id, twin_name = MaterialXShaders.STANDARD_SURFACE, to_standard[name]
    else:
        return None
    if not twin.IsA(UsdShade.Shader) or UsdShade.Shader(twin).GetIdAttr().Get() != twin_id:
        return None
    return str(twin.GetPath()), f"inputs:{twin_name}"


def _require_prim(stage: Usd.Stage, prim_path: str) -> Usd.Prim:
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")
    return prim


def _typed_value(
    prim: Usd.Prim,
    attribute_name: str,
    value: object,
    expected_type: Sdf.ValueTypeName | None,
) -> tuple[Usd.Attribute, Sdf.ValueTypeName | None, Sdf.ValueTypeName, Any]:
    """The attribute, the type to create it with (if missing), its type and *value* converted.

    Converting before anything is created means a bad value leaves the prim untouched.
    """
    attr = prim.GetAttribute(attribute_name)
    new_type = (
        None if attr.IsValid()
        else _new_attribute_type(prim, attribute_name, value, expected_type)
    )
    if expected_type is not None:
        type_name = expected_type
    elif new_type is not None:
        type_name = new_type
    else:
        type_name = attr.GetTypeName()
    converted = json_to_usd(value, type_name)
    if attr.IsValid():
        _require_allowed_tokens(attr, converted)
    return attr, new_type, type_name, converted


def _require_allowed_tokens(attr: Usd.Attribute, value: Any) -> None:
    """Refuse a token (or token array) outside the attribute's schema ``allowedTokens``."""
    allowed = attr.GetMetadata("allowedTokens")
    type_name = attr.GetTypeName()
    if not allowed or type_name not in (Sdf.ValueTypeNames.Token, Sdf.ValueTypeNames.TokenArray):
        return
    values = [value] if type_name == Sdf.ValueTypeNames.Token else list(value)
    bad = [v for v in values if v not in allowed]
    if bad:
        msg = f"{attr.GetName()} takes one of {list(allowed)}; got {value!r}."
        raise ValueError(msg)


def _new_attribute_type(
    prim: Usd.Prim,
    attribute_name: str,
    value: object,
    expected_type: Sdf.ValueTypeName | None,
) -> Sdf.ValueTypeName:
    """The type a missing attribute is created with: xform op, expected, shader input, inferred."""
    if attribute_name.startswith("xformOp:") and prim.IsA(UsdGeom.Xformable):
        spec = _xform_op_spec(attribute_name[len("xformOp:"):].partition(":")[0])
        if spec is not None:
            return spec[2]

    if expected_type is not None:
        return expected_type

    if attribute_name.startswith("inputs:") and prim.IsA(UsdShade.Shader):
        base_name = attribute_name[len("inputs:"):]
        sdr_type = _resolve_shader_input_type(UsdShade.Shader(prim), base_name)
        if sdr_type is not None:
            return sdr_type

    return infer_sdf_type(value)


def _create_attribute(
    prim: Usd.Prim, attribute_name: str, type_name: Sdf.ValueTypeName,
) -> Usd.Attribute:
    """Create a missing attribute; xformOp:* goes through Xformable so xformOpOrder updates."""
    if attribute_name.startswith("xformOp:") and prim.IsA(UsdGeom.Xformable):
        op = _add_xform_op(UsdGeom.Xformable(prim), attribute_name)
        if op is not None:
            return op.GetAttr()
    return prim.CreateAttribute(attribute_name, type_name, custom=False)


def _add_xform_op(
    xformable: UsdGeom.Xformable, attribute_name: str,
) -> UsdGeom.XformOp | None:
    """Return the xform op for *attribute_name*, adding to xformOpOrder if missing."""
    suffix = attribute_name[len("xformOp:"):]
    base, _, namespace = suffix.partition(":")
    spec = _xform_op_spec(base)
    if spec is None:
        return None
    op_type, precision, value_type = spec
    current_order = xformable.GetXformOpOrderAttr().Get() or ()
    if attribute_name in current_order:
        attr = xformable.GetPrim().CreateAttribute(
            attribute_name, value_type, custom=False,
        )
        return UsdGeom.XformOp(attr)
    return xformable.AddXformOp(op_type, precision, opSuffix=namespace or "")


def _resolve_shader_input_type(
    shader: UsdShade.Shader, base_name: str,
) -> Sdf.ValueTypeName | None:
    """Look up a shader input's declared type via the Sdr registry."""
    id_attr = shader.GetIdAttr()
    info_id = id_attr.Get() if id_attr else None
    if not info_id:
        return None
    node = Sdr.Registry().GetShaderNodeByIdentifier(info_id)
    if node is None:
        return None
    sdr_input = node.GetShaderInput(base_name)
    if sdr_input is None:
        return None
    return sdr_input.GetTypeAsSdfType().GetSdfType()


def _xform_op_spec(
    base: str,
) -> tuple[UsdGeom.XformOp.Type, UsdGeom.XformOp.Precision, Sdf.ValueTypeName] | None:
    """Op type, precision and value type for an ``xformOp:<base>`` attribute, or ``None``.

    Precisions are USD's per-op defaults, the ones BowerBot authors everywhere
    else: double for translate and transform, float for rotate, scale and orient.
    """
    op, types = UsdGeom.XformOp, Sdf.ValueTypeNames
    match base:
        case "translate":
            return op.TypeTranslate, op.PrecisionDouble, types.Double3
        case "rotateX":
            return op.TypeRotateX, op.PrecisionFloat, types.Float
        case "rotateY":
            return op.TypeRotateY, op.PrecisionFloat, types.Float
        case "rotateZ":
            return op.TypeRotateZ, op.PrecisionFloat, types.Float
        case "rotateXYZ":
            return op.TypeRotateXYZ, op.PrecisionFloat, types.Float3
        case "rotateXZY":
            return op.TypeRotateXZY, op.PrecisionFloat, types.Float3
        case "rotateYXZ":
            return op.TypeRotateYXZ, op.PrecisionFloat, types.Float3
        case "rotateYZX":
            return op.TypeRotateYZX, op.PrecisionFloat, types.Float3
        case "rotateZXY":
            return op.TypeRotateZXY, op.PrecisionFloat, types.Float3
        case "rotateZYX":
            return op.TypeRotateZYX, op.PrecisionFloat, types.Float3
        case "scale":
            return op.TypeScale, op.PrecisionFloat, types.Float3
        case "orient":
            return op.TypeOrient, op.PrecisionFloat, types.Quatf
        case "transform":
            return op.TypeTransform, op.PrecisionDouble, types.Matrix4d
    return None
