# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Type predicates for UsdPhysics-typed prims; leaf module, safe to import anywhere."""

from __future__ import annotations

from pxr import Usd, UsdPhysics

JOINT_CLASSES: tuple[type, ...] = (
    UsdPhysics.RevoluteJoint,
    UsdPhysics.PrismaticJoint,
    UsdPhysics.SphericalJoint,
    UsdPhysics.FixedJoint,
    UsdPhysics.DistanceJoint,
)


def is_joint(prim: Usd.Prim) -> bool:
    """Whether *prim* is one of the supported UsdPhysics joint typed prims."""
    return any(prim.IsA(c) for c in JOINT_CLASSES)


def is_physics_scene(prim: Usd.Prim) -> bool:
    """Whether *prim* is a ``UsdPhysics.Scene``."""
    return prim.IsA(UsdPhysics.Scene)


def is_collision_group(prim: Usd.Prim) -> bool:
    """Whether *prim* is a ``UsdPhysics.CollisionGroup``."""
    return prim.IsA(UsdPhysics.CollisionGroup)
