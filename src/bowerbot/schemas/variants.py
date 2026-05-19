# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant set schemas."""

from enum import StrEnum

from pydantic import BaseModel, Field


class VariantCategory(StrEnum):
    """Variant orchestrator categories shipped with BowerBot."""

    MATERIAL = "material"
    GEOMETRY = "geometry"
    CONFIGURATION = "configuration"
    ATTRIBUTE = "attribute"
    LIGHTING = "lighting"
    MODEL_SELECTION = "model_selection"
    CUSTOM = "custom"


class VariantSetSummary(BaseModel):
    """Summary of one variant set on an asset's root prim."""

    name: str
    variants: list[str] = Field(default_factory=list)
    selection: str | None = None


class VariantsSummary(BaseModel):
    """All variant sets observed on an asset's root prim."""

    asset_path: str
    has_variants_layer: bool
    variant_sets: list[VariantSetSummary] = Field(default_factory=list)


class VariantCarrier(BaseModel):
    """A scene prim that exposes one or more variant sets via composition."""

    prim_path: str
    variant_sets: list[VariantSetSummary] = Field(default_factory=list)


class SceneVariantsSummary(BaseModel):
    """All variant carriers visible under a scene placement."""

    prim_path: str
    carriers: list[VariantCarrier] = Field(default_factory=list)
