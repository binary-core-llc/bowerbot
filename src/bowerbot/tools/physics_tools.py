# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics tools — introspect, apply, remove, summarise UsdPhysics APIs."""

from __future__ import annotations

from typing import Any

from bowerbot import scene_state
from bowerbot import schemas
from bowerbot import skills
from bowerbot.services import physics_service
from bowerbot.tools import _helpers


def list_physics_api_properties(
    _state: scene_state.SceneState, params: dict[str, Any],
) -> skills.ToolResult:
    """Return live schema-registry info for a UsdPhysics applied API."""
    try:
        data = physics_service.list_physics_api_properties(_state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def apply_physics_api(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Apply a UsdPhysics applied API to a prim and author opinions."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.apply_physics_api(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def remove_physics_api(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Remove a UsdPhysics applied API from a prim."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.remove_physics_api(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def setup_physics_scene(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Create the scene's PhysicsScene singleton with gravity attributes."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.setup_physics_scene(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def list_physics_scenes(
    state: scene_state.SceneState, params: dict[str, Any],
) -> skills.ToolResult:
    """Return every UsdPhysics.Scene prim under /Scene/Physics."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.list_physics_scenes(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def remove_physics_scene(
    state: scene_state.SceneState, params: dict[str, Any],
) -> skills.ToolResult:
    """Remove a UsdPhysics.Scene prim by name."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.remove_physics_scene(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def get_physics_summary(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Return asset-side and scene-side physics opinions for a prim path."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.get_physics_summary(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def add_collider_shape(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Add a basic collider shape (box, sphere, capsule, cylinder) under a part."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.add_collider_shape(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def remove_collider_shape(
    state: scene_state.SceneState, params: dict[str, Any],
) -> skills.ToolResult:
    """Remove a collider shape added with add_collider_shape."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.remove_collider_shape(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def create_physics_material(
    state: scene_state.SceneState, params: dict[str, Any],
) -> skills.ToolResult:
    """Create a physics material (friction, bounce) and bind it to a prim."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.create_physics_material(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def bind_physics_material(
    state: scene_state.SceneState, params: dict[str, Any],
) -> skills.ToolResult:
    """Bind an existing physics material to another prim."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.bind_physics_material(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def remove_physics_material(
    state: scene_state.SceneState, params: dict[str, Any],
) -> skills.ToolResult:
    """Take the physics material off a prim."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.remove_physics_material(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def list_joint_properties(
    state: scene_state.SceneState, params: dict[str, Any],
) -> skills.ToolResult:
    """Schema-registry introspection for a typed joint prim."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.list_joint_properties(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def create_joint(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Create a typed joint connecting two bodies."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.create_joint(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def remove_joint(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Remove a joint prim (asset-level or scene-level)."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.remove_joint(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def list_joints(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """List joints scene-wide, scoped under a prim, or inside an asset folder."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.list_joints(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def create_or_update_collision_group(
    state: scene_state.SceneState, params: dict[str, Any],
) -> skills.ToolResult:
    """Create or update a UsdPhysicsCollisionGroup under /Scene/Physics/Groups."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.create_or_update_collision_group(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def remove_collision_group(
    state: scene_state.SceneState, params: dict[str, Any],
) -> skills.ToolResult:
    """Remove a collision group; refuses if other groups depend on it."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.remove_collision_group(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def list_collision_groups(
    state: scene_state.SceneState, params: dict[str, Any],
) -> skills.ToolResult:
    """List every collision group with membership, filters, and merge token."""
    if (err := _helpers.require_stage(state)):
        return err
    try:
        data = physics_service.list_collision_groups(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


_API_VALUES = [a.value for a in schemas.PhysicsApiName]
_JOINT_TYPE_VALUES = [j.value for j in schemas.PhysicsJointType]


TOOLS: list[skills.Tool] = [
    skills.Tool(
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
            "automatically with no BowerBot changes. The result also "
            "includes target_requirement (the prim type the API must "
            "target, e.g. UsdGeom.Mesh for PhysicsMeshCollisionAPI) and "
            "requires_companion_api (the API auto-applied alongside this "
            "one, e.g. PhysicsCollisionAPI for PhysicsMeshCollisionAPI, "
            "else null)."
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
                        "LimitAPI). The degree-of-freedom token. DriveAPI: "
                        "'angular' (revolute), 'linear' (prismatic). "
                        "LimitAPI: 'angular' (revolute), 'linear' "
                        "(prismatic), 'rotX'/'rotY'/'rotZ' (spherical), "
                        "'distance' (distance joint)."
                    ),
                },
            },
            "required": ["api_name"],
        },
    ),
    skills.Tool(
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
            "(disable collision on THIS chair instance only).\n\n"
            "The response reports api_name, instance_name, companion_api "
            "(the auto-applied companion, e.g. PhysicsCollisionAPI alongside "
            "PhysicsMeshCollisionAPI, else null), attributes_set, "
            "relationships_set, and scope. For asset-scope writes it also "
            "returns asset_folder, scene_prim_path, asset_prim_path, and "
            "cleared_masking_opinions (the scene.usda overrides "
            "{prim_path, kind, key} deleted when clear_masking_overrides=true, "
            "empty otherwise)."
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
                        "LimitAPI). The DOF token. DriveAPI: 'angular' "
                        "(revolute), 'linear' (prismatic). LimitAPI: "
                        "'angular' (revolute), 'linear' (prismatic), "
                        "'rotX'/'rotY'/'rotZ' (spherical), 'distance' "
                        "(distance joint)."
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
                        "paths (scene paths; each must exist). Use for "
                        "physics:filteredPairs on PhysicsFilteredPairsAPI: "
                        "the bodies or colliders this prim must not collide "
                        "with (e.g. a vehicle body and its front wheels, "
                        "which no joint connects directly). Also for "
                        "physics:simulationOwner (point at "
                        "/Scene/Physics/PhysicsScene, scope='scene' only). "
                        "With scope='asset' every target must be a prim of "
                        "the same asset. A physics material is bound with "
                        "create_physics_material, not here."
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
    skills.Tool(
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
    skills.Tool(
        name="setup_physics_scene",
        description=(
            "Create the scene's PhysicsScene singleton at "
            "/Scene/Physics/<name> with gravity attributes. Every rigid "
            "body and collider in the scene resolves its simulationOwner "
            "to a PhysicsScene; without one, the simulator picks an "
            "engine default. Call once per scene before authoring "
            "physics, unless you only need static colliders (no rigid "
            "bodies). Gravity magnitude defaults to 9.81 / the "
            "project's meters_per_unit (Earth gravity in project units); direction "
            "defaults to straight down: (0, -1, 0) in a Y-up project, (0, 0, -1) "
            "in a Z-up project. Returns prim_path and "
            "the resolved gravity_magnitude and gravity_direction actually "
            "authored (the defaults when you omit them, never null)."
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
                        "Gravity strength in project units per second "
                        "squared. Leave unset to derive 9.81 / the "
                        "project's meters_per_unit."
                    ),
                },
                "gravity_direction": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": (
                        "Unit-vector gravity direction. Defaults to "
                        "straight down along the project's up axis: "
                        "(0, -1, 0) for Y-up, (0, 0, -1) for Z-up."
                    ),
                },
            },
        },
    ),
    skills.Tool(
        name="list_physics_scenes",
        description=(
            "List every UsdPhysics.Scene prim under /Scene/Physics. "
            "Shows name, gravity magnitude, and gravity direction for "
            "each. Use to check which physics scenes exist before "
            "creating or removing one."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    skills.Tool(
        name="remove_physics_scene",
        description=(
            "Remove a UsdPhysics.Scene prim by name from /Scene/Physics. "
            "Use when the user asks to delete or clean up a physics scene."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Name of the PhysicsScene prim to remove "
                        "(e.g. 'PhysicsScene', 'PendulumPhysics')."
                    ),
                },
            },
            "required": ["name"],
        },
    ),
    skills.Tool(
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


TOOLS.append(skills.Tool(
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
TOOLS.append(skills.Tool(
    name="remove_collision_group",
    description=(
        "Remove a UsdPhysicsCollisionGroup. Refuses if other groups "
        "reference it via filteredGroups unless force=true is passed. "
        "Returns scrubbed_dangling_refs describing any now-dangling "
        "filteredGroups references BowerBot cleaned up after removal."
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
                    "this one via filteredGroups; BowerBot scrubs the "
                    "now-dangling references afterwards."
                ),
            },
        },
        "required": ["name"],
    },
))
TOOLS.append(skills.Tool(
    name="add_collider_shape",
    description=(
        "Add a basic collider shape under a part: a box, sphere, capsule "
        "or cylinder that only physics uses. USD has no setting that makes "
        "a mesh collide as a cylinder; a collider is always a geometry prim "
        "with PhysicsCollisionAPI, so this adds that prim (a UsdGeom Cube, "
        "Sphere, Capsule or Cylinder) with the collision API applied and "
        "purpose 'guide', which renders skip and the asset's box ignores. "
        "Use it when a mesh's own shape collides badly: a tire as a convex "
        "hull rolls like a polygon, a cylinder rolls smoothly.\n\n"
        "prim_path is the PART the shape goes under (an Xform that groups "
        "geometry, e.g. a wheel), not the mesh: the shape then moves with "
        "that part and belongs to its rigid body. Sizes and the offset are "
        "in project units, measured in the world; axis and the offset "
        "follow the part's own axes.\n\n"
        "Each shape takes its own sizes and no others: box -> size_x, "
        "size_y, size_z; sphere -> radius; capsule and cylinder -> radius, "
        "height, axis. USD's physics rules apply: a sphere, capsule or "
        "cylinder under a part with non-uniform scale is REFUSED (a box is "
        "fine).\n\n"
        "The mesh under the part keeps colliding if it has "
        "PhysicsCollisionAPI: remove that with remove_physics_api so only "
        "the shape collides.\n\n"
        "scope='asset' writes the shape into the asset's phy.usda, so every "
        "placement of the asset has it. scope='scene' writes it into "
        "scene.usda for this placement only. Omit scope to auto-detect."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prim_path": {
                "type": "string",
                "description": (
                    "Scene prim path of the part the shape goes under "
                    "(e.g. /Scene/Props/Tractor_01/asset/wheel_front_L)."
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "Name of the new collider prim under the part "
                    "(e.g. 'collider'). Must be a valid USD prim name "
                    "and not taken."
                ),
            },
            "shape": {
                "type": "string",
                "enum": ["box", "sphere", "capsule", "cylinder"],
                "description": "Which basic shape the collider is.",
            },
            "radius": {
                "type": "number",
                "description": "sphere, capsule, cylinder: radius in project units.",
            },
            "height": {
                "type": "number",
                "description": (
                    "capsule, cylinder: length along the axis in project "
                    "units (for a capsule, without its two round caps)."
                ),
            },
            "axis": {
                "type": "string",
                "enum": ["X", "Y", "Z"],
                "description": (
                    "capsule, cylinder: which of the PART's own axes the "
                    "shape runs along (a wheel's axle axis)."
                ),
            },
            "size_x": {"type": "number", "description": "box: width in project units."},
            "size_y": {"type": "number", "description": "box: size along Y in project units."},
            "size_z": {"type": "number", "description": "box: size along Z in project units."},
            "translate_x": {
                "type": "number",
                "description": "Offset from the part's origin along its X, in project units.",
            },
            "translate_y": {
                "type": "number",
                "description": "Offset from the part's origin along its Y, in project units.",
            },
            "translate_z": {
                "type": "number",
                "description": "Offset from the part's origin along its Z, in project units.",
            },
            "scope": {
                "type": "string",
                "enum": ["asset", "scene"],
                "description": (
                    "Where to write the shape. Omit to auto-detect: asset "
                    "scope for a part of a placed asset, scene otherwise."
                ),
            },
        },
        "required": ["prim_path", "name", "shape"],
    },
))
TOOLS.append(skills.Tool(
    name="remove_collider_shape",
    description=(
        "Remove a collider shape added with add_collider_shape, from "
        "wherever it was written (scene.usda or the asset's phy.usda). "
        "Only removes those shapes: a prim from the asset's own geometry "
        "is REFUSED; to stop a mesh from colliding use remove_physics_api "
        "with PhysicsCollisionAPI. A path with nothing at it answers "
        "removed: false."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prim_path": {
                "type": "string",
                "description": (
                    "Scene prim path of the collider shape, as returned "
                    "by add_collider_shape."
                ),
            },
        },
        "required": ["prim_path"],
    },
))
_PHYSICS_MATERIAL_SCOPE = {
    "type": "string",
    "enum": ["asset", "scene"],
    "description": (
        "Where to write it. scope='asset': the asset's phy.usda, so every "
        "placement of the asset has it. scope='scene': scene.usda, for "
        "this placement only (the material lives under /Scene/Physics). "
        "Omit to auto-detect."
    ),
}
TOOLS.append(skills.Tool(
    name="create_physics_material",
    description=(
        "Create a physics material and bind it to a prim: how much the "
        "surface grips (friction) and bounces (restitution). Without one a "
        "collider has no friction of its own and the simulator falls back "
        "to its defaults. Authors a Material prim with PhysicsMaterialAPI "
        "and binds it with the 'physics' purpose "
        "(material:binding:physics).\n\n"
        "prim_path is a collider, or a part above colliders: every "
        "collider at or under it uses the material. Bind it to a wheel "
        "part and both its tire mesh and its collider shape get it. The "
        "look the prim renders with is a different binding and is not "
        "touched.\n\n"
        "The numbers have no unit. static_friction resists starting to "
        "slide, dynamic_friction resists sliding (usually a little lower); "
        "typical values: rubber on dry ground about 0.8-1.0, ice about "
        "0.05. restitution is the bounce, 0 (none) to 1 (full).\n\n"
        "Calling it again with the same material_name updates that "
        "material's values. To put an existing material on another prim "
        "use bind_physics_material. Mass is not set here: use "
        "PhysicsMassAPI."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prim_path": {
                "type": "string",
                "description": (
                    "Scene prim path of the collider, or of a part above "
                    "colliders, the material is bound to."
                ),
            },
            "material_name": {
                "type": "string",
                "description": "Name of the physics material (e.g. 'rubber').",
            },
            "static_friction": {
                "type": "number",
                "description": "Grip against starting to slide; 0 or more.",
            },
            "dynamic_friction": {
                "type": "number",
                "description": "Grip while sliding; 0 or more.",
            },
            "restitution": {
                "type": "number",
                "description": "Bounce, from 0 (none) to 1 (full). Left out: 0.",
            },
            "scope": _PHYSICS_MATERIAL_SCOPE,
        },
        "required": ["prim_path", "material_name", "static_friction", "dynamic_friction"],
    },
))
TOOLS.append(skills.Tool(
    name="bind_physics_material",
    description=(
        "Bind a physics material that already exists to another prim "
        "(a collider, or a part above colliders). The material is looked "
        "up by name where the scope keeps it: scope='asset' in this "
        "asset's phy.usda, scope='scene' under /Scene/Physics. "
        "get_physics_summary shows the materials there are. A name that "
        "does not exist is REFUSED: create it with "
        "create_physics_material."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prim_path": {
                "type": "string",
                "description": "Scene prim path the material is bound to.",
            },
            "material_name": {
                "type": "string",
                "description": "Name of an existing physics material.",
            },
            "scope": _PHYSICS_MATERIAL_SCOPE,
        },
        "required": ["prim_path", "material_name"],
    },
))
TOOLS.append(skills.Tool(
    name="remove_physics_material",
    description=(
        "Take the physics material off a prim, wherever the binding was "
        "written (scene.usda or the asset's phy.usda). The material "
        "itself is deleted too once nothing else binds it. The look the "
        "prim renders with is not touched. A prim with no physics "
        "material binding of its own answers removed: false."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prim_path": {
                "type": "string",
                "description": "Scene prim path that carries the binding.",
            },
        },
        "required": ["prim_path"],
    },
))
TOOLS.append(skills.Tool(
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
TOOLS.append(skills.Tool(
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
        "must be an enabled rigid body itself: PhysicsRigidBodyAPI on "
        "that prim, not on a prim above it (USD's own rule; a part "
        "under a rigid body does not count, name the body). The "
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
                    "carry PhysicsRigidBodyAPI itself."
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
TOOLS.append(skills.Tool(
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
TOOLS.append(skills.Tool(
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
TOOLS.append(skills.Tool(
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
    "list_physics_scenes": list_physics_scenes,
    "remove_physics_scene": remove_physics_scene,
    "get_physics_summary": get_physics_summary,
    "create_or_update_collision_group": create_or_update_collision_group,
    "remove_collision_group": remove_collision_group,
    "list_collision_groups": list_collision_groups,
    "add_collider_shape": add_collider_shape,
    "remove_collider_shape": remove_collider_shape,
    "create_physics_material": create_physics_material,
    "bind_physics_material": bind_physics_material,
    "remove_physics_material": remove_physics_material,
    "list_joint_properties": list_joint_properties,
    "create_joint": create_joint,
    "remove_joint": remove_joint,
    "list_joints": list_joints,
}
