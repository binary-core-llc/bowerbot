# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics tools — introspect, apply, remove, summarise UsdPhysics APIs."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import PhysicsApiName, PhysicsJointType
from bowerbot.services import physics_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage


def list_physics_api_properties(
    _state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Return live schema-registry info for a UsdPhysics applied API."""
    try:
        data = physics_service.list_physics_api_properties(_state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def apply_physics_api(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Apply a UsdPhysics applied API to a prim and author opinions."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.apply_physics_api(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def remove_physics_api(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove a UsdPhysics applied API from a prim."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.remove_physics_api(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def setup_physics_scene(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Create the scene's PhysicsScene singleton with gravity attributes."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.setup_physics_scene(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def get_physics_summary(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Return asset-side and scene-side physics opinions for a prim path."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.get_physics_summary(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def list_joint_properties(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Schema-registry introspection for a typed joint prim."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.list_joint_properties(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def create_joint(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Create a typed joint connecting two bodies."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.create_joint(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def remove_joint(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove a joint prim (asset-level or scene-level)."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.remove_joint(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def list_joints(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List joints scene-wide, scoped under a prim, or inside an asset folder."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.list_joints(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def create_or_update_collision_group(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Create or update a UsdPhysicsCollisionGroup under /Scene/Physics/Groups."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.create_or_update_collision_group(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def remove_collision_group(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Remove a collision group; refuses if other groups depend on it."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.remove_collision_group(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def list_collision_groups(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """List every collision group with membership, filters, and merge token."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.list_collision_groups(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


_API_VALUES = [a.value for a in PhysicsApiName]
_JOINT_TYPE_VALUES = [j.value for j in PhysicsJointType]


TOOLS: list[Tool] = [
    Tool(
        name="list_physics_api_properties",
        description=(
            "Discover the attributes and relationships a UsdPhysics applied "
            "API declares. Returns each property's name, kind "
            "(attribute/relationship), USD type, default, and allowed "
            "tokens (e.g. the convexHull/convexDecomposition/none set on "
            "PhysicsMeshCollisionAPI). ALWAYS call this before "
            "apply_physics_api so you know which property names are valid "
            "and what types to pass. Property names come from the live USD "
            "schema registry, so new OpenUSD attributes are picked up "
            "automatically with no BowerBot changes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "api_name": {
                    "type": "string",
                    "enum": _API_VALUES,
                    "description": (
                        "Which UsdPhysics applied API to introspect. "
                        "PhysicsRigidBodyAPI, PhysicsMassAPI, "
                        "PhysicsCollisionAPI, PhysicsMeshCollisionAPI, "
                        "PhysicsArticulationRootAPI, PhysicsDriveAPI "
                        "(multi-apply: motor/spring on joints), "
                        "PhysicsLimitAPI (multi-apply: angle/distance "
                        "limits on joints)."
                    ),
                },
                "instance_name": {
                    "type": "string",
                    "description": (
                        "Required for multi-apply APIs (DriveAPI, "
                        "LimitAPI). The degree-of-freedom token: "
                        "'angular' (revolute), 'linear' (prismatic), "
                        "'rotX'/'rotY'/'rotZ'/'transX'/'transY'/"
                        "'transZ' (D6), 'distance' (distance joint)."
                    ),
                },
            },
            "required": ["api_name"],
        },
    ),
    Tool(
        name="apply_physics_api",
        description=(
            "Apply a UsdPhysics applied API to a prim and author the "
            "attribute / relationship opinions you pass in. Property names "
            "in `attributes` and `relationships` must come from "
            "list_physics_api_properties for the same api_name; unknown "
            "names are refused.\n\n"
            "Prim-type rules (per UsdPhysics spec, enforced):\n"
            "- PhysicsCollisionAPI requires a UsdGeom.Gprim (Mesh, Sphere, "
            "Cube, Cylinder, Cone, Capsule, Plane). Applying to an Xform "
            "is invalid.\n"
            "- PhysicsMeshCollisionAPI requires a UsdGeom.Mesh and "
            "auto-applies PhysicsCollisionAPI alongside it.\n"
            "- PhysicsRigidBodyAPI / PhysicsMassAPI require a "
            "UsdGeom.Xformable.\n\n"
            "If you pass an Xform whose subtree contains a unique prim "
            "of the required type, BowerBot resolves to that descendant "
            "automatically and returns both `prim_path` (resolved) and "
            "`requested_prim_path`. PhysicsScene is auto-ensured.\n\n"
            "LOAD-BEARING: when adding collision to a Mesh under a "
            "dynamic or kinematic PhysicsRigidBodyAPI subtree, you "
            "MUST use api_name='PhysicsMeshCollisionAPI' with "
            "attributes={'physics:approximation': 'convexHull'} (or "
            "convexDecomposition / boundingCube / boundingSphere / "
            "meshSimplification). Bare PhysicsCollisionAPI leaves "
            "approximation at 'none', which the solver refuses on "
            "dynamic bodies — the scene appears authored but does not "
            "simulate. 'none' is ONLY valid for static colliders "
            "(no ancestor PhysicsRigidBodyAPI), where it gives "
            "mesh-accurate collision for terrain / walls / ground "
            "planes. Default to convexHull unless the user specifies "
            "another approximation.\n\n"
            "Omit `scope` to auto-detect. Pass `scope='scene'` "
            "explicitly only for a per-placement override on an asset "
            "(disable collision on THIS chair instance only)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Scene-namespace prim path. For scope=asset the "
                        "path must resolve to a prim inside an asset "
                        "placement (e.g. /Scene/Models/Chair_01/asset/Body "
                        "or /Scene/Models/Chair_01 itself); BowerBot "
                        "translates it to the asset's local namespace "
                        "before writing phy.usda. For scope=scene any "
                        "prim in the open scene is valid."
                    ),
                },
                "api_name": {
                    "type": "string",
                    "enum": _API_VALUES,
                    "description": "Which UsdPhysics applied API to apply.",
                },
                "instance_name": {
                    "type": "string",
                    "description": (
                        "Required for multi-apply APIs (DriveAPI, "
                        "LimitAPI). The DOF token: 'angular' "
                        "(revolute), 'linear' (prismatic), "
                        "'rotX'/'rotY'/'rotZ'/'transX'/'transY'/"
                        "'transZ' (D6), 'distance' (distance joint)."
                    ),
                },
                "attributes": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": (
                        "Map of attribute name -> value. Names must be "
                        "the schema property names from "
                        "list_physics_api_properties (e.g. "
                        "'physics:kinematicEnabled', "
                        "'physics:approximation', 'physics:mass'). Values "
                        "are cast to the declared USD type at write time."
                    ),
                },
                "relationships": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "description": (
                        "Map of relationship name -> list of target prim "
                        "paths. Use for physics:simulationOwner (point at "
                        "/Scene/Physics/PhysicsScene) or "
                        "material:binding:physics."
                    ),
                },
                "scope": {
                    "type": "string",
                    "enum": ["asset", "scene"],
                    "description": (
                        "Optional. Omit to auto-detect: asset placements "
                        "write to phy.usda, scene-authored prims write "
                        "to scene.usda. Pass 'scene' explicitly only "
                        "for a per-instance override on an asset "
                        "placement (affects only this instance)."
                    ),
                },
                "clear_masking_overrides": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "scope=asset only. If true, drop any scene.usda "
                        "opinion that would mask this phy.usda write, "
                        "then proceed. Use when a DCC override was "
                        "accidental and should be erased."
                    ),
                },
                "confirm_masked": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "scope=asset only. If true, write phy.usda anyway "
                        "even when scene.usda has masking opinions; "
                        "scene overrides keep winning on those "
                        "placements. Use when overrides are intentional "
                        "and you only want to change the asset default."
                    ),
                },
            },
            "required": ["prim_path", "api_name"],
        },
    ),
    Tool(
        name="remove_physics_api",
        description=(
            "Remove a UsdPhysics applied API and its authored opinions "
            "from a prim. Dropping PhysicsCollisionAPI cascades to "
            "PhysicsMeshCollisionAPI automatically. scope routing and "
            "masking flags mirror apply_physics_api."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": "Scene prim path the API was applied to.",
                },
                "api_name": {
                    "type": "string",
                    "enum": _API_VALUES,
                    "description": "Which UsdPhysics applied API to remove.",
                },
                "instance_name": {
                    "type": "string",
                    "description": (
                        "Required for multi-apply APIs (DriveAPI, "
                        "LimitAPI). Must match the instance_name "
                        "used in apply_physics_api."
                    ),
                },
                "scope": {
                    "type": "string",
                    "enum": ["asset", "scene"],
                    "description": (
                        "Optional. Omit to auto-detect (same rule as "
                        "apply_physics_api). Pass 'scene' to remove only "
                        "the per-instance override; 'asset' to remove "
                        "from the shared phy.usda."
                    ),
                },
                "clear_masking_overrides": {
                    "type": "boolean",
                    "default": False,
                    "description": "scope=asset only. See apply_physics_api.",
                },
                "confirm_masked": {
                    "type": "boolean",
                    "default": False,
                    "description": "scope=asset only. See apply_physics_api.",
                },
            },
            "required": ["prim_path", "api_name"],
        },
    ),
    Tool(
        name="setup_physics_scene",
        description=(
            "Create the scene's PhysicsScene singleton at "
            "/Scene/Physics/<name> with gravity attributes. Every rigid "
            "body and collider in the scene resolves its simulationOwner "
            "to a PhysicsScene; without one, the simulator picks an "
            "engine default. Call once per scene before authoring "
            "physics, unless you only need static colliders (no rigid "
            "bodies). Gravity magnitude defaults to 9.81 / "
            "metersPerUnit (Earth gravity in stage units); direction "
            "defaults to (0, -1, 0) (negative Y)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "default": "PhysicsScene",
                    "description": (
                        "Child name under /Scene/Physics. Use multiple "
                        "names to model different gravity worlds in one "
                        "scene (e.g. 'Earth' and 'Moon')."
                    ),
                },
                "gravity_magnitude": {
                    "type": "number",
                    "description": (
                        "Gravity strength in stage units per second "
                        "squared. Leave unset to derive 9.81 / "
                        "metersPerUnit from the stage."
                    ),
                },
                "gravity_direction": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": (
                        "Unit-vector gravity direction. Defaults to "
                        "(0, -1, 0) which matches USD's Y-up convention."
                    ),
                },
            },
        },
    ),
    Tool(
        name="get_physics_summary",
        description=(
            "Inspect every authored physics opinion on a prim and its "
            "descendants. Returns two sections: 'asset' (phy.usda "
            "opinions, when the prim is inside an asset placement) and "
            "'scene' (scene.usda opinions on the same path). Use to "
            "check what's already authored before applying new APIs, or "
            "to debug why a placement behaves differently from its asset "
            "default (scene.usda override masking phy.usda)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Scene prim path to inspect. Reports asset-side "
                        "opinions when the path is inside an asset; "
                        "scene-side opinions are always reported."
                    ),
                },
            },
            "required": ["prim_path"],
        },
    ),
]


