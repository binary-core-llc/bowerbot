# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics: physics scenes, APIs at asset and scene scope, joints, collision groups."""

from __future__ import annotations

from tests.golden.model import Scenario, Step, at

API_NAMES = ("PhysicsRigidBodyAPI", "PhysicsMassAPI", "PhysicsCollisionAPI",
             "PhysicsMeshCollisionAPI", "PhysicsArticulationRootAPI", "PhysicsDriveAPI",
             "PhysicsLimitAPI")
JOINT_TYPES = ("PhysicsRevoluteJoint", "PhysicsPrismaticJoint", "PhysicsSphericalJoint",
               "PhysicsFixedJoint", "PhysicsDistanceJoint")


def _place(asset: str, name: str, x: float = 0.0, save: str | None = None) -> Step:
    return Step(
        "place_asset",
        {"asset_file_path": f"$lib/{asset}", "asset_name": name, "group": "Props", **at(x)},
        save=save, note=f"place {asset} as {name}",
    )


def _api(prim: str, api: str, note: str = "", **extra: object) -> Step:
    return Step("apply_physics_api", {"prim_path": prim, "api_name": api, **extra},
                note=note or f"apply {api} to {prim}")


SCENARIOS = (
    Scenario(
        "physics/scene",
        "The physics scene: create, adjust, list, remove.",
        (
            Step("list_physics_scenes", note="none yet"),
            Step("setup_physics_scene", note="the default physics scene"),
            Step("setup_physics_scene", {"gravity_magnitude": 5.0,
                                         "gravity_direction": [0, -1, 0]},
                 note="adjust gravity"),
            Step("setup_physics_scene", {"name": "Space", "gravity_magnitude": 0.0},
                 note="a second scene"),
            Step("list_physics_scenes"),
            Step("remove_physics_scene", {"name": "Space"}),
            Step("remove_physics_scene", {"name": "Nope"}),
        ),
    ),
    Scenario(
        "physics/asset_apis",
        "Physics APIs authored in the asset (shared by every placement) and removed again.",
        (
            _place("crate.usda", "Crate", save="crate"),
            _place("crate.usda", "Crate", 2.0, save="crate_2"),
            _api("$crate/asset", "PhysicsRigidBodyAPI", note="a rigid body on the crate"),
            _api("$crate/asset/Box", "PhysicsCollisionAPI", note="a collider on the box"),
            _api("$crate/asset", "PhysicsMassAPI", attributes={"physics:mass": 12.5},
                 note="a mass of 12.5"),
            Step("get_physics_summary", {"prim_path": "$crate"}),
            Step("get_physics_summary", {"prim_path": "$crate_2"},
                 note="the second crate shares it"),
            Step("remove_physics_api",
                 {"prim_path": "$crate/asset", "api_name": "PhysicsMassAPI"}),
            Step("remove_physics_api",
                 {"prim_path": "$crate/asset", "api_name": "PhysicsRigidBodyAPI"}),
            Step("remove_physics_api",
                 {"prim_path": "$crate/asset/Box", "api_name": "PhysicsCollisionAPI"},
                 note="the last one: does phy.usda go?"),
        ),
    ),
    Scenario(
        "physics/scene_scope_override",
        "A physics API on one placement only (scene scope), next to the asset's own.",
        (
            _place("crate.usda", "Crate", save="crate"),
            _place("crate.usda", "Crate", 2.0, save="crate_2"),
            _api("$crate/asset", "PhysicsRigidBodyAPI", note="rigid body for every crate"),
            _api("$crate_2/asset", "PhysicsMassAPI", scope="scene",
                 attributes={"physics:mass": 50.0}, note="a heavier mass on crate 2 only"),
            Step("get_physics_summary", {"prim_path": "$crate_2"}),
            Step("remove_physics_api",
                 {"prim_path": "$crate_2/asset", "api_name": "PhysicsMassAPI", "scope": "scene"}),
        ),
    ),
    Scenario(
        "physics/joints",
        "Joints between two placements (scene) and between parts of one asset (asset).",
        (
            _place("table.usda", "Table", save="table"),
            _place("crate.usda", "Crate", 2.0, save="crate"),
            _api("$table/asset", "PhysicsRigidBodyAPI"),
            _api("$crate/asset", "PhysicsRigidBodyAPI"),
            Step("create_joint", {"joint_type": "PhysicsFixedJoint", "name": "Weld",
                                  "body0": "$table", "body1": "$crate", "scope": "scene"},
                 note="weld the crate to the table"),
            Step("create_joint", {"joint_type": "PhysicsRevoluteJoint", "name": "Hinge",
                                  "body0": "$table/asset/Top", "body1": "$table/asset/Leg_L",
                                  "scope": "asset",
                                  "attributes": {"physics:axis": "Y"}},
                 note="a hinge between two parts of the table"),
            Step("list_joints", {"scope": "scene"}),
            Step("list_joints", {"scope": "asset", "asset_anchor_prim_path": "$table"}),
            Step("create_joint", {"joint_type": "PhysicsFixedJoint", "name": "Weld",
                                  "body0": "$table", "body1": "$crate", "scope": "scene"},
                 note="a taken name"),
            _api("/Scene/Physics/Weld", "PhysicsLimitAPI", instance_name="rotX",
                 note="a limit on a typed joint"),
            Step("remove_joint", {"scope": "scene", "prim_path": "/Scene/Physics/Weld"}),
            Step("remove_joint", {"scope": "asset", "name": "Hinge",
                                  "asset_anchor_prim_path": "$table"}),
            Step("remove_prim", {"prim_path": "$crate"},
                 note="remove a body the removed joint used"),
        ),
    ),
    Scenario(
        "physics/collision_groups",
        "Collision groups: create, filter, update, remove.",
        (
            _place("crate.usda", "Crate", save="crate"),
            _place("table.usda", "Table", 2.0, save="table"),
            Step("create_or_update_collision_group",
                 {"name": "Boxes", "includes": ["$crate"]}),
            Step("create_or_update_collision_group",
                 {"name": "Furniture", "includes": ["$table"], "filtered_groups": ["Boxes"]},
                 note="furniture ignores boxes"),
            Step("create_or_update_collision_group",
                 {"name": "Boxes", "excludes": ["$crate/asset/Box"]}, note="update a group"),
            Step("list_collision_groups"),
            Step("remove_collision_group", {"name": "Boxes"},
                 note="a group another group filters"),
            Step("remove_collision_group", {"name": "Boxes", "force": True}),
            Step("remove_collision_group", {"name": "Nope"}),
        ),
    ),
    Scenario(
        "physics/properties_and_refusals",
        "Physics property listings, and physics calls that cannot work.",
        tuple(
            Step("list_physics_api_properties", {"api_name": name}) for name in API_NAMES
        ) + tuple(
            Step("list_joint_properties", {"joint_type": kind}) for kind in JOINT_TYPES
        ) + (
            _place("crate.usda", "Crate", save="crate"),
            _api("$crate/asset", "PhysicsMassAPI", attributes={"physics:mass": -3.0},
                 note="a negative mass"),
            _api("$crate/asset", "PhysicsRigidBodyAPI", attributes={"physics:nope": 1},
                 note="an attribute the API does not have"),
            _api("/Scene/Nope", "PhysicsRigidBodyAPI", note="a prim that does not exist"),
            Step("create_joint", {"joint_type": "PhysicsFixedJoint", "name": "J",
                                  "body0": "$crate", "body1": "/Scene/Nope", "scope": "scene"},
                 note="a body that does not exist"),
            Step("remove_joint", {"scope": "scene", "prim_path": "/Scene/Physics/Nope"}),
            Step("get_physics_summary", {"prim_path": "/Scene/Nope"}),
            Step("list_joints"),
            Step("list_collision_groups"),
        ),
    ),
)
