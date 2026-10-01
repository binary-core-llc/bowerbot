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

    properties: list[schemas.SchemaPropertySpec] = []
    for prop_name in UsdGeom.Camera.GetSchemaAttributeNames(False):
        row = usd.attributes.schema_attribute_row(prim_def, str(prop_name))
        if row is not None:
            properties.append(row)

    return schemas.CameraSchemaInfo(properties=properties)
