# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Type predicates for UsdPhysics-typed prims."""

from __future__ import annotations

from pxr import Usd, UsdPhysics

from bowerbot.schemas import PhysicsJointType
from bowerbot.utils.core.schema_registry import schema_class


def is_joint(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is one of the supported UsdPhysics joint typed prims."""
    return prim is not None and prim.IsValid() and any(
        prim.IsA(schema_class(joint_type)) for joint_type in PhysicsJointType
    )


def is_physics_scene(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is a ``UsdPhysics.Scene``."""
    return prim is not None and prim.IsValid() and prim.IsA(UsdPhysics.Scene)


def is_collision_group(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is a ``UsdPhysics.CollisionGroup``."""
    return prim is not None and prim.IsValid() and prim.IsA(UsdPhysics.CollisionGroup)


def is_rigid_body(prim: Usd.Prim | None) -> bool:
    """Whether *prim* carries ``PhysicsRigidBodyAPI``."""
    return (
        prim is not None
        and prim.IsValid()
        and "PhysicsRigidBodyAPI" in prim.GetAppliedSchemas()
    )


def is_articulation_root(prim: Usd.Prim | None) -> bool:
    """Whether *prim* carries ``PhysicsArticulationRootAPI``."""
    return (
        prim is not None
        and prim.IsValid()
        and "PhysicsArticulationRootAPI" in prim.GetAppliedSchemas()
    )
