# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Transform and placement schemas shared across scene + asset operations."""

from enum import StrEnum

from pydantic import BaseModel

from bowerbot.schemas.assets import AssetMetadata


class TransformParams(BaseModel):
    """A prim transform (translate + rotate + scale).

    Reusable across any operation that places a prim — nested assets,
    cameras, or other scene/asset objects.
    """

    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)


class PositionMode(StrEnum):
    """Coordinate system used when placing a prim inside an asset.

    * ``absolute`` — translate values are world-space coordinates (as
      returned by ``list_scene`` / ``list_prim_children``). Converted
      into the asset's internal coordinate frame automatically.
    * ``bounds_offset`` — translate values are offsets from the asset's
      bounding box surfaces (center for X/Z, top/bottom for Y). Use
      for "above/below/next to" placements like a bulb above a lamp.
    """

    ABSOLUTE = "absolute"
    BOUNDS_OFFSET = "bounds_offset"


class LayoutPattern(StrEnum):
    """Parametric placement pattern for a batch layout entry."""

    GRID = "grid"
    LINEAR = "linear"


class SceneObject(BaseModel):
    """An object placed in the scene graph."""

    prim_path: str  # e.g. "/Scene/Furniture/Table_01"
    asset: AssetMetadata
    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
