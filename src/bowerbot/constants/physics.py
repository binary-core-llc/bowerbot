# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics values: UsdPhysics schema classes and the rules for applying them."""

from pxr import UsdGeom
from pxr import UsdPhysics

from bowerbot import schemas


class PhysicsUsd:
    """UsdPhysics and UsdGeom schema classes behind each API and joint type."""

    APIS: dict[schemas.PhysicsApiName, type] = {
        schemas.PhysicsApiName.RIGID_BODY: UsdPhysics.RigidBodyAPI,
        schemas.PhysicsApiName.MASS: UsdPhysics.MassAPI,
        schemas.PhysicsApiName.COLLISION: UsdPhysics.CollisionAPI,
        schemas.PhysicsApiName.MESH_COLLISION: UsdPhysics.MeshCollisionAPI,
        schemas.PhysicsApiName.ARTICULATION_ROOT: UsdPhysics.ArticulationRootAPI,
        schemas.PhysicsApiName.DRIVE: UsdPhysics.DriveAPI,
        schemas.PhysicsApiName.LIMIT: UsdPhysics.LimitAPI,
    }
    # Prim base type each single-apply API requires per the UsdPhysics spec.
    # Multi-apply APIs (Drive, Limit) target joint prims directly.
    API_TARGETS: dict[schemas.PhysicsApiName, type] = {
        schemas.PhysicsApiName.RIGID_BODY: UsdGeom.Xformable,
        schemas.PhysicsApiName.MASS: UsdGeom.Xformable,
        schemas.PhysicsApiName.COLLISION: UsdGeom.Gprim,
        schemas.PhysicsApiName.MESH_COLLISION: UsdGeom.Mesh,
        schemas.PhysicsApiName.ARTICULATION_ROOT: UsdGeom.Xformable,
    }
    JOINTS: dict[schemas.PhysicsJointType, type] = {
        schemas.PhysicsJointType.REVOLUTE: UsdPhysics.RevoluteJoint,
        schemas.PhysicsJointType.PRISMATIC: UsdPhysics.PrismaticJoint,
        schemas.PhysicsJointType.SPHERICAL: UsdPhysics.SphericalJoint,
        schemas.PhysicsJointType.FIXED: UsdPhysics.FixedJoint,
        schemas.PhysicsJointType.DISTANCE: UsdPhysics.DistanceJoint,
    }


class PhysicsRules:
    """Which APIs go together, and which instance names each joint accepts."""

    MULTI_APPLY_APIS: frozenset[schemas.PhysicsApiName] = frozenset({
        schemas.PhysicsApiName.DRIVE,
        schemas.PhysicsApiName.LIMIT,
    })
    # Namespace of every UsdPhysics attribute (physics:mass, drive:angular:physics:damping).
    ATTRIBUTE_NAMESPACE = "physics"
    # Keyword USD's own physics validators carry in the validation registry.
    VALIDATOR_KEYWORD = "UsdPhysicsValidators"
    # Stands for the instance name in a multi-apply API's property names.
    INSTANCE_NAME_PLACEHOLDER = "__INSTANCE_NAME__"
    # Drive instance names each joint type accepts.
    DRIVE_INSTANCES: dict[schemas.PhysicsJointType, frozenset[str]] = {
        schemas.PhysicsJointType.REVOLUTE: frozenset({"angular"}),
        schemas.PhysicsJointType.PRISMATIC: frozenset({"linear"}),
        schemas.PhysicsJointType.SPHERICAL: frozenset(),
        schemas.PhysicsJointType.FIXED: frozenset(),
        schemas.PhysicsJointType.DISTANCE: frozenset(),
    }
    # Limit instance names each joint type accepts.
    LIMIT_INSTANCES: dict[schemas.PhysicsJointType, frozenset[str]] = {
        schemas.PhysicsJointType.REVOLUTE: frozenset({"angular"}),
        schemas.PhysicsJointType.PRISMATIC: frozenset({"linear"}),
        schemas.PhysicsJointType.SPHERICAL: frozenset({"rotX", "rotY", "rotZ"}),
        schemas.PhysicsJointType.FIXED: frozenset(),
        schemas.PhysicsJointType.DISTANCE: frozenset({"distance"}),
    }
    INSTANCES_BY_API: dict[
        schemas.PhysicsApiName, dict[schemas.PhysicsJointType, frozenset[str]],
    ] = {
        schemas.PhysicsApiName.DRIVE: DRIVE_INSTANCES,
        schemas.PhysicsApiName.LIMIT: LIMIT_INSTANCES,
    }
    # MeshCollisionAPI is meaningless without CollisionAPI per the spec.
    COMPANION_APIS: dict[schemas.PhysicsApiName, schemas.PhysicsApiName] = {
        schemas.PhysicsApiName.MESH_COLLISION: schemas.PhysicsApiName.COLLISION,
    }
    # Dropping CollisionAPI also drops MeshCollisionAPI.
    DEPENDENT_APIS: dict[schemas.PhysicsApiName, tuple[schemas.PhysicsApiName, ...]] = {
        schemas.PhysicsApiName.COLLISION: (schemas.PhysicsApiName.MESH_COLLISION,),
    }


class PhysicsNamespace:
    """Prim names BowerBot uses in an asset's phy.usda."""

    # Scope under the asset's default prim that holds its joints.
    JOINTS_SCOPE = "joints"
