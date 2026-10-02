# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics: physics scenes, APIs at asset and scene scope, joints, collision groups."""

from __future__ import annotations

from tests.golden import model

API_NAMES = (
    "PhysicsRigidBodyAPI",
    "PhysicsMassAPI",
    "PhysicsCollisionAPI",
    "PhysicsMeshCollisionAPI",
    "PhysicsArticulationRootAPI",
    "PhysicsDriveAPI",
    "PhysicsLimitAPI",
)
JOINT_TYPES = (
    "PhysicsRevoluteJoint",
    "PhysicsPrismaticJoint",
    "PhysicsSphericalJoint",
    "PhysicsFixedJoint",
    "PhysicsDistanceJoint",
)


def _place(asset: str, name: str, x: float = 0.0, save: str | None = None) -> model.Step:
    return model.Step(
        "place_asset",
        {"asset_file_path": f"$lib/{asset}", "asset_name": name, "group": "Props", **model.at(x)},
        save=save,
        note=f"place {asset} as {name}",
    )


def _api(prim: str, api: str, note: str = "", **extra: object) -> model.Step:
    return model.Step(
        "apply_physics_api",
        {"prim_path": prim, "api_name": api, **extra},
        note=note or f"apply {api} to {prim}",
    )


def _joint(
    name: str, body0: str, body1: str, note: str = "", scope: str = "scene",
    kind: str = "PhysicsFixedJoint",
) -> model.Step:
    return model.Step(
        "create_joint",
        {"joint_type": kind, "name": name, "body0": body0, "body1": body1, "scope": scope},
        note=note or f"join {body0} and {body1}",
    )


