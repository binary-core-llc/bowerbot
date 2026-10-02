# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tools called where they cannot work: nothing open, no library configured, not an asset."""

from __future__ import annotations

from tests.golden import model

P = "/Scene/Props/Thing_01"

# Plausible arguments for every tool; with no project open, each call shows how
# the tool answers when there is nothing to work on.
ARGS: dict[str, dict[str, object]] = {
    "add_asset_attribute_variant": {
        "prim_path": P,
        "variant_set": "s",
        "variant_name": "v",
        "overrides": {f"{P}/asset/A": {"visibility": "invisible"}},
    },
    "add_asset_configuration_variant": {
        "prim_path": P,
        "variant_set": "s",
        "variant_name": "v",
        "activations": {f"{P}/asset/A": False},
    },
    "add_asset_geometry_variant": {
        "prim_path": P,
        "variant_set": "s",
        "variant_name": "v",
        "payloads": {"/thing": "./geo_low.usda"},
    },
    "add_asset_material_variant": {
        "prim_path": P,
        "variant_set": "s",
        "variant_name": "v",
        "bindings": {f"{P}/asset/A": f"{P}/asset/mtl/m"},
    },
    "add_scene_lighting_attribute_variant": {
        "variant_set": "s",
        "variant_name": "v",
        "overrides": {"/Scene/Lighting/Key": {"inputs:intensity": 1.0}},
    },
    "add_scene_lighting_selection_variant": {
        "variant_set": "s",
        "variant_name": "v",
        "activations": {"/Scene/Lighting/Key": True},
    },
    "add_scene_model_selection_variant": {
        "prim_path": P,
        "variant_set": "s",
        "variant_name": "v",
        "asset_file_path": "$lib/crate.usda",
    },
    "apply_physics_api": {"prim_path": P, "api_name": "PhysicsRigidBodyAPI"},
    "bind_material": {"prim_path": P, "material_file": "$lib/materials/oak.usda"},
    "cleanup_unused_contents": {},
    "cleanup_unused_materials": {},
    "compute_grid_layout": {"count": 4},
    "create_camera": {"camera_name": "Cam"},
    "create_joint": {
        "joint_type": "PhysicsFixedJoint",
        "name": "J",
        "body0": P,
        "body1": "/Scene/Props/Other_01",
    },
    "create_light": {"light_type": "SphereLight", "light_name": "Key"},
    "create_material": {"prim_path": P, "material_name": "oak"},
    "create_or_update_collision_group": {"name": "G"},
    "create_stage": {"filename": "scene"},
    "delete_project_asset": {"name": "thing"},
    "delete_project_texture": {"file_name": "studio.hdr"},
    "delete_scene_snapshot": {"name": "snap"},
    "drop_to_surface": {"prim_paths": [P]},
    "freeze_asset": {},
    "get_current_project": {},
    "get_physics_summary": {"prim_path": P},
    "list_asset_geo_files": {"prim_path": P},
    "list_assets": {},
    "list_camera_properties": {},
    "list_collision_groups": {},
    "list_joint_properties": {"joint_type": "PhysicsFixedJoint"},
    "list_joints": {},
    "list_light_type_properties": {"light_type": "SphereLight"},
    "list_materials": {},
    "list_physics_api_properties": {"api_name": "PhysicsRigidBodyAPI"},
    "list_physics_scenes": {},
    "list_prim_attributes": {"prim_path": P},
    "list_prim_children": {"prim_path": P},
    "list_project_assets": {},
    "list_projects": {},
    "list_scene": {},
    "list_scene_snapshots": {},
    "list_textures": {},
    "list_variants": {"prim_path": P},
    "move_asset": {"prim_path": P, "translate_x": 1.0},
    "open_project": {"name": "nope"},
    "package_scene": {},
    "place_asset": {
        "asset_file_path": "$lib/crate.usda",
        "asset_name": "Crate",
        "group": "Props",
        "translate_x": 0.0,
        "translate_y": 0.0,
        "translate_z": 0.0,
    },
    "add_asset_to_asset": {
        "asset_file_path": "$lib/crate.usda",
        "asset_name": "Crate",
        "parent_prim_path": P,
        "group": "Props",
        "translate_x": 0.0,
        "translate_y": 0.0,
        "translate_z": 0.0,
    },
    "place_layout": {
        "placements": [
            {"asset": "$lib/crate.usda", "group": "Props", "transforms": [{"translate": [0, 0, 0]}]}
        ]
    },
    "remove_asset_variant": {"prim_path": P, "variant_set": "s", "variant_name": "v"},
    "remove_asset_variant_set": {"prim_path": P, "variant_set": "s"},
    "remove_camera": {"prim_path": "/Scene/Cameras/Cam"},
    "remove_collision_group": {"name": "G"},
    "remove_joint": {"scope": "scene", "prim_path": "/Scene/Physics/J"},
    "remove_light": {"prim_path": "/Scene/Lighting/Key"},
    "remove_material": {"prim_path": P},
    "remove_physics_api": {"prim_path": P, "api_name": "PhysicsRigidBodyAPI"},
    "remove_physics_scene": {"name": "PhysicsScene"},
    "remove_prim": {"prim_path": P},
    "remove_scene_variant": {"prim_path": P, "variant_set": "s", "variant_name": "v"},
    "remove_scene_variant_set": {"prim_path": P, "variant_set": "s"},
    "rename_prim": {"old_path": P, "new_path": "/Scene/Props/Other"},
    "save_scene_snapshot": {"name": "snap"},
    "scatter_along_path": {
        "name": "Row",
        "assets": [{"asset": "$lib/crate.usda"}],
        "points": [[0, 0, 0], [4, 0, 0]],
        "count": 3,
    },
    "scatter_on_surface": {
        "name": "Pile",
        "assets": [{"asset": "$lib/crate.usda"}],
        "surfaces": [P],
        "count": 3,
    },
    "search_assets": {"query": "chair"},
    "search_textures": {"query": "studio"},
    "select_asset_variant": {"prim_path": P, "variant_set": "s", "variant_name": "v"},
    "select_asset_variant_for_instance": {"prim_path": P, "variant_set": "s", "variant_name": "v"},
    "select_scene_variant": {"prim_path": P, "variant_set": "s", "variant_name": "v"},
    "set_prim_attribute": {"prim_path": P, "attribute_name": "visibility", "value": "invisible"},
    "setup_asset_geometry_variants": {
        "prim_path": P,
        "variant_set": "s",
        "variants": {"high": "./geo.usda"},
        "default_variant": "high",
    },
    "setup_physics_scene": {},
    "update_camera": {"prim_path": "/Scene/Cameras/Cam", "translate_x": 1.0},
    "update_light": {"prim_path": "/Scene/Lighting/Key", "translate_x": 1.0},
    "validate_scene": {},
    "create_project": {"name": "late", "up_axis": "Y", "meters_per_unit": 1.0},
}

