# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Schema registry — the properties a USD prim or API schema declares."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from pxr import Sdf, Usd

from bowerbot.schemas import SchemaPropertySpec
from bowerbot.utils.core.values import usd_to_json


def schema_properties(
    prim_def: Usd.PrimDefinition,
    names: Iterable[str],
    *,
    rename: Callable[[str], str] | None = None,
) -> list[SchemaPropertySpec]:
    """Every attribute and relationship among *names* that *prim_def* declares."""
    properties: list[SchemaPropertySpec] = []
    for name in names:
        shown = rename(name) if rename is not None else name
        attr_spec = prim_def.GetSchemaAttributeSpec(name)
        if attr_spec is not None:
            properties.append(SchemaPropertySpec(
                name=shown,
                kind="attribute",
                type_name=str(attr_spec.typeName),
                default=usd_to_json(attr_spec.default),
                allowed_tokens=[str(t) for t in (attr_spec.allowedTokens or [])],
                documentation=property_doc(prim_def, name, attr_spec),
            ))
            continue
        rel_spec = prim_def.GetSchemaRelationshipSpec(name)
        if rel_spec is not None:
            properties.append(SchemaPropertySpec(
                name=shown,
                kind="relationship",
                documentation=property_doc(prim_def, name, rel_spec),
            ))
    return properties


def property_doc(
    prim_def: Usd.PrimDefinition, prop_name: str, spec: Sdf.PropertySpec,
) -> str:
    """Best-effort documentation lookup across USD versions."""
    getter = getattr(prim_def, "GetPropertyDocumentation", None)
    if callable(getter):
        return getter(prop_name) or ""
    return spec.GetInfo("documentation") or ""


