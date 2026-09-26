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
from bowerbot.schemas.cameras import (
    CameraDefaults,
    CameraParams,
    CameraSchemaInfo,
    CameraTuning,
)
from bowerbot.schemas.intake import (
    DetectionOutcome,
    FolderDetection,
    IntakeReport,
    IntakeRules,
)
from bowerbot.schemas.layout import (
    GridPattern,
    LayoutEntry,
    LayoutRules,
    LayoutTransform,
    LinearPattern,
)
from bowerbot.schemas.library import LibraryDefaults, LibraryRules
from bowerbot.schemas.lights import (
    LightParams,
    LightRules,
    LightType,
    LightTypeSchemaInfo,
)
from bowerbot.schemas.materials import (
    MaterialXShaders,
    PreviewSurfaceShader,
    ProceduralMaterialParams,
)
from bowerbot.schemas.naming import NamingRules
from bowerbot.schemas.overrides import OverrideRules
from bowerbot.schemas.physics import (
    AssetPhysicsSummary,
    CollisionGroupsSummary,
    CollisionGroupSummary,
    JointsSummary,
    JointSummary,
    PhysicsApiName,
    PhysicsApiSchemaInfo,
    PhysicsJointType,
    PhysicsNamespace,
    PhysicsPrimSummary,
    PhysicsRules,
    PhysicsSummary,
    ScenePhysicsSummary,
)
from bowerbot.schemas.scatter import (
    ScatterAlign,
    ScatterArrangement,
    ScatterAsset,
    ScatterAssetOrder,
    ScatterDropAlign,
    ScatterInstanceSet,
    ScatterNamespace,
    ScatterOutput,
    ScatterPathCircle,
    ScatterPathFacing,
    ScatterPathParams,
    ScatterPathSide,
    ScatterPoseParams,
    ScatterPrototype,
    ScatterRegion,
    ScatterRegionFalloff,
    ScatterRules,
    ScatterSurfaceParams,
    ScatterTuning,
)
from bowerbot.schemas.scene import SceneNamespace
from bowerbot.schemas.schema_registry import SchemaPropertySpec
from bowerbot.schemas.surface import (
    SurfaceIndex,
    SurfaceTriangles,
    SurfaceTuning,
)
from bowerbot.schemas.textures import HDRIFormat, TextureCategory
from bowerbot.schemas.transforms import (
    LayoutPattern,
    PositionDefaults,
    PositionMode,
    SceneObject,
    TransformParams,
)
from bowerbot.schemas.validation import Severity, ValidationIssue, ValidationResult
from bowerbot.schemas.variants import (
    SceneVariantsSummary,
    VariantCarrier,
    VariantCategory,
    VariantRules,
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
    "CameraDefaults",
    "CameraParams",
    "CameraSchemaInfo",
    "CameraTuning",
    "CollisionGroupSummary",
    "CollisionGroupsSummary",
    "DetectionOutcome",
    "FolderDetection",
    "GridPattern",
    "HDRIFormat",
    "IntakeReport",
    "IntakeRules",
    "JointSummary",
    "JointsSummary",
    "LayoutEntry",
    "LayoutPattern",
    "LayoutRules",
    "LayoutTransform",
    "LibraryDefaults",
    "LibraryRules",
    "LightParams",
    "LightRules",
    "LightType",
    "LightTypeSchemaInfo",
    "LinearPattern",
    "MaterialXShaders",
    "NamingRules",
    "OverrideRules",
    "PhysicsApiName",
    "PhysicsApiSchemaInfo",
    "PhysicsJointType",
    "PhysicsNamespace",
    "PhysicsPrimSummary",
    "PhysicsRules",
    "PhysicsSummary",
    "PositionDefaults",
    "PositionMode",
    "PreviewSurfaceShader",
    "ProceduralMaterialParams",
    "ScatterAlign",
    "ScatterArrangement",
    "ScatterAsset",
    "ScatterAssetOrder",
    "ScatterDropAlign",
    "ScatterInstanceSet",
    "ScatterNamespace",
    "ScatterOutput",
    "ScatterPathCircle",
    "ScatterPathFacing",
    "ScatterPathParams",
    "ScatterPathSide",
    "ScatterPoseParams",
    "ScatterPrototype",
    "ScatterRegion",
    "ScatterRegionFalloff",
    "ScatterRules",
    "ScatterSurfaceParams",
    "ScatterTuning",
    "SceneNamespace",
    "SceneObject",
    "ScenePhysicsSummary",
    "SceneVariantsSummary",
    "SchemaPropertySpec",
    "Severity",
    "SurfaceIndex",
    "SurfaceTriangles",
    "SurfaceTuning",
    "TextureCategory",
    "TransformParams",
    "ValidationIssue",
    "ValidationResult",
    "VariantCarrier",
    "VariantCategory",
    "VariantRules",
    "VariantSetSummary",
    "VariantsSummary",
]
