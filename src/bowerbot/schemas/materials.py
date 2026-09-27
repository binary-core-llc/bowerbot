# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Material schemas (MaterialX shader identifiers, procedural params)."""

from typing import Annotated

from pydantic import BaseModel, Field


class MaterialXShaders:
    """MaterialX shader identifiers and naming conventions."""

    STANDARD_SURFACE = "ND_standard_surface_surfaceshader"
    STANDARD_SURFACE_PRIM = "standard_surface"
    OUTPUT_QUALIFIER = "mtlx"
    # Every MaterialX node definition id starts with this prefix.
    NODE_DEF_PREFIX = "ND_"
    # Sdr source type a USD build with MaterialX support registers.
    SDR_SOURCE_TYPE = "mtlx"
    # A BowerBot material authors each value on both networks; a value change
    # on one input goes to its twin: standard_surface input -> preview input.
    PREVIEW_TWIN_INPUTS = {
        "base_color": "diffuseColor",
        "metalness": "metallic",
        "specular_roughness": "roughness",
        "opacity": "opacity",
    }


class PreviewSurfaceShader:
    """UsdPreviewSurface shader identifiers."""

    SURFACE_ID = "UsdPreviewSurface"
    SURFACE_PRIM = "preview_surface"


# A material input that runs from 0 to 1 (a color channel, metalness, roughness, opacity).
type UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]


class ProceduralMaterialParams(BaseModel):
    """Parameters for creating a procedural MaterialX material; every input is 0 to 1."""

    material_name: str
    base_color: tuple[UnitFloat, UnitFloat, UnitFloat] = (0.8, 0.8, 0.8)
    metalness: UnitFloat = 0.0
    roughness: UnitFloat = 0.5
    opacity: UnitFloat = 1.0
