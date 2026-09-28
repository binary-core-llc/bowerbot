# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot data schemas, grouped by domain.

Import from ``bowerbot.schemas`` for anything — this package re-exports
every public symbol so call sites don't need to know which file a
schema lives in.
"""

from bowerbot.schemas.assets import AssetCategory
from bowerbot.schemas.assets import AssetFormat
from bowerbot.schemas.assets import AssetMetadata
from bowerbot.schemas.cameras import CameraParams
from bowerbot.schemas.cameras import CameraPropertySpec
from bowerbot.schemas.cameras import CameraSchemaInfo
from bowerbot.schemas.intake import DetectionOutcome
from bowerbot.schemas.intake import FolderDetection
from bowerbot.schemas.intake import IntakeReport
from bowerbot.schemas.layout import GridPattern
from bowerbot.schemas.layout import LayoutEntry
from bowerbot.schemas.layout import LayoutTransform
from bowerbot.schemas.layout import LinearPattern
from bowerbot.schemas.lights import LightParams
from bowerbot.schemas.lights import LightPropertySpec
from bowerbot.schemas.lights import LightType
from bowerbot.schemas.lights import LightTypeSchemaInfo
from bowerbot.schemas.materials import ProceduralMaterialParams
from bowerbot.schemas.opinions import OpinionKind
from bowerbot.schemas.physics import AssetPhysicsSummary
from bowerbot.schemas.physics import CollisionGroupsSummary
from bowerbot.schemas.physics import CollisionGroupSummary
from bowerbot.schemas.physics import JointsSummary
from bowerbot.schemas.physics import JointSummary
from bowerbot.schemas.physics import PhysicsApiName
from bowerbot.schemas.physics import PhysicsApiSchemaInfo
from bowerbot.schemas.physics import PhysicsJointType
from bowerbot.schemas.physics import PhysicsPrimSummary
from bowerbot.schemas.physics import PhysicsPropertySpec
from bowerbot.schemas.physics import PhysicsSummary
from bowerbot.schemas.physics import ScenePhysicsSummary
from bowerbot.schemas.scatter import ScatterAcceptance
from bowerbot.schemas.scatter import ScatterAlign
from bowerbot.schemas.scatter import ScatterArrangement
from bowerbot.schemas.scatter import ScatterAsset
from bowerbot.schemas.scatter import ScatterAssetOrder
from bowerbot.schemas.scatter import ScatterDropAlign
from bowerbot.schemas.scatter import ScatterInstanceSet
from bowerbot.schemas.scatter import ScatterOutput
from bowerbot.schemas.scatter import ScatterPathCircle
from bowerbot.schemas.scatter import ScatterPathFacing
from bowerbot.schemas.scatter import ScatterPathParams
from bowerbot.schemas.scatter import ScatterPathSide
from bowerbot.schemas.scatter import ScatterPoseParams
from bowerbot.schemas.scatter import ScatterPrototype
from bowerbot.schemas.scatter import ScatterRegion
from bowerbot.schemas.scatter import ScatterRegionFalloff
from bowerbot.schemas.scatter import ScatterSurfaceParams
from bowerbot.schemas.surface import BoolArray
from bowerbot.schemas.surface import FloatArray
from bowerbot.schemas.surface import IntArray
from bowerbot.schemas.surface import SurfaceIndex
from bowerbot.schemas.surface import SurfaceTriangles
from bowerbot.schemas.textures import HDRIFormat
from bowerbot.schemas.textures import TextureCategory
from bowerbot.schemas.transforms import LayoutPattern
from bowerbot.schemas.transforms import PositionMode
from bowerbot.schemas.transforms import SceneObject
from bowerbot.schemas.transforms import TransformParams
from bowerbot.schemas.transforms import Vec3
from bowerbot.schemas.validation import Severity
from bowerbot.schemas.validation import ValidationIssue
from bowerbot.schemas.validation import ValidationResult
from bowerbot.schemas.variants import SceneVariantsSummary
from bowerbot.schemas.variants import VariantCarrier
from bowerbot.schemas.variants import VariantCategory
from bowerbot.schemas.variants import VariantSetSummary
from bowerbot.schemas.variants import VariantsSummary

__all__ = [
    "AssetCategory",
    "AssetFormat",
    "AssetMetadata",
    "AssetPhysicsSummary",
    "BoolArray",
    "CameraParams",
    "CameraPropertySpec",
    "CameraSchemaInfo",
    "CollisionGroupsSummary",
    "CollisionGroupSummary",
    "DetectionOutcome",
    "FloatArray",
    "FolderDetection",
    "GridPattern",
    "HDRIFormat",
    "IntakeReport",
    "IntArray",
    "JointsSummary",
    "JointSummary",
    "LayoutEntry",
    "LayoutPattern",
    "LayoutTransform",
    "LightParams",
    "LightPropertySpec",
    "LightType",
    "LightTypeSchemaInfo",
    "LinearPattern",
    "OpinionKind",
    "PhysicsApiName",
    "PhysicsApiSchemaInfo",
    "PhysicsJointType",
    "PhysicsPrimSummary",
    "PhysicsPropertySpec",
    "PhysicsSummary",
    "PositionMode",
    "ProceduralMaterialParams",
    "ScatterAcceptance",
    "ScatterAlign",
    "ScatterArrangement",
    "ScatterAsset",
    "ScatterAssetOrder",
    "ScatterDropAlign",
    "ScatterInstanceSet",
    "ScatterOutput",
    "ScatterPathCircle",
    "ScatterPathFacing",
    "ScatterPathParams",
    "ScatterPathSide",
    "ScatterPoseParams",
    "ScatterPrototype",
    "ScatterRegion",
    "ScatterRegionFalloff",
    "ScatterSurfaceParams",
    "SceneObject",
    "ScenePhysicsSummary",
    "SceneVariantsSummary",
    "Severity",
    "SurfaceIndex",
    "SurfaceTriangles",
    "TextureCategory",
    "TransformParams",
    "ValidationIssue",
    "ValidationResult",
    "VariantCarrier",
    "VariantCategory",
    "VariantSetSummary",
    "VariantsSummary",
    "Vec3",
]
