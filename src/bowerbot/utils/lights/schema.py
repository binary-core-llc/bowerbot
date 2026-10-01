# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Each light type's inputs, read from the live schema registry."""

from __future__ import annotations

from pxr import Usd

from bowerbot import schemas
from bowerbot.utils import usd


def list_type_properties(light_type: schemas.LightType) -> schemas.LightTypeSchemaInfo:
    """Live schema-registry view of every input the light type declares."""
    prim_def = Usd.SchemaRegistry().FindConcretePrimDefinition(light_type.value)
    if prim_def is None:
        raise ValueError(
            f"USD schema registry does not know {light_type.value}. "
            "USD build is missing UsdLux.",
        )

    properties: list[schemas.SchemaPropertySpec] = []
    for prop_name in prim_def.GetPropertyNames():
        if not prop_name.startswith("inputs:"):
            continue
        row = usd.attributes.schema_attribute_row(prim_def, prop_name)
        if row is not None:
            properties.append(row)

    return schemas.LightTypeSchemaInfo(
        light_type=light_type.value,
        properties=properties,
    )
