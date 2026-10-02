# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Attributes: read and author them, their declared types, what a schema declares."""

from __future__ import annotations

from collections.abc import Iterable

from pxr import Sdf
from pxr import Sdr
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade

from bowerbot import schemas
from bowerbot.utils import usd

# ── Reading and writing attributes ──


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
            "value": usd.values.usd_value_to_json(attr.Get()),
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
    """Author or clear an attribute opinion at the stage's edit target.

    *expected_type* overrides the type lookup.
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
            usd.namespace.prune_empty_overrides(layer, prim_path)
        return

    attr = prim.GetAttribute(attribute_name)
    if not attr.IsValid():
        attr = _create_attribute_on_demand(
            prim, attribute_name, value, expected_type,
        )

    allowed = attr.GetMetadata("allowedTokens")
    if allowed and value not in allowed:
        raise ValueError(
            f"{attribute_name} takes one of {sorted(allowed)}; got {value!r}.",
        )

    type_name = expected_type if expected_type is not None else attr.GetTypeName()
    converted = usd.values.json_to_usd_value(value, type_name)
    try:
        attr.Set(converted)
    except (TypeError, RuntimeError):
        msg = (
            f"value {value!r} does not match {attribute_name}'s "
            f"declared type {type_name}."
        )
        raise ValueError(msg) from None

# ── Applied API schemas ──


def drop_api_schema(prim_spec: Sdf.PrimSpec, api_name: str) -> bool:
    """Take *api_name* out of a spec's ``apiSchemas``; True if it was there."""
    if not prim_spec.HasInfo("apiSchemas"):
        return False
    list_op = prim_spec.GetInfo("apiSchemas")
    if list_op.isExplicit:
        explicit = list(list_op.explicitItems)
        if api_name not in explicit:
            return False
        explicit.remove(api_name)
        prim_spec.SetInfo("apiSchemas", Sdf.TokenListOp.CreateExplicit(explicit))
        return True

    prepended = list(list_op.prependedItems)
    appended = list(list_op.appendedItems)
    if api_name not in prepended and api_name not in appended:
        return False
    prepended = [name for name in prepended if name != api_name]
    appended = [name for name in appended if name != api_name]
    deleted = list(list_op.deletedItems)
    if prepended or appended or deleted:
        prim_spec.SetInfo(
            "apiSchemas", Sdf.TokenListOp.Create(prepended, appended, deleted),
        )
    else:
        prim_spec.ClearInfo("apiSchemas")
    return True

# ── Declared types and unknown names ──


def resolve_attribute_types(
    stage: Usd.Stage | None,
    overrides: dict[str, dict[str, object]],
) -> dict[str, dict[str, Sdf.ValueTypeName | None]]:
    """Look up each override attribute's declared type on a composed stage; None when unknown."""
    out: dict[str, dict[str, Sdf.ValueTypeName | None]] = {}
    for prim_path, attrs in overrides.items():
        resolved: dict[str, Sdf.ValueTypeName | None] = {}
        prim = stage.GetPrimAtPath(prim_path) if stage is not None else None
        for attr_name in attrs:
            type_name: Sdf.ValueTypeName | None = None
            if prim and prim.IsValid():
                attr = prim.GetAttribute(attr_name)
                if attr.IsValid():
                    type_name = attr.GetTypeName()
            resolved[attr_name] = type_name
        out[prim_path] = resolved
    return out


def refuse_unknown_attributes(
    stage: Usd.Stage,
    resolved_types: dict[str, dict[str, Sdf.ValueTypeName | None]],
) -> None:
    """Raise if any attribute in *resolved_types* does not exist on its target prim."""
    missing: list[tuple[str, str]] = []
    for prim_path, types in resolved_types.items():
        for attr_name, type_name in types.items():
            if type_name is None:
                missing.append((prim_path, attr_name))
    if not missing:
        return

    lines = ["Attribute(s) do not exist on the target prim(s):"]
    for prim_path, attr_name in missing:
        prim = stage.GetPrimAtPath(prim_path) if stage is not None else None
        available = sorted(
            a.GetName() for a in prim.GetAttributes()
            if a.GetName().startswith("inputs:")
        ) if prim and prim.IsValid() else []
        leaf = attr_name.split(":")[-1]
        similar = [a for a in available if leaf and leaf in a]
        if similar:
            hint = f" Did you mean: {', '.join(similar[:3])}?"
        elif available:
            hint = f" Available inputs on {prim_path}: {', '.join(available[:8])}"
        else:
            hint = ""
        lines.append(f"  '{attr_name}' on {prim_path}.{hint}")
    raise ValueError("\n".join(lines))

# ── What a schema declares ──


def schema_attribute_row(
    prim_def: Usd.PrimDefinition, prop_name: str, *, name: str | None = None,
) -> schemas.SchemaPropertySpec | None:
    """The listing row of a schema attribute, shown as *name*; None when it is not an attribute."""
    attr_spec = prim_def.GetSchemaAttributeSpec(prop_name)
    if attr_spec is None:
        return None
    return schemas.SchemaPropertySpec(
        name=name or prop_name,
        kind="attribute",
        type_name=str(attr_spec.typeName),
        default=usd.values.to_jsonable(attr_spec.default),
        allowed_tokens=[str(t) for t in (attr_spec.allowedTokens or [])],
        documentation=property_doc(prim_def, prop_name, attr_spec),
    )


def schema_property_row(
    prim_def: Usd.PrimDefinition, prop_name: str, *, name: str | None = None,
) -> schemas.SchemaPropertySpec | None:
    """The listing row of a schema attribute or relationship; None when it is neither."""
    row = schema_attribute_row(prim_def, prop_name, name=name)
    if row is not None:
        return row
    rel_spec = prim_def.GetSchemaRelationshipSpec(prop_name)
    if rel_spec is None:
        return None
    return schemas.SchemaPropertySpec(
        name=name or prop_name,
        kind="relationship",
        documentation=property_doc(prim_def, prop_name, rel_spec),
    )


def refuse_undeclared(
    schema_name: str, provided: Iterable[str], valid: set[str], kind: str,
) -> None:
    """Refuse the *provided* names that are not among the *valid* ones a schema declares."""
    unknown = sorted(n for n in provided if n not in valid)
    if unknown:
        raise ValueError(
            f"{schema_name} does not declare {kind}(s) {unknown}. "
            f"Allowed: {sorted(valid)}",
        )


def property_doc(
    prim_def: Usd.PrimDefinition, prop_name: str, spec: Sdf.PropertySpec,
) -> str:
    """Best-effort documentation lookup across USD versions."""
    getter = getattr(prim_def, "GetPropertyDocumentation", None)
    if callable(getter):
        return getter(prop_name) or ""
    return spec.GetInfo("documentation") or ""

# ── Helpers ──


def _create_attribute_on_demand(
    prim: Usd.Prim,
    attribute_name: str,
    value: object,
    expected_type: Sdf.ValueTypeName | None = None,
) -> Usd.Attribute:
    """Create an attribute; xformOp:* routes through Xformable so xformOpOrder updates."""
    if attribute_name.startswith("xformOp:") and prim.IsA(UsdGeom.Xformable):
        op = usd.transforms.add_xform_op(UsdGeom.Xformable(prim), attribute_name)
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

    inferred = usd.values.infer_sdf_type(value)
    return prim.CreateAttribute(attribute_name, inferred, custom=False)


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
