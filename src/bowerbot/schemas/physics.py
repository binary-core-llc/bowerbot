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

from bowerbot.schemas.schema_registry import SchemaPropertySpec


class PhysicsApiName(StrEnum):
    """Whitelist of UsdPhysics applied-API schemas supported."""

    RIGID_BODY = "PhysicsRigidBodyAPI"
    MASS = "PhysicsMassAPI"
    COLLISION = "PhysicsCollisionAPI"
    MESH_COLLISION = "PhysicsMeshCollisionAPI"
    ARTICULATION_ROOT = "PhysicsArticulationRootAPI"
    DRIVE = "PhysicsDriveAPI"
    LIMIT = "PhysicsLimitAPI"


class PhysicsJointType(StrEnum):
    """Whitelist of UsdPhysics typed joint prims supported."""

    REVOLUTE = "PhysicsRevoluteJoint"
    PRISMATIC = "PhysicsPrismaticJoint"
    SPHERICAL = "PhysicsSphericalJoint"
    FIXED = "PhysicsFixedJoint"
    DISTANCE = "PhysicsDistanceJoint"


class PhysicsRules:
    """How UsdPhysics APIs apply to prims and depend on each other."""

    MULTI_APPLY_APIS = frozenset({PhysicsApiName.DRIVE, PhysicsApiName.LIMIT})
    # Placeholder the schema registry uses for a multi-apply instance name.
    INSTANCE_NAME_PLACEHOLDER = "__INSTANCE_NAME__"
    # Instance names each multi-apply API accepts, per joint type.
    INSTANCE_NAMES = {
        PhysicsApiName.DRIVE: {
            PhysicsJointType.REVOLUTE: frozenset({"angular"}),
            PhysicsJointType.PRISMATIC: frozenset({"linear"}),
            PhysicsJointType.SPHERICAL: frozenset(),
            PhysicsJointType.FIXED: frozenset(),
            PhysicsJointType.DISTANCE: frozenset(),
        },
        PhysicsApiName.LIMIT: {
            PhysicsJointType.REVOLUTE: frozenset({"angular"}),
            PhysicsJointType.PRISMATIC: frozenset({"linear"}),
            PhysicsJointType.SPHERICAL: frozenset({"rotX", "rotY", "rotZ"}),
            PhysicsJointType.FIXED: frozenset(),
            PhysicsJointType.DISTANCE: frozenset({"distance"}),
        },
    }
    # Prim base type each single-apply API requires per the UsdPhysics spec
    # (USD schema type names). Multi-apply APIs (Drive, Limit) target joint prims.
    TARGET_TYPES = {
        PhysicsApiName.RIGID_BODY: "Xformable",
        PhysicsApiName.MASS: "Xformable",
        PhysicsApiName.COLLISION: "Gprim",
        PhysicsApiName.MESH_COLLISION: "Mesh",
        PhysicsApiName.ARTICULATION_ROOT: "Xformable",
    }
    # MeshCollisionAPI is meaningless without CollisionAPI per the spec.
    COMPANIONS = {PhysicsApiName.MESH_COLLISION: PhysicsApiName.COLLISION}
    # Dropping CollisionAPI also drops MeshCollisionAPI.
    DEPENDENTS = {PhysicsApiName.COLLISION: (PhysicsApiName.MESH_COLLISION,)}


class PhysicsNamespace:
    """Canonical names BowerBot uses when authoring physics."""

    JOINTS_SCOPE = "joints"
    # Name of the physics scene BowerBot creates when a scene has none.
    DEFAULT_SCENE_NAME = "PhysicsScene"


class PhysicsDefaults:
    """Values a new physics scene gets when the request gives none."""

    # Earth gravity in m/s²; divided by metersPerUnit to get stage units.
    EARTH_GRAVITY = 9.81


class PhysicsApiSchemaInfo(BaseModel):
    """Live introspection of a UsdPhysics applied-API schema."""

    api_name: str
    target_requirement: str  # e.g. "UsdGeomGprim", "UsdGeomXformable", "UsdGeomMesh"
    requires_companion_api: str | None = None
    properties: list[SchemaPropertySpec] = []


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
