# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics tools — introspect, apply, remove, summarise UsdPhysics APIs."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import PhysicsApiName
from bowerbot.services import physics_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage


def list_physics_api_properties(
    _state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Return live schema-registry info for a UsdPhysics applied API."""
    try:
        data = physics_service.list_api_properties(_state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def apply_physics_api(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Apply a UsdPhysics applied API to a prim and author opinions."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.apply_api(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def remove_physics_api(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove a UsdPhysics applied API from a prim."""
    if (err := require_stage(state)):
        return err
    try:
        data = physics_service.remove_api(state, params)
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


_API_VALUES = [a.value for a in PhysicsApiName]


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
                        "PhysicsRigidBodyAPI for rigid bodies, "
                        "PhysicsMassAPI for mass/density/COM, "
                        "PhysicsCollisionAPI for colliders, "
                        "PhysicsMeshCollisionAPI for mesh-collision "
                        "approximation choice."
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
            "scope='asset' (default): writes to the asset's phy.usda so "
            "every placement of the asset inherits the opinion. Refuses "
            "if scene.usda already has authored opinions on the same "
            "prim+attribute (see clear_masking_overrides / "
            "confirm_masked). Use this for the asset's natural defaults "
            "(this chair has collision, this barrel is a rigid body).\n\n"
            "scope='scene': writes directly to scene.usda on the given "
            "prim_path. Use for per-placement overrides (disable "
            "collision on THIS chair instance only) or for physics on "
            "scene-only prims that have no asset folder."
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
                    "default": "asset",
                    "description": (
                        "'asset' writes to phy.usda (affects every "
                        "placement). 'scene' writes per-placement to "
                        "scene.usda (affects only this instance)."
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
                "scope": {
                    "type": "string",
                    "enum": ["asset", "scene"],
                    "default": "asset",
                    "description": (
                        "'asset' removes from phy.usda. 'scene' removes "
                        "scene.usda overrides on this placement."
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


HANDLERS = {
    "list_physics_api_properties": list_physics_api_properties,
    "apply_physics_api": apply_physics_api,
    "remove_physics_api": remove_physics_api,
    "setup_physics_scene": setup_physics_scene,
    "get_physics_summary": get_physics_summary,
}
