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
from bowerbot.schemas.diagnostics import DiagnosticReport, Finding, FindingStatus
from bowerbot.schemas.intake import DetectionOutcome, FolderDetection, IntakeReport
from bowerbot.schemas.lights import (
    LightParams,
    LightPropertySpec,
    LightType,
    LightTypeSchemaInfo,
)
from bowerbot.schemas.materials import (
    MaterialXShaders,
    PreviewSurfaceShader,
    ProceduralMaterialParams,
)
from bowerbot.schemas.physics import (
    AssetPhysicsSummary,
    CollisionGroupsSummary,
    CollisionGroupSummary,
    JointsSummary,
    JointSummary,
    PhysicsApiName,
    PhysicsApiSchemaInfo,
    PhysicsJointType,
    PhysicsPrimSummary,
    PhysicsPropertySpec,
    PhysicsSummary,
    ScenePhysicsSummary,
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
    "AssetPhysicsSummary",
    "CollisionGroupSummary",
    "CollisionGroupsSummary",
    "DetectionOutcome",
    "DiagnosticReport",
    "Finding",
    "FindingStatus",
    "FolderDetection",
    "HDRIFormat",
    "IntakeReport",
    "JointSummary",
    "JointsSummary",
    "LightParams",
    "LightPropertySpec",
    "LightType",
    "LightTypeSchemaInfo",
    "MaterialXShaders",
    "PhysicsApiName",
    "PhysicsApiSchemaInfo",
    "PhysicsJointType",
    "PhysicsPrimSummary",
    "PhysicsPropertySpec",
    "PhysicsSummary",
    "PositionMode",
    "PreviewSurfaceShader",
    "ProceduralMaterialParams",
    "SceneNamespace",
    "SceneObject",
    "ScenePhysicsSummary",
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
