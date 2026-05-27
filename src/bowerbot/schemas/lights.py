# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD light schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class LightType(StrEnum):
    """Supported USD light types."""

    DISTANT = "DistantLight"
    DOME = "DomeLight"
    SPHERE = "SphereLight"
    RECT = "RectLight"
    DISK = "DiskLight"
    CYLINDER = "CylinderLight"


class LightPropertySpec(BaseModel):
    """One UsdLux property discovered from the schema registry."""

    name: str
    kind: str
    type_name: str | None = None
    default: Any = None
    allowed_tokens: list[str] = []
    documentation: str = ""


class LightTypeSchemaInfo(BaseModel):
    """Live introspection of a UsdLux concrete-prim schema."""

    light_type: str
    properties: list[LightPropertySpec] = []


class LightParams(BaseModel):
    """Parameters describing a USD light."""

    light_type: LightType
    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    texture: str | None = None
    light_link_includes: list[str] = []
    attributes: dict[str, Any] = {}
