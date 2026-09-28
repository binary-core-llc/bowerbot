# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Projects, the library and texture searches, validation and packaging."""

from __future__ import annotations

from tests.golden.model import Scenario, Step, at


def _place(asset: str, name: str, group: str = "Props", x: float = 0.0,
           save: str | None = None) -> Step:
    return Step(
        "place_asset",
        {"asset_file_path": f"$lib/{asset}", "asset_name": name, "group": group, **at(x)},
        save=save, note=f"place {asset} as {name}",
    )


SCENARIOS = (
    Scenario(
        "projects/lifecycle",
        "Projects: list, create a second one, switch between them, refusals.",
        (
            Step("list_projects"),
            Step("get_current_project"),
            _place("crate.usda", "Crate"),
            Step("create_project", {"name": "second", "up_axis": "Z", "meters_per_unit": 0.01},
                 note="a second project, Z-up in centimeters: it becomes current"),
            Step("get_current_project"),
            _place("chair.usda", "Chair", "Furniture"),
            Step("list_projects"),
            Step("open_project", {"name": "golden"}, note="back to the first project"),
            Step("list_scene", note="the crate is still there, the chair is not"),
            Step("open_project", {"name": "nope"}, note="a project that does not exist"),
            Step("create_project", {"name": "golden", "up_axis": "Y", "meters_per_unit": 1.0},
                 note="a name that is taken"),
            Step("create_project", {"name": "odd name!", "up_axis": "Y",
                                    "meters_per_unit": 1.0},
                 note="a name with a space and a symbol"),
            Step("create_project", {"name": "third", "up_axis": "X", "meters_per_unit": 1.0},
                 note="an up axis that does not exist"),
            Step("create_project", {"name": "third", "up_axis": "Y", "meters_per_unit": 0},
                 note="zero meters per unit"),
            Step("list_projects"),
        ),
    ),
    Scenario(
        "library/search_and_list",
        "The asset library: searches and listings by category.",
        (
            Step("search_assets", {"query": "chair"}),
            Step("search_assets", {"query": "LAMP"}, note="case does not matter"),
            Step("search_assets", {"query": "zzz"}, note="nothing matches"),
            Step("search_assets", {"query": "a", "limit": 2}, note="limited to 2"),
            Step("list_assets"),
            Step("list_assets", {"category": "package"}),
            Step("list_assets", {"category": "mtl"}),
            Step("list_assets", {"category": "geo"}),
        ),
    ),
    Scenario(
        "library/textures",
        "Texture searches and listings, and deleting a project texture.",
        (
            Step("search_textures", {"query": "studio"}),
            Step("search_textures", {"query": "wood", "category": "material"}),
            Step("list_textures"),
            Step("list_textures", {"category": "hdri"}),
            Step("create_light", {"light_type": "DomeLight", "light_name": "Sky",
                                  "texture": "$lib/hdri/studio.hdr"},
                 save="sky", note="a dome light copies the HDRI into the project"),
            Step("delete_project_texture", {"file_name": "studio.hdr"},
                 note="the texture is still used by the light"),
            Step("remove_light", {"prim_path": "$sky"}),
            Step("delete_project_texture", {"file_name": "studio.hdr"},
                 note="now unused"),
        ),
    ),
    Scenario(
        "validation/validate_and_package",
        "validate_scene and package_scene on a clean scene, then on a broken one.",
        (
            Step("validate_scene", note="an empty scene"),
            _place("table.usda", "Table", "Furniture", save="table"),
            _place("lamp/lamp.usda", "Lamp", x=2.0),
            Step("create_light", {"light_type": "DomeLight", "light_name": "Sky",
                                  "texture": "$lib/hdri/studio.hdr"}),
            Step("validate_scene"),
            Step("package_scene", note="a .usdz of the scene"),
            Step("package_scene", {"for_apple_ar_quick_look": True},
                 note="a .usdz for Apple's AR Quick Look"),
            Step("create_material", {"prim_path": "$table/asset/Top", "material_name": "oak",
                                     "base_color_r": 0.55, "base_color_g": 0.35,
                                     "base_color_b": 0.2},
                 note="a BowerBot material (validation then reports it)"),
            Step("validate_scene"),
            Step("package_scene", note="package a scene that has validation errors"),
        ),
    ),
)
