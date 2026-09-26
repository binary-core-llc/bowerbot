# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD camera schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from bowerbot.schemas.schema_registry import SchemaPropertySpec


class CameraDefaults:
    """Values a camera gets when the request leaves them out."""

    CLIPPING_RANGE_METERS = (0.01, 100_000.0)


class CameraTuning:
    """Internal settings of camera aiming."""

    # Aim closer than this (cosine) to the up axis switches to the other up axis.
    UP_ALIGNED_DOT = 0.999


class CameraSchemaInfo(BaseModel):
    """Live introspection of the UsdGeom Camera prim schema."""

    properties: list[SchemaPropertySpec] = []


class CameraParams(BaseModel):
    """Parameters describing a scene-level USD camera."""

    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    attributes: dict[str, Any] = {}
