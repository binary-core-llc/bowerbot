# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Attributes — reading and authoring prim attributes from JSON-shaped values."""

from __future__ import annotations

from pxr import Sdf, Sdr, Usd, UsdGeom, UsdShade

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
        out.append({
            "name": attr.GetName(),
            "type": str(attr.GetTypeName()),
            "value": usd_to_json(attr.Get()),
            "authored": attr.HasAuthoredValue(),
        })
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
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")

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

    attr = prim.GetAttribute(attribute_name)
    if not attr.IsValid():
        attr = _create_attribute_on_demand(
            prim, attribute_name, value, expected_type,
        )

    type_name = expected_type if expected_type is not None else attr.GetTypeName()
    converted = json_to_usd(value, type_name)
    try:
        attr.Set(converted)
    except (TypeError, RuntimeError):
        msg = (
            f"value {value!r} does not match {attribute_name}'s "
            f"declared type {type_name}."
        )
        raise ValueError(msg) from None


def _create_attribute_on_demand(
    prim: Usd.Prim,
    attribute_name: str,
    value: object,
    expected_type: Sdf.ValueTypeName | None = None,
) -> Usd.Attribute:
    """Create an attribute; xformOp:* routes through Xformable so xformOpOrder updates."""
    if attribute_name.startswith("xformOp:") and prim.IsA(UsdGeom.Xformable):
        op = _add_xform_op(UsdGeom.Xformable(prim), attribute_name)
        if op is not None:
            return op.GetAttr()

    if expected_type is not None:
        return prim.CreateAttribute(attribute_name, expected_type, custom=False)

    if attribute_name.startswith("inputs:") and prim.IsA(UsdShade.Shader):
        shader = UsdShade.Shader(prim)
        base_name = attribute_name[len("inputs:"):]
        sdr_type = _resolve_shader_input_type(shader, base_name)
        if sdr_type is not None:
            return shader.CreateInput(base_name, sdr_type).GetAttr()

    inferred = infer_sdf_type(value)
    return prim.CreateAttribute(attribute_name, inferred, custom=False)


def _add_xform_op(
    xformable: UsdGeom.Xformable, attribute_name: str,
) -> UsdGeom.XformOp | None:
    """Return the xform op for *attribute_name*, adding to xformOpOrder if missing."""
    suffix = attribute_name[len("xformOp:"):]
    base, _, namespace = suffix.partition(":")
    spec = _xform_op_spec(base)
    if spec is None:
        return None
    op_type, value_type = spec
    current_order = xformable.GetXformOpOrderAttr().Get() or ()
    if attribute_name in current_order:
        attr = xformable.GetPrim().CreateAttribute(
            attribute_name, value_type, custom=False,
        )
        return UsdGeom.XformOp(attr)
    return xformable.AddXformOp(op_type, opSuffix=namespace or "")


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


def _xform_op_spec(base: str) -> tuple[UsdGeom.XformOp.Type, Sdf.ValueTypeName] | None:
    """Op type and value type for an ``xformOp:<base>`` attribute, or ``None``."""
    match base:
        case "translate":
            return UsdGeom.XformOp.TypeTranslate, Sdf.ValueTypeNames.Double3
        case "rotateX":
            return UsdGeom.XformOp.TypeRotateX, Sdf.ValueTypeNames.Float
        case "rotateY":
            return UsdGeom.XformOp.TypeRotateY, Sdf.ValueTypeNames.Float
        case "rotateZ":
            return UsdGeom.XformOp.TypeRotateZ, Sdf.ValueTypeNames.Float
        case "rotateXYZ":
            return UsdGeom.XformOp.TypeRotateXYZ, Sdf.ValueTypeNames.Float3
        case "rotateXZY":
            return UsdGeom.XformOp.TypeRotateXZY, Sdf.ValueTypeNames.Float3
        case "rotateYXZ":
            return UsdGeom.XformOp.TypeRotateYXZ, Sdf.ValueTypeNames.Float3
        case "rotateYZX":
            return UsdGeom.XformOp.TypeRotateYZX, Sdf.ValueTypeNames.Float3
        case "rotateZXY":
            return UsdGeom.XformOp.TypeRotateZXY, Sdf.ValueTypeNames.Float3
        case "rotateZYX":
            return UsdGeom.XformOp.TypeRotateZYX, Sdf.ValueTypeNames.Float3
        case "scale":
            return UsdGeom.XformOp.TypeScale, Sdf.ValueTypeNames.Float3
        case "orient":
            return UsdGeom.XformOp.TypeOrient, Sdf.ValueTypeNames.Quatf
        case "transform":
            return UsdGeom.XformOp.TypeTransform, Sdf.ValueTypeNames.Matrix4d
    return None
