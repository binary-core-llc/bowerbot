# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD camera schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

DEFAULT_CLIPPING_RANGE_METERS = (0.01, 100_000.0)


class CameraPropertySpec(BaseModel):
    """One Camera property discovered from the schema registry."""

    name: str
    kind: str
    type_name: str | None = None
    default: Any = None
    allowed_tokens: list[str] = []
    documentation: str = ""


class CameraSchemaInfo(BaseModel):
    """Live introspection of the UsdGeom Camera prim schema."""

    properties: list[CameraPropertySpec] = []


class CameraParams(BaseModel):
    """Parameters describing a scene-level USD camera."""

    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    attributes: dict[str, Any] = {}
