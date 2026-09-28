# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics values: UsdPhysics schema classes and the rules for applying them."""

from pxr import UsdGeom, UsdPhysics

from bowerbot.schemas import PhysicsApiName, PhysicsJointType


class PhysicsUsd:
    """UsdPhysics and UsdGeom schema classes behind each API and joint type."""

    APIS: dict[PhysicsApiName, type] = {
        PhysicsApiName.RIGID_BODY: UsdPhysics.RigidBodyAPI,
        PhysicsApiName.MASS: UsdPhysics.MassAPI,
        PhysicsApiName.COLLISION: UsdPhysics.CollisionAPI,
        PhysicsApiName.MESH_COLLISION: UsdPhysics.MeshCollisionAPI,
        PhysicsApiName.ARTICULATION_ROOT: UsdPhysics.ArticulationRootAPI,
        PhysicsApiName.DRIVE: UsdPhysics.DriveAPI,
        PhysicsApiName.LIMIT: UsdPhysics.LimitAPI,
    }
    # Prim base type each single-apply API requires per the UsdPhysics spec.
    # Multi-apply APIs (Drive, Limit) target joint prims directly.
    API_TARGETS: dict[PhysicsApiName, type] = {
        PhysicsApiName.RIGID_BODY: UsdGeom.Xformable,
        PhysicsApiName.MASS: UsdGeom.Xformable,
        PhysicsApiName.COLLISION: UsdGeom.Gprim,
        PhysicsApiName.MESH_COLLISION: UsdGeom.Mesh,
        PhysicsApiName.ARTICULATION_ROOT: UsdGeom.Xformable,
    }
    JOINTS: dict[PhysicsJointType, type] = {
        PhysicsJointType.REVOLUTE: UsdPhysics.RevoluteJoint,
        PhysicsJointType.PRISMATIC: UsdPhysics.PrismaticJoint,
        PhysicsJointType.SPHERICAL: UsdPhysics.SphericalJoint,
        PhysicsJointType.FIXED: UsdPhysics.FixedJoint,
        PhysicsJointType.DISTANCE: UsdPhysics.DistanceJoint,
    }


class PhysicsRules:
    """Which APIs go together, and which instance names each joint accepts."""

    MULTI_APPLY_APIS: frozenset[PhysicsApiName] = frozenset({
        PhysicsApiName.DRIVE,
        PhysicsApiName.LIMIT,
    })
    # Stands for the instance name in a multi-apply API's property names.
    INSTANCE_NAME_PLACEHOLDER = "__INSTANCE_NAME__"
    # Drive instance names each joint type accepts.
    DRIVE_INSTANCES: dict[PhysicsJointType, frozenset[str]] = {
        PhysicsJointType.REVOLUTE: frozenset({"angular"}),
        PhysicsJointType.PRISMATIC: frozenset({"linear"}),
        PhysicsJointType.SPHERICAL: frozenset(),
        PhysicsJointType.FIXED: frozenset(),
        PhysicsJointType.DISTANCE: frozenset(),
    }
    # Limit instance names each joint type accepts.
    LIMIT_INSTANCES: dict[PhysicsJointType, frozenset[str]] = {
        PhysicsJointType.REVOLUTE: frozenset({"angular"}),
        PhysicsJointType.PRISMATIC: frozenset({"linear"}),
        PhysicsJointType.SPHERICAL: frozenset({"rotX", "rotY", "rotZ"}),
        PhysicsJointType.FIXED: frozenset(),
        PhysicsJointType.DISTANCE: frozenset({"distance"}),
    }
    INSTANCES_BY_API: dict[PhysicsApiName, dict[PhysicsJointType, frozenset[str]]] = {
        PhysicsApiName.DRIVE: DRIVE_INSTANCES,
        PhysicsApiName.LIMIT: LIMIT_INSTANCES,
    }
    # MeshCollisionAPI is meaningless without CollisionAPI per the spec.
    COMPANION_APIS: dict[PhysicsApiName, PhysicsApiName] = {
        PhysicsApiName.MESH_COLLISION: PhysicsApiName.COLLISION,
    }
    # Dropping CollisionAPI also drops MeshCollisionAPI.
    DEPENDENT_APIS: dict[PhysicsApiName, tuple[PhysicsApiName, ...]] = {
        PhysicsApiName.COLLISION: (PhysicsApiName.MESH_COLLISION,),
    }


class PhysicsNamespace:
    """Prim names BowerBot uses in an asset's phy.usda."""

    # Scope under the asset's default prim that holds its joints.
    JOINTS_SCOPE = "joints"
