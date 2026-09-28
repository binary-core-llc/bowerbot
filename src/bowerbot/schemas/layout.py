# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Layout schemas — the batch-placement contract consumed by place_layout."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

# Imported under another name: LayoutEntry has a field named ``transforms`` (the
# place_layout input key), which would hide the module inside that class.
from bowerbot.schemas import transforms as transform_schemas


class GridPattern(BaseModel):
    """Repeat an asset along the X/Y(/Z) axes from an origin."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[transform_schemas.LayoutPattern.GRID]
    origin: transform_schemas.Vec3
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

    type: Literal[transform_schemas.LayoutPattern.LINEAR]
    origin: transform_schemas.Vec3
    count: int = Field(ge=1)
    spacing: tuple[float, float] | tuple[float, float, float]


class LayoutTransform(BaseModel):
    """One enumerated placement transform."""

    model_config = ConfigDict(extra="forbid")

    translate: transform_schemas.Vec3
    rotate: transform_schemas.Vec3 | None = None
    scale: float | transform_schemas.Vec3 | None = None


class LayoutEntry(BaseModel):
    """One batch-placement entry: an asset placed at many transforms."""

    model_config = ConfigDict(extra="forbid")

    asset: str = Field(min_length=1)
    group: str = Field(min_length=1)
    name: str | None = None
    rotate: transform_schemas.Vec3 | None = None
    scale: float | transform_schemas.Vec3 | None = None
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
