# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD camera schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from bowerbot.schemas import attributes


class CameraSchemaInfo(BaseModel):
    """Live introspection of the UsdGeom Camera prim schema."""

    properties: list[attributes.SchemaPropertySpec] = []


class CameraParams(BaseModel):
    """Parameters describing a scene-level USD camera."""

    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    attributes: dict[str, Any] = {}
