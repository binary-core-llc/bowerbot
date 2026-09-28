# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Material schemas (MaterialX shader identifiers, procedural params)."""

from pydantic import BaseModel


class ProceduralMaterialParams(BaseModel):
    """Parameters for creating a procedural MaterialX material."""

    material_name: str
    base_color: tuple[float, float, float] = (0.8, 0.8, 0.8)
    metalness: float = 0.0
    roughness: float = 0.5
    opacity: float = 1.0
