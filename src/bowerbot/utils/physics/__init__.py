# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The physics tools: UsdPhysics APIs, physics scenes, collision groups and joints.

APIs are generic over the four supported ones (RigidBody, Mass, Collision,
MeshCollision). Property names and types are discovered from the live
USD schema registry; callers pass free ``{name: value}`` dicts and the
declared types are resolved at write time.

phy.usda is composed into the asset via a reference arc (matching the
lgt/mtl/contents convention), so it sits outside the asset stage's local
LayerStack. Writes go to phy.usda opened as its own stage; the schema
registry exposes API-declared properties on Over prims after ``Apply()``.
Validation against the asset's composed types is a separate read pass.
"""

from bowerbot.utils.physics import apis
from bowerbot.utils.physics import collision_groups
from bowerbot.utils.physics import joints
from bowerbot.utils.physics import layer
from bowerbot.utils.physics import masking
from bowerbot.utils.physics import rules
from bowerbot.utils.physics import scenes
from bowerbot.utils.physics import scope
from bowerbot.utils.physics import summary

__all__ = [
    "apis",
    "collision_groups",
    "joints",
    "layer",
    "masking",
    "rules",
    "scenes",
    "scope",
    "summary",
]