SCENARIOS = (
    model.Scenario(
        "physics/scene",
        "The physics scene: create, adjust, list, remove.",
        (
            model.Step("list_physics_scenes", note="none yet"),
            model.Step("setup_physics_scene", note="the default physics scene"),
            model.Step(
                "setup_physics_scene",
                {"gravity_magnitude": 5.0, "gravity_direction": [0, -1, 0]},
                note="adjust gravity",
            ),
            model.Step(
                "setup_physics_scene",
                {"name": "Space", "gravity_magnitude": 0.0},
                note="a second scene",
            ),
            model.Step("list_physics_scenes"),
            model.Step("remove_physics_scene", {"name": "Space"}),
            model.Step("remove_physics_scene", {"name": "Nope"}),
        ),
    ),
    model.Scenario(
        "physics/asset_apis",
        "Physics APIs authored in the asset (shared by every placement) and removed again.",
        (
            _place("crate.usda", "Crate", save="crate"),
            _place("crate.usda", "Crate", 2.0, save="crate_2"),
            _api("$crate/asset", "PhysicsRigidBodyAPI", note="a rigid body on the crate"),
            _api("$crate/asset/Box", "PhysicsCollisionAPI", note="a collider on the box"),
            _api(
                "$crate/asset",
                "PhysicsMassAPI",
                attributes={"physics:mass": 12.5},
                note="a mass of 12.5",
            ),
            model.Step("get_physics_summary", {"prim_path": "$crate"}),
            model.Step(
                "get_physics_summary", {"prim_path": "$crate_2"}, note="the second crate shares it"
            ),
            model.Step(
                "remove_physics_api", {"prim_path": "$crate/asset", "api_name": "PhysicsMassAPI"}
            ),
            model.Step(
                "remove_physics_api",
                {"prim_path": "$crate/asset", "api_name": "PhysicsRigidBodyAPI"},
            ),
            model.Step(
                "remove_physics_api",
                {"prim_path": "$crate/asset/Box", "api_name": "PhysicsCollisionAPI"},
                note="the last one: does phy.usda go?",
            ),
        ),
    ),
    model.Scenario(
        "physics/scene_scope_override",
        "A physics API on one placement only (scene scope), next to the asset's own.",
        (
            _place("crate.usda", "Crate", save="crate"),
            _place("crate.usda", "Crate", 2.0, save="crate_2"),
            _api("$crate/asset", "PhysicsRigidBodyAPI", note="rigid body for every crate"),
            _api(
                "$crate_2/asset",
                "PhysicsMassAPI",
                scope="scene",
                attributes={"physics:mass": 50.0},
                note="a heavier mass on crate 2 only",
            ),
            model.Step("get_physics_summary", {"prim_path": "$crate_2"}),
            model.Step(
                "remove_physics_api",
                {"prim_path": "$crate_2/asset", "api_name": "PhysicsMassAPI", "scope": "scene"},
            ),
        ),
    ),
    model.Scenario(
        "physics/joints",
        "Joints between two placements (scene) and between parts of one asset (asset).",
        (
            _place("table.usda", "Table", save="table"),
            _place("crate.usda", "Crate", 2.0, save="crate"),
            _api("$table/asset", "PhysicsRigidBodyAPI"),
            _api("$crate/asset", "PhysicsRigidBodyAPI"),
            model.Step(
                "create_joint",
                {
                    "joint_type": "PhysicsFixedJoint",
                    "name": "Weld",
                    "body0": "$table/asset",
                    "body1": "$crate/asset",
                    "scope": "scene",
                },
                note="weld the crate to the table",
            ),
            model.Step(
                "create_joint",
                {
                    "joint_type": "PhysicsRevoluteJoint",
                    "name": "Hinge",
                    "body0": "$table/asset",
                    "body1": "$table/asset/Leg_L",
                    "scope": "asset",
                    "attributes": {"physics:axis": "Y"},
                },
                note="a hinge between the table and one of its legs",
            ),
            model.Step("list_joints", {"scope": "scene"}),
            model.Step("list_joints", {"scope": "asset", "asset_anchor_prim_path": "$table"}),
            model.Step(
                "create_joint",
                {
                    "joint_type": "PhysicsFixedJoint",
                    "name": "Weld",
                    "body0": "$table/asset",
                    "body1": "$crate/asset",
                    "scope": "scene",
                },
                note="a taken name",
            ),
            _api(
                "/Scene/Physics/Weld",
                "PhysicsLimitAPI",
                instance_name="rotX",
                note="a limit on a typed joint",
            ),
            model.Step("remove_joint", {"scope": "scene", "prim_path": "/Scene/Physics/Weld"}),
            model.Step(
                "remove_joint",
                {"scope": "asset", "name": "Hinge", "asset_anchor_prim_path": "$table"},
            ),
            model.Step(
                "remove_prim", {"prim_path": "$crate"}, note="remove a body the removed joint used"
            ),
        ),
    ),
    model.Scenario(
        "physics/collision_groups",
        "Collision groups: create, filter, update, remove.",
        (
            _place("crate.usda", "Crate", save="crate"),
            _place("table.usda", "Table", 2.0, save="table"),
            model.Step(
                "create_or_update_collision_group", {"name": "Boxes", "includes": ["$crate"]}
            ),
            model.Step(
                "create_or_update_collision_group",
                {"name": "Furniture", "includes": ["$table"], "filtered_groups": ["Boxes"]},
                note="furniture ignores boxes",
            ),
            model.Step(
                "create_or_update_collision_group",
                {"name": "Boxes", "excludes": ["$crate/asset/Box"]},
                note="update a group",
            ),
            model.Step("list_collision_groups"),
            model.Step(
                "remove_collision_group", {"name": "Boxes"}, note="a group another group filters"
            ),
            model.Step("remove_collision_group", {"name": "Boxes", "force": True}),
            model.Step("remove_collision_group", {"name": "Nope"}),
        ),
    ),
    model.Scenario(
        "physics/properties_and_refusals",
        "Physics property listings, and physics calls that cannot work.",
        tuple(model.Step("list_physics_api_properties", {"api_name": name}) for name in API_NAMES)
        + tuple(model.Step("list_joint_properties", {"joint_type": kind}) for kind in JOINT_TYPES)
        + (
            _place("crate.usda", "Crate", save="crate"),
            _api(
                "$crate/asset",
                "PhysicsMassAPI",
                attributes={"physics:mass": -3.0},
                note="a negative mass",
            ),
            _api(
                "$crate/asset",
                "PhysicsRigidBodyAPI",
                attributes={"physics:nope": 1},
                note="an attribute the API does not have",
            ),
            _api("/Scene/Nope", "PhysicsRigidBodyAPI", note="a prim that does not exist"),
            model.Step(
                "create_joint",
                {
                    "joint_type": "PhysicsFixedJoint",
                    "name": "J",
                    "body0": "$crate",
                    "body1": "/Scene/Nope",
                    "scope": "scene",
                },
                note="a body that does not exist",
            ),
            model.Step("remove_joint", {"scope": "scene", "prim_path": "/Scene/Physics/Nope"}),
            model.Step("get_physics_summary", {"prim_path": "/Scene/Nope"}),
            model.Step("list_joints"),
            model.Step("list_collision_groups"),
        ),
    ),
    model.Scenario(
        "physics/usd_rules_joint_bodies",
        "A joint needs a body that is a rigid body itself, and enabled: USD's own rule.",
        (
            _place("table.usda", "Table", save="table"),
            _place("crate.usda", "Crate", 2.0, save="crate"),
            _place("crate.usda", "Crate", 4.0, save="off"),
            _api("$table/asset", "PhysicsRigidBodyAPI"),
            _joint("UnderBody", "$table/asset/Top", "$crate/asset",
                   note="a part under the rigid body, not the body itself"),
            _joint("Hinge", "$table/asset/Top", "$table/asset/Leg_L", scope="asset",
                   kind="PhysicsRevoluteJoint", note="two parts under one rigid body"),
            _api("$off/asset", "PhysicsRigidBodyAPI",
                 attributes={"physics:rigidBodyEnabled": False}, note="a rigid body switched off"),
            _joint("ToOff", "$off/asset", "$crate/asset",
                   note="the only rigid body is switched off"),
            _joint("Weld", "$table/asset", "$crate/asset", note="the body itself: correct"),
            _joint("Mixed", "$table/asset", "$table/asset/Top",
                   note="one body is rigid itself, the other a part: USD accepts it"),
            model.Step("validate_scene"),
        ),
    ),
    model.Scenario(
        "physics/usd_rules_body_a_joint_needs",
        "Taking away the rigid body a joint depends on, four ways.",
        (
            _place("table.usda", "Table", save="a"),
            _place("crate.usda", "Crate", 2.0, save="a_crate"),
            _api("$a/asset", "PhysicsRigidBodyAPI"),
            _joint("WeldA", "$a/asset", "$a_crate/asset"),
            model.Step(
                "remove_physics_api",
                {"prim_path": "$a/asset", "api_name": "PhysicsRigidBodyAPI"},
                note="remove the rigid body (asset scope)",
            ),
            _place("ground.usda", "Slab", 6.0, save="b"),
            _api("$b/asset", "PhysicsRigidBodyAPI", scope="scene"),
            _joint("WeldB", "$b/asset", "$a_crate/asset"),
            model.Step(
                "remove_physics_api",
                {"prim_path": "$b/asset", "api_name": "PhysicsRigidBodyAPI", "scope": "scene"},
                note="remove the rigid body (scene scope)",
            ),
            _place("chair.usda", "Chair", 10.0, save="c"),
            _api("$c/asset", "PhysicsRigidBodyAPI", scope="scene"),
            _joint("WeldC", "$c/asset", "$a_crate/asset"),
            _api("$c/asset", "PhysicsRigidBodyAPI", scope="scene",
                 attributes={"physics:rigidBodyEnabled": False}, note="switch the body off"),
            _place("armchair.usda", "Armchair", 14.0, save="d"),
            _api("$d/asset", "PhysicsRigidBodyAPI", scope="scene"),
            _joint("WeldD", "$d/asset", "$a_crate/asset"),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$d/asset", "attribute_name": "physics:rigidBodyEnabled",
                 "value": False},
                note="switch the body off with the general attribute tool",
            ),
            _place("post_z.usda", "Post", 18.0, save="e"),
            _api("$e/asset", "PhysicsRigidBodyAPI", scope="scene"),
            _joint("WeldE", "$e/asset", "$a_crate/asset"),
            model.Step("remove_prim", {"prim_path": "$e"},
                       note="remove the placement that holds the body"),
            model.Step("list_joints"),
            model.Step("validate_scene"),
        ),
    ),
    model.Scenario(
        "physics/usd_rules_colliders_and_articulations",
        "Colliders and articulation roots USD's own rules do not accept.",
        (
            _place("shapes.usda", "Stretched", save="stretched"),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$stretched", "attribute_name": "xformOp:scale", "value": [1, 2, 3]},
                note="stretch the placement",
            ),
            _api("$stretched/asset/Ball", "PhysicsCollisionAPI", scope="scene",
                 note="a sphere collider that is stretched"),
            _api("$stretched/asset/Pill", "PhysicsCollisionAPI", scope="scene",
                 note="a capsule collider that is stretched"),
            _place("shapes.usda", "Shapes", 5.0, save="shapes"),
            _api("$shapes/asset/Ball", "PhysicsCollisionAPI",
                 note="a sphere collider in the asset: its other placement is stretched"),
            _api("$shapes/asset/Ball", "PhysicsCollisionAPI", scope="scene",
                 note="a sphere collider on this placement only, not stretched"),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$shapes", "attribute_name": "xformOp:scale", "value": [1, 2, 3]},
                note="stretch the placement after its sphere collider exists",
            ),
            _api("$shapes/asset/Dots", "PhysicsCollisionAPI", scope="scene",
                 note="points with no widths"),
            _api("$shapes/asset/Floor", "PhysicsCollisionAPI", scope="scene",
                 note="a plane collider, static"),
            _api("$shapes/asset", "PhysicsRigidBodyAPI", scope="scene",
                 note="a rigid body above the plane collider: the plane becomes dynamic"),
            _place("table.usda", "Table", 10.0, save="table"),
            _api("$table/asset", "PhysicsRigidBodyAPI",
                 attributes={"physics:rigidBodyEnabled": False}, note="a rigid body switched off"),
            _api("$table/asset", "PhysicsArticulationRootAPI",
                 note="an articulation root on a body that is switched off"),
            _place("crate.usda", "Crate", 14.0, save="crate"),
            _api("$crate/asset", "PhysicsRigidBodyAPI"),
            _api("$crate/asset", "PhysicsArticulationRootAPI"),
            _api("$crate/asset", "PhysicsRigidBodyAPI",
                 attributes={"physics:rigidBodyEnabled": False},
                 note="switch off a body that is an articulation root"),
            model.Step("validate_scene"),
        ),
    ),
)
