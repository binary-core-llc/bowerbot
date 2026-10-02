# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Material values: shader identifiers and shading prim types."""


class MaterialXShaders:
    """MaterialX shader identifiers and naming conventions."""

    STANDARD_SURFACE = "ND_standard_surface_surfaceshader"
    # Every MaterialX shader identifier BowerBot authors.
    ALL = (STANDARD_SURFACE,)
    STANDARD_SURFACE_PRIM = "standard_surface"
    OUTPUT_QUALIFIER = "mtlx"


class PreviewSurfaceShader:
    """UsdPreviewSurface shader identifiers."""

    SURFACE_ID = "UsdPreviewSurface"
    SURFACE_PRIM = "preview_surface"


class MaterialRules:
    """Which prim types belong to shading rather than geometry."""

    # Prim types that make up a material, never geometry.
    SHADING_PRIM_TYPES = frozenset({"Material", "Shader", "NodeGraph"})
