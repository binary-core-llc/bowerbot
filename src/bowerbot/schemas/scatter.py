# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter schemas — asset mixes, regions, distribution settings, and generated instances."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from bowerbot.schemas.surface import FloatArray, IntArray
from bowerbot.schemas.transforms import Vec3

MAX_SCATTER_INSTANCES = 1_000_000
MAX_SCATTER_PLACEMENTS = 10_000


class ScatterNamespace:
    """Canonical names BowerBot uses when authoring a scatter."""

    DEFAULT_GROUP = "Scatter"
    PROTOTYPES = "Prototypes"


class ScatterOutput(StrEnum):
    """How a scatter is written: one PointInstancer, or one placement per instance."""

    INSTANCER = "instancer"
    PLACEMENTS = "placements"


class ScatterArrangement(StrEnum):
    """How instances are distributed over the surfaces."""

    RANDOM = "random"
    ROWS = "rows"
    PILE = "pile"


class ScatterAlign(StrEnum):
    """Which way an instance's up axis points once it rests."""

    SURFACE = "surface"
    UP = "up"


class ScatterRegionFalloff(StrEnum):
    """Density fade from the centre of a circular region to its edge."""

    NONE = "none"
    LINEAR = "linear"
    SMOOTH = "smooth"


class ScatterPathFacing(StrEnum):
    """Which way instances placed along a path face."""

    TANGENT = "tangent"
    PATH = "path"
    CENTER = "center"
    OUTWARD = "outward"
    FIXED = "fixed"
    RANDOM = "random"


class ScatterPathSide(StrEnum):
    """Where instances sit relative to the path line."""

    CENTER = "center"
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"


class ScatterAssetOrder(StrEnum):
    """How assets are picked per instance when several are given."""

    RANDOM = "random"
    CYCLE = "cycle"


class ScatterDropAlign(StrEnum):
    """Whether drop_to_surface keeps rotation or tilts onto the surface."""

    KEEP = "keep"
    SURFACE = "surface"


class ScatterAsset(BaseModel):
    """One asset in a scatter mix."""

    asset: str
    weight: float = 1.0
    fix_root_prim: bool = False
    fix_root_transforms: bool = False


class ScatterRegion(BaseModel):
    """A plan-view area: a circle (``center`` + ``radius``) or a ``polygon``."""

    center: Vec3 | None = None
    radius: float | None = None
    falloff: ScatterRegionFalloff = ScatterRegionFalloff.NONE
    polygon: list[Vec3] | None = None


class ScatterPathCircle(BaseModel):
    """A closed circular path around ``center``."""

    center: Vec3
    radius: float
    start_angle_degrees: float = 0.0


class ScatterPoseParams(BaseModel):
    """How each scattered piece is oriented, sized and seated on the surface."""

    align: ScatterAlign = ScatterAlign.SURFACE
    random_yaw: bool = True
    tilt_jitter_degrees: float = 0.0
    scale_range: tuple[float, float] = (1.0, 1.0)
    embed: float = 0.0


class ScatterSurfaceParams(BaseModel):
    """Distribution settings for scattering over surfaces."""

    arrangement: ScatterArrangement = ScatterArrangement.RANDOM
    count: int | None = None
    density: float | None = None
    min_spacing: float | None = None
    variation: float = 0.0
    variation_scale: float | None = None
    region: ScatterRegion | None = None
    avoid_margin: float = 0.0
    max_slope_degrees: float = 60.0
    spacing: float | None = None
    row_spacing: float | None = None
    row_direction_degrees: float = 0.0
    jitter: float = 0.0
    repose_degrees: float = 35.0


class ScatterPathParams(BaseModel):
    """Distribution settings for placing along a polyline, circle, or curve."""

    points: list[Vec3] | None = None
    closed: bool = False
    circle: ScatterPathCircle | None = None
    curve_prim: str | None = None
    count: int | None = None
    spacing: float | None = None
    gap: float = 0.0
    start_offset: float = 0.0
    sides: ScatterPathSide = ScatterPathSide.CENTER
    offset: float = 0.0
    facing: ScatterPathFacing = ScatterPathFacing.TANGENT
    direction_degrees: float | None = None
    yaw_offset_degrees: float = 0.0
    follow_slope: bool = False
    asset_order: ScatterAssetOrder = ScatterAssetOrder.RANDOM


class ScatterPrototype(BaseModel):
    """A staged asset to instance: conformed bounds, base footprint, vertex sample."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    source: str
    scene_ref: str
    weight: float
    bounds_min: Vec3
    bounds_max: Vec3
    base_min: Vec3
    base_max: Vec3
    points: FloatArray


class ScatterInstanceSet(BaseModel):
    """Per-instance world transforms; orientations are (w, x, y, z) quaternions."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    proto_indices: IntArray
    positions: FloatArray
    orientations: FloatArray
    scales: FloatArray

    @property
    def count(self) -> int:
        return int(self.proto_indices.shape[0])
