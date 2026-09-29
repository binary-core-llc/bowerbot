# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The Camera schema's attributes, read from the live schema registry."""

from __future__ import annotations

from pxr import Usd
from pxr import UsdGeom

from bowerbot import schemas
from bowerbot.utils import usd


def list_properties() -> schemas.CameraSchemaInfo:
    """Live schema-registry view of every attribute the Camera prim declares."""
    prim_def = Usd.SchemaRegistry().FindConcretePrimDefinition("Camera")
    if prim_def is None:
        raise ValueError(
            "USD schema registry does not know Camera. "
            "USD build is missing UsdGeom.",
        )

    properties: list[schemas.CameraPropertySpec] = []
    for prop_name in UsdGeom.Camera.GetSchemaAttributeNames(False):
        name = str(prop_name)
        attr_spec = prim_def.GetSchemaAttributeSpec(name)
        if attr_spec is None:
            continue
        properties.append(schemas.CameraPropertySpec(
            name=name,
            kind="attribute",
            type_name=str(attr_spec.typeName),
            default=usd.values.to_jsonable(attr_spec.default),
            allowed_tokens=[
                str(t) for t in (attr_spec.allowedTokens or [])
            ],
            documentation=usd.attributes.property_doc(prim_def, name, attr_spec),
        ))

    return schemas.CameraSchemaInfo(properties=properties)
