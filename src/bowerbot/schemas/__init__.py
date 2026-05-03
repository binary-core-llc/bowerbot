# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot data schemas, grouped by domain.

Import from ``bowerbot.schemas`` for anything — this package re-exports
every public symbol so call sites don't need to know which file a
schema lives in.
"""

from bowerbot.schemas.assets import (
    AppleUSDZConstraints,
    AssetCategory,
    AssetFormat,
    AssetMetadata,
    ASWFLayerNames,
    SceneLayerNames,
)
from bowerbot.schemas.intake import DetectionOutcome, FolderDetection, IntakeReport
from bowerbot.schemas.lights import LightParams, LightType
from bowerbot.schemas.materials import (
    MaterialXShaders,
    PreviewSurfaceShader,
    ProceduralMaterialParams,
)
from bowerbot.schemas.textures import HDRIFormat, ImageFormat, TextureCategory
from bowerbot.schemas.transforms import (
    PlacementCategory,
    PositionMode,
    SceneObject,
    TransformParams,
)
from bowerbot.schemas.validation import Severity, ValidationIssue, ValidationResult

__all__ = [
    "AppleUSDZConstraints",
    "ASWFLayerNames",
    "AssetCategory",
    "AssetFormat",
    "AssetMetadata",
    "DetectionOutcome",
    "FolderDetection",
    "HDRIFormat",
    "ImageFormat",
    "IntakeReport",
    "LightParams",
    "LightType",
    "MaterialXShaders",
    "PlacementCategory",
    "PositionMode",
    "PreviewSurfaceShader",
    "ProceduralMaterialParams",
    "SceneLayerNames",
    "SceneObject",
    "Severity",
    "TextureCategory",
    "TransformParams",
    "ValidationIssue",
    "ValidationResult",
]
