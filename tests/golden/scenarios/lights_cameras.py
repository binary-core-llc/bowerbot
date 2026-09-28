# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Lights and cameras: every light type, scene and asset lights, cameras, and their edits."""

from __future__ import annotations

from tests.golden.model import Point, Scenario, Step, at

LIGHT_TYPES = ("DistantLight", "DomeLight", "SphereLight", "RectLight", "DiskLight",
               "CylinderLight")


def _table(save: str = "table") -> Step:
    return Step(
        "place_asset",
        {"asset_file_path": "$lib/table.usda", "asset_name": "Table", "group": "Furniture",
         **at(0.0)},
        save=save, note="place a table",
    )


SCENARIOS = (
    Scenario(
        "lights/every_type",
        "One scene light of every type, with the defaults BowerBot authors.",
        tuple(
            Step("create_light", {"light_type": kind, "light_name": kind.replace("Light", ""),
                                  **at(float(index), 3.0, 0.0)},
                 note=f"a {kind} with default values")
            for index, kind in enumerate(LIGHT_TYPES)
        ) + (Step("list_scene"),),
    ),
    Scenario(
        "lights/scene_light_edits",
        "A scene light: values, rotation, texture, update, and removal.",
        (
            Step("create_light",
                 {"light_type": "SphereLight", "light_name": "Key", **at(2.0, 3.0, 1.0),
                  "attributes": {"inputs:intensity": 800.0, "inputs:color": [1.0, 0.9, 0.8],
                                 "inputs:radius": 0.2}},
                 save="key", note="a warm key light with values"),
            Step("create_light",
                 {"light_type": "DistantLight", "light_name": "Sun", "rotate_x": -45.0,
                  "rotate_y": 30.0},
                 save="sun", note="a sun, turned"),
            Step("create_light",
                 {"light_type": "DomeLight", "light_name": "Sky",
                  "texture": "$lib/hdri/studio.hdr"},
                 save="sky", note="a dome light with an HDRI from the library"),
            Step("update_light", {"prim_path": "$key", **at(0.0, 4.0, 0.0)}, note="move the key"),
            Step("update_light", {"prim_path": "$sun", "rotate_x": -60.0}, note="turn the sun"),
            Step("update_light", {"prim_path": "$sky", "texture": "$lib/textures/wood_diffuse.png"},
                 note="swap the dome's texture"),
            Step("create_light", {"light_type": "SphereLight", "light_name": "Key"},
                 note="a second light with a taken name"),
            Step("remove_light", {"prim_path": "$key"}),
            Step("remove_light", {"prim_path": "$sky"}),
            Step("list_scene"),
            Step("list_project_assets", note="does the project still keep the textures?"),
        ),
    ),
    Scenario(
        "lights/asset_lights",
        "Lights inside an asset: authored in its lgt.usda, shared by every placement.",
        (
            Step("place_asset",
                 {"asset_file_path": "$lib/lamp/lamp.usda", "asset_name": "Lamp",
                  "group": "Props", **at(0.0)},
                 save="lamp", note="place the lamp"),
            Step("create_light",
                 {"light_type": "SphereLight", "light_name": "Bulb", "asset_prim_path": "$lamp",
                  **at(0.0, 0.1, 0.0), "attributes": {"inputs:radius": 0.05}},
                 save="bulb", note="a bulb inside the lamp (default position mode)"),
            Step("create_light",
                 {"light_type": "RectLight", "light_name": "Panel", "asset_prim_path": "$lamp",
                  "position_mode": "absolute", **at(0.0, 0.6, 0.0)},
                 note="a panel at an absolute position"),
            Step("place_asset",
                 {"asset_file_path": "$lib/lamp/lamp.usda", "asset_name": "Lamp",
                  "group": "Props", **at(2.0)},
                 note="a second lamp: it shares the lights"),
            Step("update_light", {"prim_path": "$bulb", **at(0.0, 0.2, 0.0)},
                 note="move the bulb (both lamps)"),
            Step("create_light",
                 {"light_type": "DomeLight", "light_name": "Sky", "asset_prim_path": "$lamp"},
                 note="a dome light cannot live inside an asset"),
            Step("remove_light", {"prim_path": "$bulb"}),
            Step("list_scene"),
        ),
    ),
    Scenario(
        "lights/light_linking",
        "A light that only lights some prims.",
        (
            _table(),
            Step("place_asset",
                 {"asset_file_path": "$lib/chair.usda", "asset_name": "Chair",
                  "group": "Furniture", **at(2.0)},
                 save="chair"),
            Step("create_light",
                 {"light_type": "SphereLight", "light_name": "Spot", **at(0.0, 3.0, 0.0),
                  "light_link_includes": ["$table"]},
                 save="spot", note="light only the table"),
            Step("remove_prim", {"prim_path": "$table"},
                 note="remove the table the light links to"),
            Step("list_scene"),
        ),
    ),
    Scenario(
        "lights/refusals_and_properties",
        "Light property listings, and light calls that cannot work.",
        tuple(
            Step("list_light_type_properties", {"light_type": kind}) for kind in LIGHT_TYPES
        ) + (
            Step("create_light", {"light_type": "SphereLight", "light_name": "Bad",
                                  "attributes": {"inputs:nope": 1.0}},
                 note="an attribute the light type does not have"),
            Step("create_light", {"light_type": "SphereLight", "light_name": "Bad",
                                  "texture": "$lib/hdri/studio.hdr"},
                 note="a texture on a light type without a texture input"),
            Step("create_light", {"light_type": "SphereLight", "light_name": "Bad",
                                  "asset_prim_path": "/Scene/Nope"},
                 note="inside an asset that does not exist"),
            Step("update_light", {"prim_path": "/Scene/Lighting/Nope", **at(0.0)},
                 note="a light that does not exist"),
            Step("remove_light", {"prim_path": "/Scene/Lighting/Nope"}),
        ),
    ),
    Scenario(
        "cameras/create_update_remove",
        "Cameras: placed, aimed, turned, given lens values, moved and removed.",
        (
            _table(),
            Step("list_camera_properties"),
            Step("create_camera",
                 {"camera_name": "Front", **at(0.0, 1.5, 5.0), "look_at": Point(0.0, 0.75, 0.0)},
                 save="front", note="a camera looking at the table"),
            Step("create_camera",
                 {"camera_name": "Top", **at(0.0, 8.0, 0.0), "rotate_x": -90.0,
                  "attributes": {"focalLength": 35.0, "projection": "orthographic"}},
                 save="top", note="an overhead orthographic camera"),
            Step("update_camera", {"prim_path": "$front", **at(3.0, 2.0, 3.0),
                                   "look_at": Point(0.0, 0.75, 0.0)},
                 note="move the front camera and re-aim it"),
            Step("update_camera", {"prim_path": "$top", "rotate_z": 90.0},
                 note="turn the overhead camera"),
            Step("create_camera", {"camera_name": "Front"}, note="a taken name"),
            Step("create_camera", {"camera_name": "Bad", "attributes": {"nope": 1}},
                 note="an attribute cameras do not have"),
            Step("remove_camera", {"prim_path": "$top"}),
            Step("remove_camera", {"prim_path": "/Scene/Cameras/Nope"}),
            Step("list_scene"),
        ),
    ),
)
