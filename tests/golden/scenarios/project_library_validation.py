# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Projects, the library and texture searches, validation and packaging."""

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


SCENARIOS = (
    model.Scenario(
        "projects/lifecycle",
        "Projects: list, create a second one, switch between them, refusals.",
        (
            model.Step("list_projects"),
            model.Step("get_current_project"),
            _place("crate.usda", "Crate"),
            model.Step(
                "create_project",
                {"name": "second", "up_axis": "Z", "meters_per_unit": 0.01},
                note="a second project, Z-up in centimeters: it becomes current",
            ),
            model.Step("get_current_project"),
            _place("chair.usda", "Chair", "Furniture"),
            model.Step("list_projects"),
            model.Step("open_project", {"name": "golden"}, note="back to the first project"),
            model.Step("list_scene", note="the crate is still there, the chair is not"),
            model.Step("open_project", {"name": "nope"}, note="a project that does not exist"),
            model.Step(
                "create_project",
                {"name": "golden", "up_axis": "Y", "meters_per_unit": 1.0},
                note="a name that is taken",
            ),
            model.Step(
                "create_project",
                {"name": "odd name!", "up_axis": "Y", "meters_per_unit": 1.0},
                note="a name with a space and a symbol",
            ),
            model.Step(
                "create_project",
                {"name": "third", "up_axis": "X", "meters_per_unit": 1.0},
                note="an up axis that does not exist",
            ),
            model.Step(
                "create_project",
                {"name": "third", "up_axis": "Y", "meters_per_unit": 0},
                note="zero meters per unit",
            ),
            model.Step("list_projects"),
        ),
    ),
    model.Scenario(
        "library/search_and_list",
        "The asset library: searches and listings by category.",
        (
            model.Step("search_assets", {"query": "chair"}),
            model.Step("search_assets", {"query": "LAMP"}, note="case does not matter"),
            model.Step("search_assets", {"query": "zzz"}, note="nothing matches"),
            model.Step("search_assets", {"query": "a", "limit": 2}, note="limited to 2"),
            model.Step("list_assets"),
            model.Step("list_assets", {"category": "package"}),
            model.Step("list_assets", {"category": "mtl"}),
            model.Step("list_assets", {"category": "geo"}),
        ),
    ),
    model.Scenario(
        "library/textures",
        "Texture searches and listings, and deleting a project texture.",
        (
            model.Step("search_textures", {"query": "studio"}),
            model.Step("search_textures", {"query": "wood", "category": "material"}),
            model.Step("list_textures"),
            model.Step("list_textures", {"category": "hdri"}),
            model.Step(
                "create_light",
                {"light_type": "DomeLight", "light_name": "Sky", "texture": "$lib/hdri/studio.hdr"},
                save="sky",
                note="a dome light copies the HDRI into the project",
            ),
            model.Step(
                "delete_project_texture",
                {"file_name": "studio.hdr"},
                note="the texture is still used by the light",
            ),
            model.Step("remove_light", {"prim_path": "$sky"}),
            model.Step("delete_project_texture", {"file_name": "studio.hdr"}, note="now unused"),
        ),
    ),
    model.Scenario(
        "validation/validate_and_package",
        "validate_scene and package_scene on a clean scene, then on a broken one.",
        (
            model.Step("validate_scene", note="an empty scene"),
            _place("table.usda", "Table", "Furniture", save="table"),
            _place("lamp/lamp.usda", "Lamp", x=2.0),
            model.Step(
                "create_light",
                {"light_type": "DomeLight", "light_name": "Sky", "texture": "$lib/hdri/studio.hdr"},
            ),
            model.Step("validate_scene"),
            model.Step("package_scene", note="a .usdz of the scene"),
            model.Step(
                "package_scene",
                {"for_apple_ar_quick_look": True},
                note="a .usdz for Apple's AR Quick Look",
            ),
            model.Step(
                "create_material",
                {
                    "prim_path": "$table/asset/Top",
                    "material_name": "oak",
                    "base_color_r": 0.55,
                    "base_color_g": 0.35,
                    "base_color_b": 0.2,
                },
                note="a BowerBot material (validation then reports it)",
            ),
            model.Step("validate_scene"),
            model.Step("package_scene", note="package a scene that has validation errors"),
        ),
    ),
)
