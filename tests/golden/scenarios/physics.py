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
    "PhysicsFilteredPairsAPI",
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


def _shape(part: str, name: str, shape: str, note: str = "", **sizes: object) -> model.Step:
    return model.Step(
        "add_collider_shape",
        {"prim_path": part, "name": name, "shape": shape, **sizes},
        note=note or f"a {shape} collider under {part}",
    )


def _grip(
    prim: str, name: str, static: float, dynamic: float, note: str = "", **extra: object,
) -> model.Step:
    return model.Step(
        "create_physics_material",
        {"prim_path": prim, "material_name": name, "static_friction": static,
         "dynamic_friction": dynamic, **extra},
        note=note or f"physics material {name} on {prim}",
    )


def _bind_grip(prim: str, name: str, note: str = "", **extra: object) -> model.Step:
    return model.Step(
        "bind_physics_material",
        {"prim_path": prim, "material_name": name, **extra},
        note=note or f"bind physics material {name} to {prim}",
    )


def _ungrip(prim: str, note: str = "") -> model.Step:
    return model.Step(
        "remove_physics_material", {"prim_path": prim},
        note=note or f"take the physics material off {prim}",
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
            _api(
                "$crate/asset",
                "PhysicsCollisionAPI",
                scope="scene",
                relationships={"physics:simulationOwner": ["/Scene/Physics/Nope"]},
                note="a relationship to a prim that does not exist",
            ),
            _place("ground.usda", "Ground", 6.0, save="ground"),
            _api(
                "$ground/asset/Plane",
                "PhysicsMeshCollisionAPI",
                attributes={"physics:approximation": "nonsense"},
                note="an approximation USD does not have (asset scope)",
            ),
            _api(
                "$ground/asset/Plane",
                "PhysicsMeshCollisionAPI",
                scope="scene",
                attributes={"physics:approximation": "roundish"},
                note="an approximation USD does not have (scene scope)",
            ),
            model.Step(
                "set_prim_attribute",
                {
                    "prim_path": "$ground/asset/Plane",
                    "attribute_name": "purpose",
                    "value": "nonsense",
                },
                note="a value outside the list an attribute allows, with the general tool",
            ),
            model.Step("get_physics_summary", {"prim_path": "/Scene/Nope"}),
            model.Step("list_joints"),
            model.Step("list_collision_groups"),
        ),
    ),
    model.Scenario(
        "physics/collider_shapes",
        "Basic collider shapes under a part: every shape, both scopes, sizes, and what is refused.",
        (
            _place("wagon.usda", "Wagon", save="wagon"),
            _api("$wagon/asset/Wheel_L", "PhysicsRigidBodyAPI"),
            _shape("$wagon/asset/Wheel_L", "collider", "cylinder",
                   radius=model.Meters(0.3), height=model.Meters(0.2), axis="X",
                   note="a cylinder for a wheel, in the asset (every placement has it)"),
            _shape("$wagon/asset/Wheel_R", "collider", "cylinder", scope="scene",
                   radius=model.Meters(0.3), height=model.Meters(0.2), axis="X",
                   note="the same on the other wheel, for this placement only"),
            _shape("$wagon/asset/Bed", "floor", "box", scope="asset",
                   size_x=model.Meters(1.2), size_y=model.Meters(0.2), size_z=model.Meters(0.8),
                   translate_y=model.Meters(0.1), note="a box, lifted a little"),
            _shape("$wagon/asset", "hitch", "sphere", radius=model.Meters(0.25),
                   translate_x=model.Meters(1.0), translate_z=model.Meters(0.5),
                   note="a sphere under the asset root, off to one side"),
            _shape("$wagon/asset", "handle", "capsule",
                   radius=model.Meters(0.1), height=model.Meters(0.5), axis="Y",
                   note="a capsule standing up"),
            _shape("$wagon/asset/Bed", "roller", "cylinder",
                   radius=model.Meters(0.1), height=model.Meters(0.8), axis="Z",
                   note="a cylinder along Z"),
            model.Step("get_physics_summary", {"prim_path": "$wagon"}),
            model.Step("validate_scene"),
            _shape("$wagon/asset/Wheel_L", "collider", "sphere", radius=model.Meters(0.3),
                   note="a name that is taken"),
            _shape("$wagon/asset/Wheel_L/Tire", "extra", "sphere", radius=model.Meters(0.3),
                   note="under a mesh, not under the part"),
            _shape("$wagon/asset/Nope", "extra", "sphere", radius=model.Meters(0.3),
                   note="a part that does not exist"),
            _shape("$wagon/asset/Bed", "extra", "cylinder", radius=model.Meters(0.3), axis="X",
                   note="a cylinder with no height"),
            _shape("$wagon/asset/Bed", "extra", "sphere", radius=model.Meters(0.3),
                   size_x=model.Meters(1.0), size_y=model.Meters(1.0), size_z=model.Meters(1.0),
                   note="a sphere given box sizes"),
            _shape("$wagon/asset/Bed", "extra", "box", size_x=model.Meters(1.0),
                   note="a box with one side only"),
            _shape("$wagon/asset/Bed", "extra", "sphere", radius=model.Meters(-0.3),
                   note="a radius below zero"),
            _shape("$wagon/asset/Bed", "my-shape", "sphere", radius=model.Meters(0.3),
                   note="a name USD cannot take"),
            _place("crate.usda", "Crate", 4.0, save="crate"),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$crate", "attribute_name": "xformOp:scale", "value": [1, 2, 1]},
                note="stretch the crate placement",
            ),
            _shape("$crate/asset", "round", "cylinder", scope="scene",
                   radius=model.Meters(0.3), height=model.Meters(0.5), axis="Y",
                   note="a cylinder under a stretched part: USD's rule refuses it"),
            _shape("$crate/asset", "block", "box", scope="scene",
                   size_x=model.Meters(0.5), size_y=model.Meters(0.5), size_z=model.Meters(0.5),
                   note="a box under a stretched part is fine"),
            model.Step("remove_collider_shape", {"prim_path": "$wagon/asset/Wheel_L/collider"},
                       note="remove the one in the asset"),
            model.Step("remove_collider_shape", {"prim_path": "$wagon/asset/Wheel_R/collider"},
                       note="remove the one in the scene"),
            model.Step("remove_collider_shape", {"prim_path": "$wagon/asset/Wheel_R/collider"},
                       note="nothing there any more"),
            model.Step("remove_collider_shape", {"prim_path": "$wagon/asset/Wheel_R/Tire"},
                       note="a mesh of the asset, not a collider shape"),
            model.Step("get_physics_summary", {"prim_path": "$wagon"}),
            model.Step("validate_scene"),
        ),
    ),
    model.Scenario(
        "physics/filtered_pairs",
        "Bodies that must not collide with each other, in an asset and across the scene.",
        (
            _place("wagon.usda", "Wagon", save="wagon"),
            _api("$wagon/asset/Bed", "PhysicsRigidBodyAPI"),
            _api("$wagon/asset/Wheel_L", "PhysicsRigidBodyAPI"),
            _api("$wagon/asset/Wheel_R", "PhysicsRigidBodyAPI"),
            _api(
                "$wagon/asset/Bed",
                "PhysicsFilteredPairsAPI",
                relationships={
                    "physics:filteredPairs": ["$wagon/asset/Wheel_L", "$wagon/asset/Wheel_R"],
                },
                note="the bed never collides with its two wheels: written in the asset",
            ),
            model.Step("get_physics_summary", {"prim_path": "$wagon"}),
            _place("crate.usda", "Crate", 4.0, save="crate"),
            _api("$crate/asset", "PhysicsRigidBodyAPI", scope="scene"),
            _api(
                "$crate/asset",
                "PhysicsFilteredPairsAPI",
                scope="scene",
                relationships={"physics:filteredPairs": ["$wagon/asset/Bed"]},
                note="the crate never collides with the wagon's bed: written in the scene",
            ),
            _api(
                "$wagon/asset/Wheel_L",
                "PhysicsFilteredPairsAPI",
                scope="asset",
                relationships={"physics:filteredPairs": ["$crate/asset"]},
                note="from the asset, a prim outside the asset cannot be reached",
            ),
            _api(
                "$wagon/asset/Wheel_L",
                "PhysicsFilteredPairsAPI",
                relationships={"physics:filteredPairs": ["$wagon/asset/Nope"]},
                note="a prim that does not exist",
            ),
            model.Step("validate_scene"),
            model.Step(
                "remove_physics_api",
                {"prim_path": "$wagon/asset/Bed", "api_name": "PhysicsFilteredPairsAPI"},
                note="remove the filter in the asset",
            ),
            model.Step(
                "remove_physics_api",
                {"prim_path": "$crate/asset", "api_name": "PhysicsFilteredPairsAPI",
                 "scope": "scene"},
                note="remove the filter in the scene",
            ),
            model.Step("get_physics_summary", {"prim_path": "$wagon"}),
        ),
    ),
    model.Scenario(
        "physics/materials",
        "Physics materials: friction and bounce bound to colliders, apart from the look.",
        (
            _place("wagon.usda", "Wagon", save="wagon"),
            _place("ground.usda", "Ground", 6.0, save="ground"),
            _api("$wagon/asset/Wheel_L", "PhysicsRigidBodyAPI"),
            _shape("$wagon/asset/Wheel_L", "collider", "cylinder",
                   radius=model.Meters(0.3), height=model.Meters(0.2), axis="X"),
            _grip("$wagon/asset/Wheel_L", "rubber", 0.9, 0.8,
                  note="rubber on a wheel part, in the asset"),
            _bind_grip("$wagon/asset/Wheel_R", "rubber", scope="asset",
                       note="the same material on the other wheel"),
            _grip("$ground/asset/Plane", "soil", 0.6, 0.5, restitution=0.1, scope="scene",
                  note="soil on the ground, in the scene"),
            _bind_grip("$wagon/asset/Bed", "soil", scope="scene",
                       note="the scene's material on a part of a placed asset"),
            _grip("$wagon/asset/Wheel_L", "rubber", 1.0, 0.9, restitution=0.2, scope="asset",
                  note="the same name again: its values are updated"),
            model.Step("get_physics_summary", {"prim_path": "$wagon"}),
            model.Step("get_physics_summary", {"prim_path": "/Scene/Physics"}),
            model.Step(
                "create_material",
                {"prim_path": "$wagon/asset/Wheel_L/Tire", "material_name": "black",
                 "base_color_r": 0.05, "base_color_g": 0.05, "base_color_b": 0.05},
                note="a look on the tire: a separate binding",
            ),
            model.Step("list_materials", note="looks only: the physics materials are not looks"),
            model.Step("remove_material", {"prim_path": "$wagon/asset/Wheel_L/Tire"},
                       note="removing the look leaves the physics material bound"),
            model.Step("validate_scene"),
            _grip("$wagon/asset/Bed", "ice", -0.1, 0.05, note="friction below zero"),
            _grip("$wagon/asset/Bed", "ball", 0.5, 0.5, restitution=2.0,
                  note="bounce above 1"),
            _grip("$wagon/asset/Bed", "my-grip", 0.5, 0.5, note="a name USD cannot take"),
            _grip("$wagon/asset/Nope", "rubber", 0.5, 0.5, note="a prim that does not exist"),
            _grip("$ground/asset/Plane", "PhysicsScene", 0.5, 0.5, scope="scene",
                  note="a name another prim has"),
            _bind_grip("$wagon/asset/Bed", "velvet", note="a material that does not exist"),
            _bind_grip("$wagon/asset/Wheel_R", "soil", scope="scene",
                       note="a scene binding over the asset's: this placement uses soil"),
            _bind_grip("$wagon/asset/Wheel_R", "rubber", scope="asset",
                       note="an asset binding the scene binding would hide"),
            _ungrip("$wagon/asset/Wheel_R", note="the scene binding goes first"),
            _ungrip("$wagon/asset/Wheel_R", note="then the asset's; rubber is still used"),
            _ungrip("$wagon/asset/Wheel_R", note="nothing left on this prim"),
            _ungrip("$wagon/asset/Wheel_L", note="the last user of rubber: it is deleted too"),
            _ungrip("$wagon/asset/Bed"),
            _ungrip("$ground/asset/Plane", note="the last user of soil"),
            _ungrip("$wagon/asset/Nope", note="a prim that does not exist"),
            model.Step("get_physics_summary", {"prim_path": "$wagon"}),
            model.Step("validate_scene"),
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
        "physics/usd_rules_through_other_tools",
        "A tool that is not a physics tool leaves a physics error: what the answer says.",
        (
            _place("table.usda", "Table", save="table"),
            _place("crate.usda", "Crate", 2.0, save="crate"),
            _api("$table/asset", "PhysicsRigidBodyAPI"),
            _joint("Weld", "$table/asset", "$crate/asset"),
            model.Step(
                "add_asset_attribute_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "state",
                    "variant_name": "frozen",
                    "overrides": {"$table/asset": {"physics:rigidBodyEnabled": False}},
                    "set_as_default": True,
                },
                note="a variant that switches off the body the joint needs, made the default",
            ),
            model.Step(
                "add_asset_attribute_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "state",
                    "variant_name": "parked",
                    "overrides": {"$table/asset": {"physics:rigidBodyEnabled": False}},
                },
                note="the same physics attribute in a variant that is not selected",
            ),
            _api("$table/asset/Top", "PhysicsRigidBodyAPI"),
            _joint("TopWeld", "$table/asset/Top", "$crate/asset"),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "parts",
                    "variant_name": "no_top",
                    "activations": {"$table/asset/Top": False},
                    "set_as_default": True,
                },
                note="a variant that switches off the part a joint is attached to",
            ),
            _place("loose_rig/loose_rig.usda", "Rig", 6.0),
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
