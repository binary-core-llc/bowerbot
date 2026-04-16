# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD light schemas."""

from enum import StrEnum

from pydantic import BaseModel


class LightType(StrEnum):
    """Supported USD light types."""

    DISTANT = "DistantLight"
    DOME = "DomeLight"
    SPHERE = "SphereLight"
    RECT = "RectLight"
    DISK = "DiskLight"
    CYLINDER = "CylinderLight"


class LightParams(BaseModel):
    """Parameters describing a USD light.

    Contains only the light's own attributes. Placement context
    (scene prim path or asset folder + light name) is passed
    separately to the engine methods.
    """

    light_type: LightType
    intensity: float = 1000.0
    exposure: float = 0.0  # Power-of-2 multiplier on intensity (camera stops)
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # Type-specific (only relevant ones used per light type)
    angle: float | None = None   # DistantLight
    texture: str | None = None   # DomeLight HDRI path
    radius: float | None = None  # SphereLight, DiskLight, CylinderLight
    width: float | None = None   # RectLight
    height: float | None = None  # RectLight
    length: float | None = None  # CylinderLight