# create_project opens a project, so it runs last.
ORDER = sorted(name for name in ARGS if name != "create_project") + ["create_project"]

LIBRARY_TOOLS = (
    "search_assets",
    "list_assets",
    "search_textures",
    "list_textures",
    "place_asset",
    "bind_material",
)

SCENARIOS = (
    model.Scenario(
        "state/nothing_open",
        "Every tool, called before any project is created or opened.",
        tuple(model.Step(name, ARGS[name], note="no project is open") for name in ORDER),
        conventions=(model.Y_M,),
        open_project=False,
    ),
    model.Scenario(
        "state/no_library",
        "Library, texture and placement tools with no asset library configured.",
        tuple(
            model.Step(name, ARGS[name], note="no asset library configured")
            for name in LIBRARY_TOOLS
        ),
        conventions=(model.Y_M,),
        library=False,
    ),
    model.Scenario(
        "state/names_usd_cannot_take",
        "Names USD cannot take as they are (starting with a digit, with a hyphen or a dot, or "
        "empty once cleaned): what does each tool answer, and does it change the project?",
        (
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/table.usda",
                    "asset_name": "Table",
                    "group": "Furniture",
                    **model.at(0.0),
                },
                save="table",
            ),
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "3 crates",
                    "group": "Props",
                    **model.at(2.0),
                },
                note="an asset name that starts with a digit",
            ),
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "--",
                    "group": "Props",
                    **model.at(3.0),
                },
                note="an asset name with nothing left once cleaned",
            ),
            model.Step(
                "add_asset_to_asset",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "2nd",
                    "parent_prim_path": "$table",
                    "group": "Props",
                    **model.at(0.0),
                },
                note="the same for an asset added to another",
            ),
            model.Step(
                "create_light",
                {"light_type": "SphereLight", "light_name": "9 lives", **model.at(0.0, 3.0, 0.0)},
                note="a light name that starts with a digit",
            ),
            model.Step("create_camera", {"camera_name": "2nd-cam"}, note="a camera name"),
            model.Step(
                "apply_physics_api",
                {"prim_path": "$table/asset", "api_name": "PhysicsRigidBodyAPI"},
                note="a body, so the joint below is only wrong in its name",
            ),
            model.Step(
                "create_joint",
                {
                    "joint_type": "PhysicsFixedJoint",
                    "name": "my-joint",
                    "body0": "$table/asset",
                    "scope": "scene",
                },
                note="a joint name with a hyphen",
            ),
            model.Step(
                "create_or_update_collision_group",
                {"name": "grp.a", "includes": ["$table"]},
                note="a collision group name with a dot",
            ),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "my-set",
                    "variant_name": "x",
                    "activations": {"$table/asset/Leg_L": False},
                },
                note="a variant set name with a hyphen",
            ),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "legs",
                    "variant_name": "no:left",
                    "activations": {"$table/asset/Leg_L": False},
                },
                note="a variant name with a colon",
            ),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "legs",
                    "variant_name": "no.left",
                    "activations": {"$table/asset/Leg_L": False},
                },
                note="a variant name with a dot in the middle",
            ),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "legs",
                    "variant_name": "no-left",
                    "activations": {"$table/asset/Leg_L": False},
                },
                note="a variant name with a hyphen, which USD allows",
            ),
            model.Step("list_scene", note="what ended up in the scene"),
        ),
    ),
    model.Scenario(
        "state/a_failed_call_changes_nothing",
        "A call that is refused half-way: does anything it started show up later, and does a "
        "rename to a name USD cannot take keep the object?",
        (
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/table.usda",
                    "asset_name": "Table",
                    "group": "Furniture",
                    **model.at(0.0),
                },
                save="table",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "light_name": "Ghost",
                    "attributes": {"inputs:radius": "big"},
                },
                note="refused: the radius is not a number",
            ),
            model.Step(
                "create_light",
                {"light_type": "SphereLight", "light_name": "Real", **model.at(0.0, 2.0, 0.0)},
                note="a good call right after: is the refused light saved along with it?",
            ),
            model.Step("list_scene"),
            model.Step(
                "rename_prim",
                {"old_path": "$table", "new_path": "/Scene/Furniture/9table"},
                note="a new name that starts with a digit",
            ),
            model.Step("list_scene", note="is the table still there?"),
        ),
    ),
    model.Scenario(
        "state/not_an_asset",
        "Tools that work on an asset, called on a scene prim that is not one.",
        (
            model.Step(
                "create_light",
                {"light_type": "SphereLight", "light_name": "Key", **model.at(0.0, 3.0, 0.0)},
                save="key",
                note="a scene light: a prim that belongs to no asset",
            ),
            model.Step(
                "add_asset_to_asset",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "Crate",
                    "parent_prim_path": "$key",
                    "group": "Props",
                    **model.at(0.0),
                },
            ),
            model.Step("cleanup_unused_contents", {"asset_prim_path": "$key"}),
            model.Step("cleanup_unused_materials", {"asset_prim_path": "$key"}),
            model.Step("create_material", {"prim_path": "$key", "material_name": "oak"}),
            model.Step(
                "bind_material",
                {"prim_path": "$key", "material_file": "$lib/materials/oak.usda"},
            ),
            model.Step("remove_material", {"prim_path": "$key"}),
            model.Step(
                "create_light",
                {"light_type": "SphereLight", "light_name": "Bulb", "asset_prim_path": "$key"},
                note="a light that should belong to an asset",
            ),
            model.Step(
                "apply_physics_api",
                {"prim_path": "$key", "api_name": "PhysicsRigidBodyAPI", "scope": "asset"},
            ),
            model.Step(
                "remove_physics_api",
                {"prim_path": "$key", "api_name": "PhysicsRigidBodyAPI", "scope": "asset"},
            ),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$key",
                    "variant_set": "s",
                    "variant_name": "v",
                    "activations": {"$key": False},
                },
            ),
            model.Step("list_asset_geo_files", {"prim_path": "$key"}),
        ),
    ),
)
