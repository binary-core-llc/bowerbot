# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Lights and cameras: every light type, scene and asset lights, cameras, and their edits."""

from __future__ import annotations

from tests.golden import model

LIGHT_TYPES = (
    "DistantLight",
    "DomeLight",
    "SphereLight",
    "RectLight",
    "DiskLight",
    "CylinderLight",
)


def _table(save: str = "table") -> model.Step:
    return model.Step(
        "place_asset",
        {
            "asset_file_path": "$lib/table.usda",
            "asset_name": "Table",
            "group": "Furniture",
            **model.at(0.0),
        },
        save=save,
        note="place a table",
    )


SCENARIOS = (
    model.Scenario(
        "lights/every_type",
        "One scene light of every type, with the defaults BowerBot authors.",
        tuple(
            model.Step(
                "create_light",
                {
                    "light_type": kind,
                    "light_name": kind.replace("Light", ""),
                    **model.at(float(index), 3.0, 0.0),
                },
                note=f"a {kind} with default values",
            )
            for index, kind in enumerate(LIGHT_TYPES)
        )
        + (model.Step("list_scene"),),
    ),
    model.Scenario(
        "lights/scene_light_edits",
        "A scene light: values, rotation, texture, update, and removal.",
        (
            model.Step(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "light_name": "Key",
                    **model.at(2.0, 3.0, 1.0),
                    "attributes": {
                        "inputs:intensity": 800.0,
                        "inputs:color": [1.0, 0.9, 0.8],
                        "inputs:radius": 0.2,
                    },
                },
                save="key",
                note="a warm key light with values",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "DistantLight",
                    "light_name": "Sun",
                    "rotate_x": -45.0,
                    "rotate_y": 30.0,
                },
                save="sun",
                note="a sun, turned",
            ),
            model.Step(
                "create_light",
                {"light_type": "DomeLight", "light_name": "Sky", "texture": "$lib/hdri/studio.hdr"},
                save="sky",
                note="a dome light with an HDRI from the library",
            ),
            model.Step(
                "update_light",
                {"prim_path": "$key", **model.at(0.0, 4.0, 0.0)},
                note="move the key",
            ),
            model.Step(
                "update_light", {"prim_path": "$sun", "rotate_x": -60.0}, note="turn the sun"
            ),
            model.Step(
                "update_light",
                {"prim_path": "$sky", "texture": "$lib/textures/wood_diffuse.png"},
                note="swap the dome's texture",
            ),
            model.Step(
                "create_light",
                {"light_type": "SphereLight", "light_name": "Key"},
                note="a second light with a taken name",
            ),
            model.Step("remove_light", {"prim_path": "$key"}),
            model.Step("remove_light", {"prim_path": "$sky"}),
            model.Step("list_scene"),
            model.Step("list_project_assets", note="does the project still keep the textures?"),
        ),
    ),
    model.Scenario(
        "lights/asset_lights",
        "Lights inside an asset: authored in its lgt.usda, shared by every placement.",
        (
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/lamp/lamp.usda",
                    "asset_name": "Lamp",
                    "group": "Props",
                    **model.at(0.0),
                },
                save="lamp",
                note="place the lamp",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "light_name": "Bulb",
                    "asset_prim_path": "$lamp",
                    **model.at(0.0, 0.1, 0.0),
                    "attributes": {"inputs:radius": 0.05},
                },
                save="bulb",
                note="a bulb inside the lamp (default position mode)",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "RectLight",
                    "light_name": "Panel",
                    "asset_prim_path": "$lamp",
                    "position_mode": "absolute",
                    **model.at(0.0, 0.6, 0.0),
                },
                note="a panel at an absolute position",
            ),
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/lamp/lamp.usda",
                    "asset_name": "Lamp",
                    "group": "Props",
                    **model.at(2.0),
                },
                note="a second lamp: it shares the lights",
            ),
            model.Step(
                "update_light",
                {"prim_path": "$bulb", **model.at(0.0, 0.2, 0.0)},
                note="move the bulb (both lamps)",
            ),
            model.Step(
                "create_light",
                {"light_type": "DomeLight", "light_name": "Sky", "asset_prim_path": "$lamp"},
                note="a dome light cannot live inside an asset",
            ),
            model.Step("remove_light", {"prim_path": "$bulb"}),
            model.Step("list_scene"),
        ),
    ),
    model.Scenario(
        "lights/light_linking",
        "A light that only lights some prims.",
        (
            _table(),
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/chair.usda",
                    "asset_name": "Chair",
                    "group": "Furniture",
                    **model.at(2.0),
                },
                save="chair",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "light_name": "Spot",
                    **model.at(0.0, 3.0, 0.0),
                    "light_link_includes": ["$table"],
                },
                save="spot",
                note="light only the table",
            ),
            model.Step(
                "remove_prim", {"prim_path": "$table"}, note="remove the table the light links to"
            ),
            model.Step("list_scene"),
        ),
    ),
    model.Scenario(
        "lights/files_named_by_path",
        "A texture or material named by its path inside the library, and two library files "
        "that share a name: is the file that was named the one that gets used?",
        (
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "table.usda",
                    "asset_name": "Table",
                    "group": "Furniture",
                    **model.at(0.0),
                },
                save="table",
                note="an asset named by its path inside the library",
            ),
            model.Step(
                "bind_material",
                {"prim_path": "$table/asset/Top", "material_file": "materials/oak.usda"},
                note="a material file named the same way",
            ),
            model.Step(
                "create_light",
                {"light_type": "DomeLight", "light_name": "Sky", "texture": "hdri/studio.hdr"},
                save="sky",
                note="a texture named the same way",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "DomeLight",
                    "light_name": "Wood",
                    "texture": "$lib/textures/wood_diffuse.png",
                },
                note="textures/wood_diffuse.png",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "DomeLight",
                    "light_name": "Wood2",
                    "texture": "$lib/other/wood_diffuse.png",
                },
                note="other/wood_diffuse.png: the same name, other content",
            ),
            model.Step(
                "create_light",
                {"light_type": "DomeLight", "light_name": "Plain"},
                save="plain",
                note="a dome with no texture yet",
            ),
            model.Step(
                "add_scene_lighting_attribute_variant",
                {
                    "variant_set": "look",
                    "variant_name": "panel",
                    "overrides": {"$plain": {"inputs:texture:file": "textures/panel.png"}},
                },
                note="textures/panel.png, while other/panel.png also exists",
            ),
            model.Step(
                "create_light",
                {"light_type": "DomeLight", "light_name": "Lost", "texture": "hdri/nope.hdr"},
                note="a texture that is nowhere",
            ),
        ),
    ),
    model.Scenario(
        "lights/refusals_and_properties",
        "Light property listings, and light calls that cannot work.",
        tuple(
            model.Step("list_light_type_properties", {"light_type": kind}) for kind in LIGHT_TYPES
        )
        + (
            model.Step(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "light_name": "Bad",
                    "attributes": {"inputs:nope": 1.0},
                },
                note="an attribute the light type does not have",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "light_name": "Bad",
                    "texture": "$lib/hdri/studio.hdr",
                },
                note="a texture on a light type without a texture input",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "light_name": "Bad",
                    "asset_prim_path": "/Scene/Nope",
                },
                note="inside an asset that does not exist",
            ),
            model.Step(
                "update_light",
                {"prim_path": "/Scene/Lighting/Nope", **model.at(0.0)},
                note="a light that does not exist",
            ),
            model.Step("remove_light", {"prim_path": "/Scene/Lighting/Nope"}),
        ),
    ),
    model.Scenario(
        "cameras/create_update_remove",
        "Cameras: placed, aimed, turned, given lens values, moved and removed.",
        (
            _table(),
            model.Step("list_camera_properties"),
            model.Step(
                "create_camera",
                {
                    "camera_name": "Front",
                    **model.at(0.0, 1.5, 5.0),
                    "look_at": model.Point(0.0, 0.75, 0.0),
                },
                save="front",
                note="a camera looking at the table",
            ),
            model.Step(
                "create_camera",
                {
                    "camera_name": "Top",
                    **model.at(0.0, 8.0, 0.0),
                    "rotate_x": -90.0,
                    "attributes": {"focalLength": 35.0, "projection": "orthographic"},
                },
                save="top",
                note="an overhead orthographic camera",
            ),
            model.Step(
                "update_camera",
                {
                    "prim_path": "$front",
                    **model.at(3.0, 2.0, 3.0),
                    "look_at": model.Point(0.0, 0.75, 0.0),
                },
                note="move the front camera and re-aim it",
            ),
            model.Step(
                "update_camera",
                {"prim_path": "$top", "rotate_z": 90.0},
                note="turn the overhead camera",
            ),
            model.Step("create_camera", {"camera_name": "Front"}, note="a taken name"),
            model.Step(
                "create_camera",
                {"camera_name": "Bad", "attributes": {"nope": 1}},
                note="an attribute cameras do not have",
            ),
            model.Step("remove_camera", {"prim_path": "$top"}),
            model.Step("remove_camera", {"prim_path": "/Scene/Cameras/Nope"}),
            model.Step("list_scene"),
        ),
    ),
)
