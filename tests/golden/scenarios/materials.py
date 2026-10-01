# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Materials: create, bind from the library, list, remove, clean up."""

from __future__ import annotations

from tests.golden import model


def _table(name: str = "Table", x: float = 0.0, save: str = "table") -> model.Step:
    return model.Step(
        "place_asset",
        {
            "asset_file_path": "$lib/table.usda",
            "asset_name": name,
            "group": "Furniture",
            **model.at(x),
        },
        save=save,
        note=f"place a table ({name}); its parts are Top, Leg_L and Leg_R",
    )


def _create(part: str, name: str, **values: float) -> model.Step:
    return model.Step(
        "create_material",
        {"prim_path": f"$table/asset/{part}", "material_name": name, **values},
        note=f"create the material {name} on the table's {part}",
    )


def _remove(part: str) -> model.Step:
    return model.Step(
        "remove_material",
        {"prim_path": f"$table/asset/{part}"},
        note=f"remove the material from the table's {part}",
    )


SCENARIOS = (
    model.Scenario(
        "materials/create_one",
        "One material on one part: mtl.usda appears and the root references it.",
        (
            _table(),
            _create(
                "Top", "oak", base_color_r=0.55, base_color_g=0.35, base_color_b=0.2, roughness=0.6
            ),
            model.Step("list_materials", note="list the materials the project's assets hold"),
        ),
    ),
    model.Scenario(
        "materials/remove_the_only_material",
        "Removing the only material deletes mtl.usda and the root's reference to it.",
        (
            _table(),
            _create("Top", "oak", base_color_r=0.55, base_color_g=0.35, base_color_b=0.2),
            _remove("Top"),
            model.Step("list_materials", note="nothing left to list"),
        ),
    ),
    model.Scenario(
        "materials/remove_one_of_two",
        "With two materials, removing one keeps mtl.usda with the other; the unused one goes.",
        (
            _table(),
            _create("Top", "oak", base_color_r=0.55, base_color_g=0.35, base_color_b=0.2),
            _create("Leg_L", "steel", metalness=1.0, roughness=0.3),
            _remove("Leg_L"),
            model.Step("list_materials", note="only oak is left"),
            _remove("Top"),
        ),
    ),
    model.Scenario(
        "materials/one_material_on_two_parts",
        "A material two parts use stays until the last part lets it go.",
        (
            _table(),
            _create("Leg_L", "steel", metalness=1.0),
            model.Step(
                "bind_material",
                {"prim_path": "$table/asset/Leg_R", "material_file": "$lib/materials/steel.usda"},
                note="bind the library's steel to the other leg",
            ),
            _remove("Leg_L"),
            _remove("Leg_R"),
        ),
    ),
    model.Scenario(
        "materials/replace_a_material",
        "Creating a second material on the same part replaces the first.",
        (
            _table(),
            _create("Top", "oak", base_color_r=0.55, base_color_g=0.35, base_color_b=0.2),
            _create("Top", "walnut", base_color_r=0.3, base_color_g=0.2, base_color_b=0.1),
            model.Step("list_materials", note="is oak still there?"),
            model.Step("cleanup_unused_materials", note="remove materials nothing binds"),
        ),
    ),
    model.Scenario(
        "materials/every_value",
        "Every create_material value is authored on both shader networks.",
        (
            _table(),
            _create(
                "Top",
                "glass",
                base_color_r=0.9,
                base_color_g=0.95,
                base_color_b=1.0,
                metalness=0.0,
                roughness=0.05,
                opacity=0.3,
            ),
        ),
    ),
    model.Scenario(
        "materials/whole_asset",
        "A material on the placement's asset prim binds the whole asset.",
        (
            _table(),
            model.Step(
                "create_material",
                {
                    "prim_path": "$table/asset",
                    "material_name": "paint",
                    "base_color_r": 0.1,
                    "base_color_g": 0.3,
                    "base_color_b": 0.8,
                },
                note="create a material on the whole table",
            ),
            model.Step("remove_material", {"prim_path": "$table/asset"}, note="remove it again"),
        ),
    ),
    model.Scenario(
        "materials/bind_from_library",
        "bind_material copies a library material into the asset and binds it.",
        (
            _table(),
            model.Step(
                "bind_material",
                {"prim_path": "$table/asset/Top", "material_file": "$lib/materials/oak.usda"},
                note="bind the library's oak to the Top",
            ),
            model.Step(
                "bind_material",
                {"prim_path": "$table/asset/Leg_L", "material_file": "$lib/materials/oak.usda"},
                note="bind oak again, to a leg",
            ),
            model.Step(
                "bind_material",
                {
                    "prim_path": "$table/asset/Leg_R",
                    "material_file": "$lib/materials/steel.usda",
                    "material_prim_path": "/steel",
                },
                note="bind steel by its prim path in the library file",
            ),
            model.Step("list_materials"),
            _remove("Top"),
        ),
    ),
    model.Scenario(
        "materials/shared_asset",
        "Two placements share one asset folder: a material edit asks first, then reaches both.",
        (
            _table(),
            _table("Table", 2.0, save="table_2"),
            _create("Top", "oak", base_color_r=0.55, base_color_g=0.35, base_color_b=0.2),
            model.Step(
                "create_material",
                {
                    "prim_path": "$table/asset/Top",
                    "material_name": "oak",
                    "base_color_r": 0.55,
                    "base_color_g": 0.35,
                    "base_color_b": 0.2,
                    "confirm_shared_modification": True,
                },
                note="confirm that both tables get it",
            ),
            model.Step(
                "bind_material",
                {"prim_path": "$table_2/asset/Leg_L", "material_file": "$lib/materials/steel.usda"},
                note="bind_material on the second table asks too",
            ),
        ),
    ),
    model.Scenario(
        "materials/asset_with_its_own_material",
        "An asset that ships a textured material: add, list and remove around it.",
        (
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/lamp/lamp.usda",
                    "asset_name": "Lamp",
                    "group": "Props",
                    **model.at(0),
                },
                save="lamp",
                note="place the lamp; its Shade ships the brass material",
            ),
            model.Step("list_materials", note="brass comes with the lamp"),
            model.Step(
                "create_material",
                {
                    "prim_path": "$lamp/asset/Base",
                    "material_name": "black",
                    "base_color_r": 0.02,
                    "base_color_g": 0.02,
                    "base_color_b": 0.02,
                },
                note="a new material on the Base",
            ),
            model.Step(
                "remove_material",
                {"prim_path": "$lamp/asset/Shade"},
                note="remove the shipped brass from the Shade",
            ),
            model.Step(
                "remove_material",
                {"prim_path": "$lamp/asset/Base"},
                note="remove the Base's material",
            ),
            model.Step("list_materials"),
        ),
    ),
    model.Scenario(
        "materials/refusals",
        "Material calls that cannot work are refused, and change nothing.",
        (
            _table(),
            model.Step(
                "create_material",
                {"prim_path": "$table/asset/Nope", "material_name": "oak"},
                note="a part the table does not have",
            ),
            model.Step(
                "create_material",
                {"prim_path": "/Scene", "material_name": "oak"},
                note="the scene root is not an asset",
            ),
            model.Step(
                "bind_material",
                {"prim_path": "$table/asset/Top", "material_file": "$lib/materials/nope.usda"},
                note="a material file that does not exist",
            ),
            model.Step(
                "bind_material",
                {"prim_path": "$table/asset/Top", "material_file": "$lib/table.usda"},
                note="a file that holds no material",
            ),
            model.Step(
                "remove_material",
                {"prim_path": "$table/asset/Top"},
                note="remove a material that was never added",
            ),
            model.Step(
                "create_material",
                {"prim_path": "$table/asset/Top", "material_name": "red", "base_color_r": 2.0},
                note="a color value above 1",
            ),
        ),
    ),
    model.Scenario(
        "materials/remove_a_shipped_binding",
        "remove_material on a part whose material and binding ship inside the asset's geometry "
        "file: is the part left without a material?",
        (
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/stand/stand.usda",
                    "asset_name": "Stand",
                    "group": "Furniture",
                    **model.at(0.0),
                },
                save="stand",
                note="the stand's wood is bound to its Top inside geo.usda",
            ),
            model.Step("list_prim_children", {"prim_path": "$stand"}),
            model.Step("remove_material", {"prim_path": "$stand/asset/Top"}),
            model.Step(
                "list_prim_children",
                {"prim_path": "$stand"},
                note="does the Top still show wood?",
            ),
            model.Step(
                "create_material",
                {"prim_path": "$stand/asset/Top", "material_name": "paint", "base_color_r": 1.0},
                note="a new material over the shipped one",
            ),
            model.Step("remove_material", {"prim_path": "$stand/asset/Top"}),
            model.Step(
                "list_prim_children",
                {"prim_path": "$stand"},
                note="does the Top show nothing, or wood again?",
            ),
        ),
    ),
    model.Scenario(
        "materials/read_only_calls",
        "list_materials and cleanup_unused_materials on an empty project.",
        (
            model.Step("list_materials"),
            model.Step("cleanup_unused_materials"),
        ),
    ),
)
