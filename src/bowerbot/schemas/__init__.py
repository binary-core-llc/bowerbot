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
)
from bowerbot.schemas.intake import DetectionOutcome, FolderDetection, IntakeReport
from bowerbot.schemas.lights import LightParams, LightType
from bowerbot.schemas.materials import (
    MaterialXShaders,
    PreviewSurfaceShader,
    ProceduralMaterialParams,
)
from bowerbot.schemas.scene import SceneNamespace
from bowerbot.schemas.textures import HDRIFormat, TextureCategory
from bowerbot.schemas.transforms import PositionMode, SceneObject, TransformParams
from bowerbot.schemas.validation import Severity, ValidationIssue, ValidationResult
from bowerbot.schemas.variants import (
    SceneVariantsSummary,
    VariantCarrier,
    VariantCategory,
    VariantSetSummary,
    VariantsSummary,
)

__all__ = [
    "AppleUSDZConstraints",
    "ASWFLayerNames",
    "AssetCategory",
    "AssetFormat",
    "AssetMetadata",
    "DetectionOutcome",
    "FolderDetection",
    "HDRIFormat",
    "IntakeReport",
    "LightParams",
    "LightType",
    "MaterialXShaders",
    "PositionMode",
    "PreviewSurfaceShader",
    "ProceduralMaterialParams",
    "SceneNamespace",
    "SceneObject",
    "SceneVariantsSummary",
    "Severity",
    "TextureCategory",
    "TransformParams",
    "ValidationIssue",
    "ValidationResult",
    "VariantCarrier",
    "VariantCategory",
    "VariantSetSummary",
    "VariantsSummary",
]