TOOLS.append(Tool(
    name="create_or_update_collision_group",
    description=(
        "Create or update a UsdPhysicsCollisionGroup typed prim at "
        "/Scene/Physics/<name>, as a flat sibling of the PhysicsScene "
        "prim (matches the Pixar / Omniverse canonical layout). "
        "Collision groups declare WHICH colliders are in the group "
        "(via a UsdCollectionAPI on the group itself, NOT via an "
        "applied API on each collider) and WHICH other groups they "
        "refuse to collide with. Use for scenarios like 'players "
        "collide with terrain but not each other', 'trigger volumes "
        "don't physically collide', 'UI props don't interact with "
        "anything'.\n\n"
        "Each list-shaped arg REPLACES the existing value when given "
        "(omit to leave unchanged on an existing group). The "
        "filtered_groups arg accepts bare group names; they resolve "
        "to /Scene/Physics/<name>. Any group named there must "
        "already exist; create it first if needed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Group name (e.g. 'Players', 'Terrain'). Becomes "
                    "the child name under /Scene/Physics (flat sibling "
                    "of /Scene/Physics/PhysicsScene)."
                ),
            },
            "includes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Scene prim paths to add to the group's colliders "
                    "collection (UsdCollectionAPI includes rel). "
                    "Replaces the existing list."
                ),
            },
            "excludes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Scene prim paths excluded from the colliders "
                    "collection. Replaces the existing list."
                ),
            },
            "filtered_groups": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Other group names this group does NOT collide "
                    "with. Resolved to /Scene/Physics/<name>. Refuses "
                    "if any named group does not exist."
                ),
            },
            "invert_filter": {
                "type": "boolean",
                "description": (
                    "When true, filtered_groups means 'ONLY collide "
                    "with these groups' instead of the default 'do NOT "
                    "collide with these groups'."
                ),
            },
            "merge_group": {
                "type": "string",
                "description": (
                    "Token that groups multiple CollisionGroup prims "
                    "into one filtering unit. Optional."
                ),
            },
        },
        "required": ["name"],
    },
))
TOOLS.append(Tool(
    name="remove_collision_group",
    description=(
        "Remove a UsdPhysicsCollisionGroup. Refuses if other groups "
        "reference it via filteredGroups (would leave dangling "
        "relationships) unless force=true is passed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Group name under /Scene/Physics.",
            },
            "force": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Remove even when other groups still reference "
                    "this one via filteredGroups. Dangling rels "
                    "are left behind."
                ),
            },
        },
        "required": ["name"],
    },
))
TOOLS.append(Tool(
    name="list_joint_properties",
    description=(
        "Schema-registry introspection for a UsdPhysics typed joint "
        "prim. Returns every attribute and relationship the joint "
        "type declares with name, USD type, default, and allowed "
        "tokens. ALWAYS call this before create_joint so you know "
        "what attributes the joint accepts (e.g. RevoluteJoint has "
        "physics:axis, physics:lowerLimit, physics:upperLimit; "
        "DistanceJoint has physics:minDistance / maxDistance)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "joint_type": {
                "type": "string",
                "enum": _JOINT_TYPE_VALUES,
                "description": "Which typed joint to introspect.",
            },
        },
        "required": ["joint_type"],
    },
))
TOOLS.append(Tool(
    name="create_joint",
    description=(
        "Create a typed UsdPhysics joint connecting two bodies. "
        "Joints are typed prims (not applied APIs); supported types: "
        "PhysicsRevoluteJoint (hinge, 1 angular DOF), "
        "PhysicsPrismaticJoint (slider, 1 linear DOF), "
        "PhysicsSphericalJoint (ball-and-socket, 3 angular DOFs with "
        "cone limit), PhysicsFixedJoint (rigid weld, 0 DOFs), "
        "PhysicsDistanceJoint (constrains distance between two "
        "points).\n\n"
        "body0 and body1 reference scene prim paths. At least one "
        "must reach PhysicsRigidBodyAPI (self or ancestor); the "
        "other can be world-static (set to empty / omit to mean "
        "'attach to world'). Convention is body0=parent, body1=child "
        "for articulated chains. Both must be UsdGeom.Xformable.\n\n"
        "scope='asset' (default 'scene'): writes the joint into the "
        "asset's phy.usda at /<defaultPrim>/joints/<name>. Used for "
        "asset-internal articulations (robot arm, character, door). "
        "Requires either body0 or body1 (or asset_anchor_prim_path) "
        "to be inside an asset placement so BowerBot can find the "
        "asset folder. body0/body1 are translated to asset-local "
        "namespace before writing.\n\n"
        "scope='scene' (default): writes the joint into scene.usda "
        "at /Scene/Physics/<name> as a flat sibling of PhysicsScene "
        "and collision groups. Used for joints that span two "
        "separate assets (e.g. welding a hook on asset A to a chain "
        "on asset B). body0/body1 are absolute scene paths.\n\n"
        "Call list_joint_properties(joint_type) first to learn which "
        "attributes the joint accepts. body0/body1 attributes are "
        "set via the dedicated body0/body1 params here, not via the "
        "attributes dict."
    ),
    parameters={
        "type": "object",
        "properties": {
            "joint_type": {
                "type": "string",
                "enum": _JOINT_TYPE_VALUES,
                "description": "Which typed joint to create.",
            },
            "name": {
                "type": "string",
                "description": (
                    "Joint name (e.g. 'elbow', 'door_hinge'). "
                    "Becomes the prim's leaf name."
                ),
            },
            "body0": {
                "type": "string",
                "description": (
                    "Scene prim path of body0 (parent in articulated "
                    "chains). Empty/omitted means 'world'. Must be "
                    "Xformable; at least one of body0/body1 must "
                    "reach PhysicsRigidBodyAPI."
                ),
            },
            "body1": {
                "type": "string",
                "description": (
                    "Scene prim path of body1 (child in articulated "
                    "chains). Empty/omitted means 'world'. Same type "
                    "and RigidBody constraints as body0."
                ),
            },
            "scope": {
                "type": "string",
                "enum": ["asset", "scene"],
                "default": "scene",
                "description": (
                    "'asset' writes inside the asset's phy.usda "
                    "(asset-internal articulations). 'scene' writes "
                    "into scene.usda (joints between separate assets "
                    "or to scene-only prims)."
                ),
            },
            "asset_anchor_prim_path": {
                "type": "string",
                "description": (
                    "scope='asset' only. If body0 and body1 are both "
                    "empty (world-attach), provide any scene prim "
                    "path inside the asset placement so BowerBot can "
                    "locate the asset folder."
                ),
            },
            "attributes": {
                "type": "object",
                "additionalProperties": True,
                "description": (
                    "Map of joint attribute name -> value (e.g. "
                    "'physics:axis': 'Y', 'physics:lowerLimit': "
                    "-90.0). Names must come from "
                    "list_joint_properties for the same joint_type. "
                    "Do NOT set physics:body0 / physics:body1 here; "
                    "use the dedicated body0/body1 params."
                ),
            },
        },
        "required": ["joint_type", "name"],
    },
))
TOOLS.append(Tool(
    name="remove_joint",
    description=(
        "Remove a typed joint prim. For scope='scene', pass the "
        "full prim_path. For scope='asset', pass the joint name "
        "plus asset_anchor_prim_path (a scene placement of the "
        "asset). Joints are leaves (no cascade); ArticulationRootAPI "
        "is independent and is not affected by joint removal."
    ),
    parameters={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["asset", "scene"],
                "default": "scene",
            },
            "prim_path": {
                "type": "string",
                "description": (
                    "scope='scene': full scene prim path of the joint "
                    "(e.g. /Scene/Physics/door_hinge)."
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "scope='asset': joint name under "
                    "/<defaultPrim>/joints/<name>."
                ),
            },
            "asset_anchor_prim_path": {
                "type": "string",
                "description": (
                    "scope='asset': any scene placement path inside "
                    "the target asset so BowerBot can locate the "
                    "asset folder."
                ),
            },
        },
    },
))
TOOLS.append(Tool(
    name="list_joints",
    description=(
        "List every typed joint prim. For scope='scene', returns "
        "joints found across the open scene (optionally under a "
        "specific prim via under_prim_path). For scope='asset', "
        "returns joints in the asset's phy.usda (requires "
        "asset_anchor_prim_path to locate the asset folder). Each "
        "joint entry includes joint_type, body0, body1, authored "
        "attributes, and applied APIs (e.g. DriveAPI / LimitAPI "
        "instances once those land)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["asset", "scene"],
                "default": "scene",
            },
            "under_prim_path": {
                "type": "string",
                "description": (
                    "scope='scene' only: restrict listing to "
                    "descendants of this prim. Default is scene root."
                ),
            },
            "asset_anchor_prim_path": {
                "type": "string",
                "description": (
                    "scope='asset' only: any scene placement path "
                    "inside the target asset."
                ),
            },
        },
    },
))
TOOLS.append(Tool(
    name="list_collision_groups",
    description=(
        "Return every UsdPhysicsCollisionGroup under /Scene/Physics "
        "(flat siblings of the PhysicsScene prim) with its membership "
        "(includes / excludes), filtered_groups, invert_filter, and "
        "merge_group token. Use before authoring filters to know "
        "which group names exist."
    ),
    parameters={"type": "object", "properties": {}},
))


HANDLERS = {
    "list_physics_api_properties": list_physics_api_properties,
    "apply_physics_api": apply_physics_api,
    "remove_physics_api": remove_physics_api,
    "setup_physics_scene": setup_physics_scene,
    "get_physics_summary": get_physics_summary,
    "create_or_update_collision_group": create_or_update_collision_group,
    "remove_collision_group": remove_collision_group,
    "list_collision_groups": list_collision_groups,
    "list_joint_properties": list_joint_properties,
    "create_joint": create_joint,
    "remove_joint": remove_joint,
    "list_joints": list_joints,
}
