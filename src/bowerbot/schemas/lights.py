# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD light schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from bowerbot.schemas.schema_registry import SchemaPropertySpec


class LightType(StrEnum):
    """Supported USD light types."""

    DISTANT = "DistantLight"
    DOME = "DomeLight"
    SPHERE = "SphereLight"
    RECT = "RectLight"
    DISK = "DiskLight"
    CYLINDER = "CylinderLight"


class LightRules:
    """Where each light type may go, and which inputs are lengths."""

    # Lights that only make sense at scene level, never inside an asset.
    SCENE_ONLY_TYPES = frozenset({LightType.DOME, LightType.DISTANT})
    # UsdLux inputs measured in stage units (scaled by asset MPU at write time).
    SPATIAL_INPUTS = frozenset({"inputs:radius", "inputs:width", "inputs:height", "inputs:length"})


class LightTypeSchemaInfo(BaseModel):
    """Live introspection of a UsdLux concrete-prim schema."""

    light_type: str
    properties: list[SchemaPropertySpec] = []


class LightParams(BaseModel):
    """Parameters describing a USD light."""

    light_type: LightType
    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    texture: str | None = None
    light_link_includes: list[str] = []
    attributes: dict[str, Any] = {}
