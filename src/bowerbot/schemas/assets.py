# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset-level schemas: formats, categories, ASWF layer names, metadata."""

from enum import StrEnum

from pydantic import BaseModel


class AssetFormat(StrEnum):
    """Supported 3D asset formats."""

    USD = ".usd"
    USDA = ".usda"
    USDC = ".usdc"
    USDZ = ".usdz"


class AssetCategory(StrEnum):
    """Classification of a USD asset following ASWF conventions."""

    GEO = "geo"          # geometry layer
    MTL = "mtl"          # materials + bindings layer
    LGT = "lgt"          # lighting layer
    PACKAGE = "package"  # ASWF-compliant asset folder


class AssetMetadata(BaseModel):
    """Metadata for a 3D asset sourced from any skill."""

    name: str
    source_skill: str  # e.g. "sketchfab", "local", "cgtrader"
    source_id: str  # Skill-specific identifier (URL, SKU, file path)
    file_path: str | None = None  # Local path after download
