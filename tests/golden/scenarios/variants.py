# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variants: asset material, geometry, configuration and attribute variants; scene lighting
and model-selection variants; selecting, listing and removing them."""

from __future__ import annotations

from tests.golden import model


def _place(
    asset: str, name: str, group: str = "Props", x: float = 0.0, save: str | None = None
) -> model.Step:
    return model.Step(
        "place_asset",
        {"asset_file_path": f"$lib/{asset}", "asset_name": name, "group": group, **model.at(x)},
        save=save,
        note=f"place {asset} as {name}",
    )


def _light(name: str, x: float, save: str) -> model.Step:
    return model.Step(
        "create_light",
        {"light_type": "SphereLight", "light_name": name, **model.at(x, 3.0, 0.0)},
        save=save,
        note=f"a light named {name}",
    )


SCENARIOS = (
    model.Scenario(
        "variants/asset_material",
        "A material variant set on an asset: add, list, select per asset and per instance, remove.",
        (
            _place("lamp/lamp.usda", "Lamp", save="lamp"),
            _place("lamp/lamp.usda", "Lamp", x=2.0, save="lamp_2"),
            model.Step(
                "create_material",
                {
                    "prim_path": "$lamp/asset/Base",
                    "material_name": "red",
                    "base_color_r": 0.8,
                    "base_color_g": 0.1,
                    "base_color_b": 0.1,
                    "confirm_shared_modification": True,
                },
                note="a second material in the lamp, so there are two to choose from",
            ),
            model.Step(
                "add_asset_material_variant",
                {
                    "prim_path": "$lamp",
                    "variant_set": "finish",
                    "variant_name": "red",
                    "bindings": {"$lamp/asset/Shade": "$lamp/asset/mtl/red"},
                },
                note="variant red: the Shade shows red",
            ),
            model.Step(
                "add_asset_material_variant",
                {
                    "prim_path": "$lamp",
                    "variant_set": "finish",
                    "variant_name": "brass",
                    "bindings": {"$lamp/asset/Shade": "$lamp/asset/mtl/brass"},
                },
                note="variant brass: the Shade shows the shipped brass",
            ),
            model.Step("list_variants", {"prim_path": "$lamp"}),
            model.Step(
                "select_asset_variant",
                {"prim_path": "$lamp", "variant_set": "finish", "variant_name": "red"},
                note="every lamp shows red",
            ),
            model.Step(
                "select_asset_variant_for_instance",
                {"prim_path": "$lamp_2", "variant_set": "finish", "variant_name": "brass"},
                note="only the second lamp shows brass",
            ),
            model.Step(
                "remove_asset_variant",
                {"prim_path": "$lamp", "variant_set": "finish", "variant_name": "red"},
                note="remove the selected variant",
            ),
            model.Step("list_variants", {"prim_path": "$lamp"}),
            model.Step("remove_asset_variant_set", {"prim_path": "$lamp", "variant_set": "finish"}),
            model.Step("list_variants", {"prim_path": "$lamp"}),
        ),
    ),
    model.Scenario(
        "variants/asset_geometry_lod",
        "A geometry (LOD) variant set built from the files in the asset folder.",
        (
            _place("lamp/lamp.usda", "Lamp", save="lamp"),
            model.Step("list_asset_geo_files", {"prim_path": "$lamp"}),
            model.Step(
                "add_asset_geometry_variant",
                {
                    "prim_path": "$lamp",
                    "variant_set": "lod",
                    "variant_name": "low",
                    "payloads": {"/lamp": "./geo_low.usda"},
                },
                note="extending a set that was never set up",
            ),
            model.Step(
                "setup_asset_geometry_variants",
                {
                    "prim_path": "$lamp",
                    "variant_set": "lod",
                    "variants": {"high": "./geo.usda", "low": "./geo_low.usda"},
                    "default_variant": "high",
                },
                note="set up high and low",
            ),
            model.Step(
                "select_asset_variant",
                {"prim_path": "$lamp", "variant_set": "lod", "variant_name": "low"},
            ),
            model.Step(
                "add_asset_geometry_variant",
                {
                    "prim_path": "$lamp",
                    "variant_set": "lod",
                    "variant_name": "proxy",
                    "payloads": {"/lamp": "./geo_low.usda"},
                },
                note="a third variant",
            ),
            model.Step(
                "setup_asset_geometry_variants",
                {
                    "prim_path": "$lamp",
                    "variant_set": "lod2",
                    "variants": {"high": "./geo.usda", "missing": "./nope.usda"},
                    "default_variant": "high",
                },
                note="a payload file that does not exist",
            ),
            model.Step("list_variants", {"prim_path": "$lamp"}),
            model.Step("remove_asset_variant_set", {"prim_path": "$lamp", "variant_set": "lod"}),
        ),
    ),
    model.Scenario(
        "variants/asset_configuration",
        "A configuration variant set that turns parts on and off.",
        (
            _place("table.usda", "Table", "Furniture", save="table"),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "legs",
                    "variant_name": "one_leg",
                    "activations": {"$table/asset/Leg_L": False},
                },
                note="variant one_leg: Leg_L switched off",
            ),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "legs",
                    "variant_name": "all",
                    "activations": {"$table/asset/Leg_L": True},
                    "set_as_default": True,
                },
                note="variant all, made the default",
            ),
            model.Step(
                "select_asset_variant",
                {"prim_path": "$table", "variant_set": "legs", "variant_name": "one_leg"},
            ),
            model.Step(
                "remove_asset_variant",
                {"prim_path": "$table", "variant_set": "legs", "variant_name": "all"},
                note="remove the default variant",
            ),
            model.Step(
                "remove_asset_variant",
                {"prim_path": "$table", "variant_set": "legs", "variant_name": "one_leg"},
                note="remove the last variant",
            ),
            model.Step("list_variants", {"prim_path": "$table"}),
        ),
    ),
    model.Scenario(
        "variants/asset_attribute",
        "An attribute variant set that changes values on parts.",
        (
            _place("table.usda", "Table", "Furniture", save="table"),
            model.Step(
                "add_asset_attribute_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "size",
                    "variant_name": "big",
                    "overrides": {"$table/asset/Top": {"size": 1.5}},
                },
                note="variant big: the Top's size 1.5",
            ),
            model.Step(
                "add_asset_attribute_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "size",
                    "variant_name": "hidden_top",
                    "overrides": {"$table/asset/Top": {"visibility": "invisible"}},
                },
                note="variant hidden_top",
            ),
            model.Step(
                "select_asset_variant",
                {"prim_path": "$table", "variant_set": "size", "variant_name": "hidden_top"},
            ),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$table/asset/Top", "attribute_name": "size", "value": 3.0},
                note="a scene override on a value the variants set",
            ),
            model.Step(
                "add_asset_attribute_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "size",
                    "variant_name": "small",
                    "overrides": {"$table/asset/Top": {"size": 0.5}},
                },
                note="a new variant now masked by the scene override",
            ),
            model.Step(
                "add_asset_attribute_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "size",
                    "variant_name": "small",
                    "overrides": {"$table/asset/Top": {"size": 0.5}},
                    "clear_masking_overrides": True,
                },
                note="clear the masking override first",
            ),
            model.Step("list_variants", {"prim_path": "$table"}),
        ),
    ),
    model.Scenario(
        "variants/scene_lighting",
        "Scene lighting variants: attribute moods and a light selection.",
        (
            _light("Key", 0.0, "key"),
            _light("Fill", 2.0, "fill"),
            model.Step(
                "add_scene_lighting_attribute_variant",
                {
                    "variant_set": "mood",
                    "variant_name": "day",
                    "overrides": {"$key": {"inputs:intensity": 1000.0}},
                },
                note="mood day",
            ),
            model.Step(
                "add_scene_lighting_attribute_variant",
                {
                    "variant_set": "mood",
                    "variant_name": "night",
                    "overrides": {
                        "$key": {"inputs:intensity": 50.0, "inputs:color": [0.4, 0.5, 1.0]}
                    },
                    "set_as_default": True,
                },
                note="mood night, the default",
            ),
            model.Step(
                "add_scene_lighting_selection_variant",
                {
                    "variant_set": "rig",
                    "variant_name": "key_only",
                    "activations": {"$key": True, "$fill": False},
                },
                note="rig key_only: the fill is off",
            ),
            model.Step("list_variants", {"prim_path": "/Scene/Lighting"}),
            model.Step(
                "select_scene_variant",
                {"prim_path": "/Scene/Lighting", "variant_set": "mood", "variant_name": "day"},
            ),
            model.Step(
                "remove_scene_variant",
                {"prim_path": "/Scene/Lighting", "variant_set": "mood", "variant_name": "day"},
                note="remove the selected mood",
            ),
            model.Step(
                "remove_scene_variant_set", {"prim_path": "/Scene/Lighting", "variant_set": "rig"}
            ),
            model.Step("list_variants", {"prim_path": "/Scene/Lighting"}),
        ),
    ),
    model.Scenario(
        "variants/model_selection",
        "A placement that can swap between models.",
        (
            _place("chair.usda", "Seat", "Furniture", save="seat"),
            model.Step(
                "add_scene_model_selection_variant",
                {
                    "prim_path": "$seat",
                    "variant_set": "model",
                    "variant_name": "crate",
                    "asset_file_path": "$lib/crate.usda",
                },
                note="the seat can also be a crate",
            ),
            model.Step(
                "add_scene_model_selection_variant",
                {
                    "prim_path": "$seat",
                    "variant_set": "model",
                    "variant_name": "chair_cm",
                    "asset_file_path": "$lib/chair_cm.usda",
                },
                note="or the centimeter chair",
            ),
            model.Step("list_variants", {"prim_path": "$seat"}),
            model.Step(
                "select_scene_variant",
                {"prim_path": "$seat", "variant_set": "model", "variant_name": "chair_cm"},
            ),
            model.Step(
                "remove_scene_variant",
                {"prim_path": "$seat", "variant_set": "model", "variant_name": "crate"},
            ),
            model.Step(
                "remove_scene_variant_set",
                {"prim_path": "$seat", "variant_set": "model"},
                note="remove the whole set: which model stays?",
            ),
            model.Step("list_scene"),
        ),
    ),
    model.Scenario(
        "variants/refusals",
        "Variant calls that cannot work.",
        (
            _place("table.usda", "Table", "Furniture", save="table"),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "bad name",
                    "variant_name": "x",
                    "activations": {"$table/asset/Leg_L": False},
                },
                note="a set name with a space",
            ),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "legs",
                    "variant_name": "x",
                    "activations": {"$table/asset/Nope": False},
                },
                note="a part that does not exist",
            ),
            model.Step(
                "add_asset_material_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "finish",
                    "variant_name": "x",
                    "bindings": {"$table/asset/Top": "$table/asset/mtl/nope"},
                },
                note="a material that does not exist",
            ),
            model.Step(
                "select_asset_variant",
                {"prim_path": "$table", "variant_set": "nope", "variant_name": "x"},
                note="a set that does not exist",
            ),
            model.Step(
                "remove_asset_variant",
                {"prim_path": "$table", "variant_set": "nope", "variant_name": "x"},
            ),
            model.Step("list_variants", {"prim_path": "/Scene/Nope"}),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "legs",
                    "variant_name": "x",
                    "activations": {},
                },
                note="no activations",
            ),
        ),
    ),
    model.Scenario(
        "variants/selection_refusals",
        "Selecting a variant that cannot be selected: no such set, no such variant, two carriers.",
        (
            _place("table.usda", "Table", "Furniture", save="table"),
            _place("table.usda", "Table", "Furniture", x=3.0, save="table2"),
            _light("Key", -2.0, "key"),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$table",
                    "variant_set": "legs",
                    "variant_name": "three",
                    "activations": {"$table/asset/Leg_L": False},
                },
                note="the table gets a set named legs",
            ),
            model.Step(
                "add_scene_lighting_selection_variant",
                {"variant_set": "rig", "variant_name": "key_only", "activations": {"$key": True}},
                note="the lighting gets a set named rig",
            ),
            model.Step(
                "select_scene_variant",
                {"prim_path": "/Scene/Lighting", "variant_set": "nope", "variant_name": "x"},
                note="a set the lighting does not have",
            ),
            model.Step(
                "select_scene_variant",
                {"prim_path": "/Scene/Lighting", "variant_set": "rig", "variant_name": "nope"},
                note="a variant the set does not have",
            ),
            model.Step(
                "select_asset_variant_for_instance",
                {"prim_path": "$table", "variant_set": "nope", "variant_name": "x"},
                note="a set the table does not have",
            ),
            model.Step(
                "select_asset_variant_for_instance",
                {"prim_path": "$table", "variant_set": "legs", "variant_name": "nope"},
                note="a variant the set does not have",
            ),
            model.Step(
                "select_asset_variant_for_instance",
                {"prim_path": "/Scene/Furniture", "variant_set": "legs", "variant_name": "three"},
                note="a prim with two tables under it",
            ),
            model.Step(
                "select_asset_variant_for_instance",
                {"prim_path": "$table2", "variant_set": "legs", "variant_name": "three"},
                note="one table only: this one works",
            ),
            model.Step("list_variants", {"prim_path": "$table2"}),
        ),
    ),
    model.Scenario(
        "variants/geometry_lod_shipped",
        "LODs from an asset that ships both geometry files: listing, setup, extending, default.",
        (
            _place("lamp_lod/lamp_lod.usda", "LodLamp", save="lamp"),
            model.Step("list_variants", {"prim_path": "$lamp"}, note="the shipped LOD set"),
            model.Step("list_asset_geo_files", {"prim_path": "$lamp"}),
            model.Step(
                "setup_asset_geometry_variants",
                {
                    "prim_path": "$lamp",
                    "variant_set": "lod",
                    "variants": {"high": "./geo.usda", "low": "./geo_low.usda"},
                    "default_variant": "high",
                },
                note="set up a BowerBot LOD set from the two files",
            ),
            model.Step(
                "add_asset_geometry_variant",
                {
                    "prim_path": "$lamp",
                    "variant_set": "lod",
                    "variant_name": "proxy",
                    "payloads": {"/lamp_lod": "./geo_low.usda"},
                    "set_as_default": True,
                },
                note="extend it with a proxy, made the default",
            ),
            model.Step(
                "select_asset_variant",
                {"prim_path": "$lamp", "variant_set": "lod", "variant_name": "low"},
            ),
            model.Step("list_variants", {"prim_path": "$lamp"}),
            model.Step(
                "remove_asset_variant",
                {"prim_path": "$lamp", "variant_set": "lod", "variant_name": "proxy"},
            ),
            model.Step(
                "list_asset_geo_files",
                {"prim_path": "/Scene/Nope"},
                note="a placement that does not exist",
            ),
        ),
    ),
    model.Scenario(
        "variants/asset_flags",
        "set_as_default, confirm_masked and clear_masking_overrides on every asset variant kind.",
        (
            _place("lamp/lamp.usda", "Lamp", save="lamp"),
            model.Step(
                "create_material",
                {
                    "prim_path": "$lamp/asset/Base",
                    "material_name": "red",
                    "base_color_r": 0.8,
                    "base_color_g": 0.1,
                    "base_color_b": 0.1,
                },
                note="a second material to switch to",
            ),
            model.Step(
                "add_asset_material_variant",
                {
                    "prim_path": "$lamp",
                    "variant_set": "finish",
                    "variant_name": "red",
                    "bindings": {"$lamp/asset/Shade": "$lamp/asset/mtl/red"},
                    "set_as_default": True,
                    "confirm_masked": True,
                },
                note="a material variant made the default, masking confirmed",
            ),
            model.Step(
                "add_asset_material_variant",
                {
                    "prim_path": "$lamp",
                    "variant_set": "finish",
                    "variant_name": "brass",
                    "bindings": {"$lamp/asset/Shade": "$lamp/asset/mtl/brass"},
                    "clear_masking_overrides": True,
                },
                note="another, clearing masking overrides first",
            ),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$lamp",
                    "variant_set": "parts",
                    "variant_name": "no_shade",
                    "activations": {"$lamp/asset/Shade": False},
                    "set_as_default": True,
                    "clear_masking_overrides": True,
                },
                note="a configuration variant made the default",
            ),
            model.Step(
                "add_asset_configuration_variant",
                {
                    "prim_path": "$lamp",
                    "variant_set": "parts",
                    "variant_name": "all",
                    "activations": {"$lamp/asset/Shade": True},
                    "confirm_masked": True,
                },
            ),
            model.Step(
                "add_asset_attribute_variant",
                {
                    "prim_path": "$lamp",
                    "variant_set": "tint",
                    "variant_name": "hidden_base",
                    "overrides": {"$lamp/asset/Base": {"visibility": "invisible"}},
                    "set_as_default": True,
                    "confirm_masked": True,
                },
                note="an attribute variant made the default",
            ),
            model.Step("list_variants", {"prim_path": "$lamp"}),
            model.Step(
                "add_asset_material_variant",
                {
                    "prim_path": "$lamp",
                    "variant_set": "finish!",
                    "variant_name": "x",
                    "bindings": {"$lamp/asset/Shade": "$lamp/asset/mtl/red"},
                },
                note="an invalid set name",
            ),
            model.Step(
                "remove_asset_variant",
                {"prim_path": "/Scene/Nope", "variant_set": "finish", "variant_name": "red"},
                note="a placement that does not exist",
            ),
            model.Step(
                "remove_asset_variant_set", {"prim_path": "/Scene/Nope", "variant_set": "finish"}
            ),
            model.Step(
                "select_asset_variant",
                {"prim_path": "/Scene/Nope", "variant_set": "finish", "variant_name": "red"},
            ),
            model.Step(
                "select_asset_variant_for_instance",
                {"prim_path": "/Scene/Nope", "variant_set": "finish", "variant_name": "red"},
            ),
            model.Step("remove_asset_variant_set", {"prim_path": "$lamp", "variant_set": "tint"}),
        ),
    ),
    model.Scenario(
        "variants/scene_flags",
        "Scene lighting and model-selection variants: flags, defaults, repairs and refusals.",
        (
            _light("Key", 0.0, "key"),
            _light("Fill", 2.0, "fill"),
            _place("chair.usda", "Seat", "Furniture", 4.0, save="seat"),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$key", "attribute_name": "inputs:intensity", "value": 700.0},
                note="a scene value on the key light",
            ),
            model.Step(
                "add_scene_lighting_attribute_variant",
                {
                    "variant_set": "mood",
                    "variant_name": "dim",
                    "overrides": {"$key": {"inputs:intensity": 10.0}},
                },
                note="masked by the value just set",
            ),
            model.Step(
                "add_scene_lighting_attribute_variant",
                {
                    "variant_set": "mood",
                    "variant_name": "dim",
                    "overrides": {"$key": {"inputs:intensity": 10.0}},
                    "confirm_masked": True,
                },
                note="author it anyway",
            ),
            model.Step(
                "add_scene_lighting_attribute_variant",
                {
                    "variant_set": "mood",
                    "variant_name": "bright",
                    "overrides": {"$key": {"inputs:intensity": 2000.0}},
                    "clear_masking_overrides": True,
                },
                note="clear the masking value first",
            ),
            model.Step(
                "add_scene_lighting_selection_variant",
                {
                    "variant_set": "rig",
                    "variant_name": "fill_only",
                    "activations": {"$key": False, "$fill": True},
                    "set_as_default": True,
                    "clear_masking_overrides": True,
                },
                note="a light selection made the default",
            ),
            model.Step(
                "add_scene_lighting_selection_variant",
                {
                    "variant_set": "rig",
                    "variant_name": "both",
                    "activations": {"$key": True, "$fill": True},
                    "confirm_masked": True,
                },
            ),
            model.Step(
                "add_scene_lighting_selection_variant",
                {"variant_set": "rig", "variant_name": "chair", "activations": {"$seat": False}},
                note="a target outside /Scene/Lighting",
            ),
            model.Step(
                "add_scene_model_selection_variant",
                {
                    "prim_path": "$seat",
                    "variant_set": "model",
                    "variant_name": "unfrozen",
                    "asset_file_path": "$lib/unfrozen.usda",
                },
                note="an alternative whose root is not frozen",
            ),
            model.Step(
                "add_scene_model_selection_variant",
                {
                    "prim_path": "$seat",
                    "variant_set": "model",
                    "variant_name": "unfrozen",
                    "asset_file_path": "$lib/unfrozen.usda",
                    "fix_root_transforms": True,
                    "set_as_default": True,
                },
                note="retry with the repair, made the default",
            ),
            model.Step(
                "add_scene_model_selection_variant",
                {
                    "prim_path": "$seat",
                    "variant_set": "model",
                    "variant_name": "cube",
                    "asset_file_path": "$lib/rooted_mesh.usda",
                    "fix_root_prim": True,
                },
                note="an alternative with a geometry root, wrapped",
            ),
            model.Step(
                "add_scene_model_selection_variant",
                {
                    "prim_path": "$seat",
                    "variant_set": "model",
                    "variant_name": "nope",
                    "asset_file_path": "$lib/nope.usda",
                },
                note="an alternative that does not exist",
            ),
            model.Step("list_variants", {"prim_path": "$seat"}),
            model.Step(
                "select_scene_variant",
                {"prim_path": "/Scene/Nope", "variant_set": "model", "variant_name": "cube"},
            ),
            model.Step(
                "remove_scene_variant",
                {"prim_path": "/Scene/Nope", "variant_set": "model", "variant_name": "cube"},
            ),
            model.Step(
                "remove_scene_variant_set", {"prim_path": "/Scene/Nope", "variant_set": "model"}
            ),
        ),
    ),
)
