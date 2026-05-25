# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""UsdPhysics static-foundation schemas.

Output-only models and the whitelist of supported applied-API schemas.
Attribute values are passed as free ``{name: value}`` dicts and resolved
against the live USD schema registry at write time, mirroring the variant
attribute-authoring pattern.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class PhysicsApiName(StrEnum):
    """Whitelist of UsdPhysics applied-API schemas supported."""

    RIGID_BODY = "PhysicsRigidBodyAPI"
    MASS = "PhysicsMassAPI"
    COLLISION = "PhysicsCollisionAPI"
    MESH_COLLISION = "PhysicsMeshCollisionAPI"
    ARTICULATION_ROOT = "PhysicsArticulationRootAPI"


class PhysicsJointType(StrEnum):
    """Whitelist of UsdPhysics typed joint prims supported."""

    REVOLUTE = "PhysicsRevoluteJoint"
    PRISMATIC = "PhysicsPrismaticJoint"
    SPHERICAL = "PhysicsSphericalJoint"
    FIXED = "PhysicsFixedJoint"
    DISTANCE = "PhysicsDistanceJoint"


class PhysicsPropertySpec(BaseModel):
    """One property exposed by a UsdPhysics API, discovered at runtime."""

    name: str
    kind: str  # "attribute" or "relationship"
    type_name: str | None = None
    default: Any = None
    allowed_tokens: list[str] = []
    documentation: str = ""


class PhysicsApiSchemaInfo(BaseModel):
    """Live introspection of a UsdPhysics applied-API schema."""

    api_name: str
    target_requirement: str  # e.g. "UsdGeomGprim", "UsdGeomXformable", "UsdGeomMesh"
    requires_companion_api: str | None = None
    properties: list[PhysicsPropertySpec] = []


class PhysicsPrimSummary(BaseModel):
    """One prim's authored physics APIs and attribute opinions."""

    prim_path: str
    applied_apis: list[str] = []
    attributes: dict[str, Any] = {}
    relationships: dict[str, list[str]] = {}


class AssetPhysicsSummary(BaseModel):
    """All physics opinions authored in an asset's ``phy.usda``."""

    asset_path: str
    has_physics_layer: bool = False
    prims: list[PhysicsPrimSummary] = []


class ScenePhysicsSummary(BaseModel):
    """Scene-side physics opinions on a prim and its descendants in scene.usda."""

    prim_path: str
    prims: list[PhysicsPrimSummary] = []


class PhysicsSummary(BaseModel):
    """Combined asset + scene physics opinions for a prim."""

    asset: AssetPhysicsSummary | None = None
    scene: ScenePhysicsSummary | None = None


class CollisionGroupSummary(BaseModel):
    """One ``UsdPhysicsCollisionGroup`` and its authored state."""

    name: str
    prim_path: str
    includes: list[str] = []
    excludes: list[str] = []
    filtered_groups: list[str] = []
    invert_filter: bool = False
    merge_group: str | None = None


class CollisionGroupsSummary(BaseModel):
    """Every ``UsdPhysicsCollisionGroup`` defined under ``/Scene/Physics/Groups``."""

    groups: list[CollisionGroupSummary] = []


class JointSummary(BaseModel):
    """One UsdPhysics joint prim and its authored state."""

    prim_path: str
    joint_type: str
    body0: str | None = None
    body1: str | None = None
    attributes: dict[str, Any] = {}
    applied_apis: list[str] = []


class JointsSummary(BaseModel):
    """Every UsdPhysics joint discovered under a prim or scene-wide."""

    joints: list[JointSummary] = []
