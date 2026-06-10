# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Layout schemas — the batch-placement contract consumed by place_layout."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bowerbot.schemas.transforms import LayoutPattern

LAYOUT_FILE_VERSION = 1
MAX_LAYOUT_PLACEMENTS = 100_000

Vec3 = tuple[float, float, float]


class GridPattern(BaseModel):
    """Repeat an asset along the X/Y(/Z) axes from an origin."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[LayoutPattern.GRID]
    origin: Vec3
    count: tuple[int, int] | tuple[int, int, int]
    spacing: tuple[float, float] | tuple[float, float, float]

    @field_validator("count")
    @classmethod
    def _counts_positive(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(c < 1 for c in value):
            raise ValueError("grid 'count' values must be >= 1.")
        return value

    @model_validator(mode="after")
    def _spacing_covers_count(self) -> GridPattern:
        if len(self.count) == 3 and len(self.spacing) == 2:
            raise ValueError(
                "a grid with a 3-axis 'count' needs a 3-axis 'spacing'.",
            )
        return self


class LinearPattern(BaseModel):
    """Repeat an asset count times along one direction step."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[LayoutPattern.LINEAR]
    origin: Vec3
    count: int = Field(ge=1)
    spacing: tuple[float, float] | tuple[float, float, float]


class LayoutTransform(BaseModel):
    """One enumerated placement transform."""

    model_config = ConfigDict(extra="forbid")

    translate: Vec3
    rotate: Vec3 | None = None
    scale: float | Vec3 | None = None


class LayoutEntry(BaseModel):
    """One batch-placement entry: an asset placed at many transforms."""

    model_config = ConfigDict(extra="forbid")

    asset: str = Field(min_length=1)
    group: str = Field(min_length=1)
    name: str | None = None
    rotate: Vec3 | None = None
    scale: float | Vec3 | None = None
    fix_root_prim: bool = False
    fix_root_transforms: bool = False
    transforms: list[LayoutTransform] | None = Field(default=None, min_length=1)
    pattern: (
        Annotated[GridPattern | LinearPattern, Field(discriminator="type")] | None
    ) = None

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> LayoutEntry:
        if (self.transforms is None) == (self.pattern is None):
            raise ValueError(
                "each layout entry needs exactly one of 'transforms' or 'pattern'.",
            )
        return self
