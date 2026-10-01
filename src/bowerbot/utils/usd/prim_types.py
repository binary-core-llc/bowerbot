# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Which UsdPhysics typed prim a prim is, and the two bodies a joint connects."""

from __future__ import annotations

from pxr import Usd
from pxr import UsdPhysics

from bowerbot import constants

# ── Physics typed prims ──


def is_physics_scene(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is a ``UsdPhysics.Scene``."""
    return prim is not None and prim.IsA(UsdPhysics.Scene)


def is_joint(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is one of the supported UsdPhysics joint typed prims."""
    return prim is not None and any(prim.IsA(c) for c in constants.PhysicsUsd.JOINTS.values())


def is_collision_group(prim: Usd.Prim | None) -> bool:
    """Whether *prim* is a ``UsdPhysics.CollisionGroup``."""
    return prim is not None and prim.IsA(UsdPhysics.CollisionGroup)


def joint_bodies(prim: Usd.Prim) -> tuple[str | None, str | None]:
    """The prim paths ``physics:body0`` and ``physics:body1`` target; ``None`` where unset."""
    bodies: list[str | None] = []
    for name in ("physics:body0", "physics:body1"):
        rel = prim.GetRelationship(name)
        targets = rel.GetTargets() if rel else []
        bodies.append(str(targets[0]) if targets else None)
    return bodies[0], bodies[1]
