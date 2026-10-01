# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Placement: place_asset, add_asset_to_asset, place_layout, and the project's asset copies."""

from __future__ import annotations

from tests.golden import model


def _place(
    asset: str,
    name: str,
    group: str = "Props",
    x: float = 0.0,
    save: str | None = None,
    note: str = "",
    **extra: object,
) -> model.Step:
    return model.Step(
        "place_asset",
        {
            "asset_file_path": f"$lib/{asset}",
            "asset_name": name,
            "group": group,
            **model.at(x),
            **extra,
        },
        save=save,
        note=note or f"place {asset} as {name} in {group}",
    )


SCENARIOS = (
    model.Scenario(
        "placement/every_library_asset",
        "Each kind of library asset is placed: loose files, other units and axes, a folder, "
        "a package.",
        (
            _place("table.usda", "Table", "Furniture", 0.0, note="a loose file with three parts"),
            _place(
                "chair_cm.usda", "ChairCm", "Furniture", 2.0, note="a chair authored in centimeters"
            ),
            _place("post_z.usda", "Post", "Architecture", 4.0, note="a post authored Z-up"),
            _place(
                "lamp/lamp.usda",
                "Lamp",
                "Props",
                6.0,
                note="an ASWF folder with its own materials and textures",
            ),
            _place("gem.usdz", "Gem", "Products", 8.0, note="a USDZ package"),
            _place("ground.usda", "Ground", "Architecture", 0.0, note="a ground mesh"),
            model.Step("list_scene", note="every placement, where it stands and how big it is"),
            model.Step("list_project_assets", note="the copies the project now holds"),
        ),
    ),
    model.Scenario(
        "placement/same_asset_twice",
        "Two placements of one asset share one project copy and get the next number.",
        (
            _place("chair.usda", "Chair", "Furniture", 0.0, save="first"),
            _place("chair.usda", "Chair", "Furniture", 1.0, save="second"),
            _place("chair.usda", "chair", "Furniture", 2.0, note="the same name in lowercase"),
            model.Step("list_project_assets"),
        ),
    ),
    model.Scenario(
        "placement/rotation_and_relative_paths",
        "A turned placement, and an asset named by its path inside the library.",
        (
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "chair.usda",
                    "asset_name": "Chair",
                    "group": "Furniture",
                    **model.at(1.0, 0.0, 2.0),
                    "rotate_y": 90.0,
                },
                save="chair",
                note="a library-relative path, turned 90 degrees",
            ),
            model.Step("list_prim_children", {"prim_path": "$chair"}),
        ),
    ),
    model.Scenario(
        "placement/assets_that_need_repair",
        "Assets with an unfrozen root or a geometry root are refused, then repaired on request.",
        (
            _place("unfrozen.usda", "Unfrozen", note="a root with a translate and scale"),
            _place(
                "unfrozen.usda",
                "Unfrozen",
                fix_root_transforms=True,
                note="retry, moving the root transform onto the parts",
            ),
            _place("rooted_mesh.usda", "RootedMesh", x=2.0, note="a cube as the root prim"),
            _place(
                "rooted_mesh.usda",
                "RootedMesh",
                x=2.0,
                fix_root_prim=True,
                note="retry, wrapping the root in an Xform",
            ),
        ),
    ),
    model.Scenario(
        "placement/refusals",
        "Placements that cannot work are refused and change nothing.",
        (
            _place("nope.usda", "Nope", note="a file that does not exist"),
            _place("hdri/studio.hdr", "Hdr", note="not a USD file"),
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/table.usda",
                    "asset_name": "Table",
                    "group": "Kitchen",
                    **model.at(0.0),
                },
                note="a group outside the allowed list",
            ),
            model.Step(
                "place_asset",
                {"asset_file_path": "$lib/table.usda", "asset_name": "Table", "group": "Props"},
                note="no position",
            ),
            _place("table.usda", "", note="an empty name"),
        ),
    ),
    model.Scenario(
        "placement/asset_to_asset",
        "Assets added to another asset, and what that shares.",
        (
            _place("table.usda", "Table", "Furniture", save="table"),
            model.Step(
                "add_asset_to_asset",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "Crate",
                    "parent_prim_path": "$table",
                    "group": "Props",
                    **model.at(0.0, 0.0, 0.0),
                },
                save="crate",
                note="a crate on the table (default position mode)",
            ),
            model.Step(
                "add_asset_to_asset",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "Crate",
                    "parent_prim_path": "$table",
                    "group": "Props",
                    **model.at(0.3, 0.8, 0.0),
                    "position_mode": "absolute",
                },
                note="a second crate at an absolute position",
            ),
            model.Step("list_prim_children", {"prim_path": "$table"}),
            _place(
                "table.usda",
                "Table",
                "Furniture",
                3.0,
                save="table_2",
                note="a second table: it shares the folder, and so the crates",
            ),
            model.Step(
                "add_asset_to_asset",
                {
                    "asset_file_path": "$lib/chair.usda",
                    "asset_name": "Chair",
                    "parent_prim_path": "$table",
                    "group": "Props",
                    **model.at(0.0),
                },
                note="adding to a shared folder asks first",
            ),
            model.Step(
                "add_asset_to_asset",
                {
                    "asset_file_path": "$lib/chair.usda",
                    "asset_name": "Chair",
                    "parent_prim_path": "$table",
                    "group": "Props",
                    **model.at(0.0),
                    "confirm_shared_modification": True,
                },
                note="confirmed",
            ),
            model.Step("remove_prim", {"prim_path": "$crate"}, note="remove the first crate"),
            model.Step("cleanup_unused_contents", note="clean up unused added-asset contents"),
        ),
    ),
    model.Scenario(
        "placement/units_and_axes",
        "Assets in other units and axes, or declaring none: placed, added to another asset, "
        "moved and lit; the grid layout in the project's axes.",
        (
            model.Step("compute_grid_layout", {"count": 4}, note="a grid for four objects"),
            _place(
                "bare.usda", "Bare", "Props", 0.0, note="a loose file declaring no units or axis"
            ),
            _place(
                "bare_kit/bare_kit.usda",
                "BareKit",
                "Props",
                2.0,
                note="a folder declaring no units or axis",
            ),
            _place("chair_cm.usda", "ChairCm", "Furniture", 4.0, save="chair_cm"),
            model.Step(
                "add_asset_to_asset",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "Crate",
                    "parent_prim_path": "$chair_cm",
                    "group": "Props",
                    **model.at(4.0, 0.5, 0.0),
                },
                save="crate_in_cm",
                note="a meters crate added to a centimeters chair, at an absolute position",
            ),
            model.Step(
                "move_asset",
                {"prim_path": "$crate_in_cm", **model.at(4.2, 0.5, 0.0)},
                note="move the added crate 0.2 m along x",
            ),
            _place("post_z.usda", "Post", "Architecture", 6.0, save="post"),
            model.Step(
                "add_asset_to_asset",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "Crate",
                    "parent_prim_path": "$post",
                    "group": "Props",
                    **model.at(6.0, 1.0, 0.0),
                },
                save="crate_on_post",
                note="a Y-up crate added to a Z-up post, at an absolute position",
            ),
            model.Step(
                "move_asset",
                {"prim_path": "$crate_on_post", **model.at(6.0, 1.5, 0.0)},
                note="move the added crate 0.5 m up",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "light_name": "Bulb",
                    "asset_prim_path": "$chair_cm",
                    **model.at(0.0, 0.5, 0.0),
                    "attributes": {"inputs:radius": 0.05},
                },
                note="a bulb 0.5 m above the centimeters chair (bounds offset)",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "light_name": "Beacon",
                    "asset_prim_path": "$post",
                    **model.at(0.0, 0.5, 0.0),
                    "attributes": {"inputs:radius": 0.05},
                },
                note="a beacon 0.5 m above the Z-up post (bounds offset)",
            ),
            model.Step("list_scene", note="where everything stands and how big it is"),
        ),
    ),
    model.Scenario(
        "placement/packages_with_their_own_files",
        "Library packages whose root points to files of their own: do they keep their geometry "
        "and materials when imported, and when BowerBot later adds or removes a layer?",
        (
            _place(
                "cabinet/cabinet.usda",
                "Cabinet",
                "Furniture",
                0.0,
                save="cabinet",
                note="a root that payloads its own model file and references its own look file",
            ),
            model.Step("list_prim_children", {"prim_path": "$cabinet"}),
            _place(
                "workbench/workbench.usda",
                "Workbench",
                "Furniture",
                3.0,
                save="workbench",
                note="geo.usda plus a part referenced from a sub-folder",
            ),
            model.Step("list_prim_children", {"prim_path": "$workbench"}),
            model.Step(
                "create_light",
                {"light_type": "SphereLight", "light_name": "Glow", "asset_prim_path": "$cabinet"},
                save="glow",
                note="adding a light writes lgt.usda and rebuilds the cabinet's root arcs",
            ),
            model.Step(
                "bind_material",
                {"prim_path": "$workbench/asset/Top", "material_file": "$lib/materials/oak.usda"},
                note="binding a material writes mtl.usda and rebuilds the workbench's root arcs",
            ),
            model.Step(
                "remove_light",
                {"prim_path": "$glow"},
                note="removing the only light deletes lgt.usda and rebuilds the root arcs again",
            ),
            model.Step(
                "add_asset_to_asset",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "Crate",
                    "parent_prim_path": "$cabinet",
                    "group": "Props",
                    **model.at(0.0, 0.0, 0.0),
                    "position_mode": "bounds_offset",
                },
                note="a crate on top of the cabinet, by bounds offset (its top is 1 m up)",
            ),
            model.Step(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "light_name": "Lamp",
                    "asset_prim_path": "$workbench",
                    **model.at(0.0, 0.2, 0.0),
                    "attributes": {"inputs:radius": 0.05},
                },
                note="a light 0.2 m above the workbench (its vise tops out at 1.05 m)",
            ),
            model.Step("list_scene", note="what each package shows now"),
        ),
    ),
    model.Scenario(
        "placement/layout",
        "place_layout: patterns, enumerated transforms, validation first.",
        (
            model.Step(
                "place_layout",
                {
                    "validate_only": True,
                    "placements": [
                        {
                            "asset": "$lib/crate.usda",
                            "group": "Props",
                            "pattern": {
                                "type": "grid",
                                "origin": model.Point(0.0, 0.0, 0.0),
                                "count": [3, 2],
                                "spacing": [model.Meters(1.0), model.Meters(1.0)],
                            },
                        },
                    ],
                },
                note="lint a grid without placing it",
            ),
            model.Step(
                "place_layout",
                {
                    "placements": [
                        {
                            "asset": "$lib/crate.usda",
                            "group": "Props",
                            "pattern": {
                                "type": "grid",
                                "origin": model.Point(0.0, 0.0, 0.0),
                                "count": [3, 2],
                                "spacing": [model.Meters(1.0), model.Meters(1.0)],
                            },
                        },
                        {
                            "asset": "$lib/chair.usda",
                            "group": "Furniture",
                            "name": "Seat",
                            "transforms": [
                                {"translate": model.Point(5.0, 0.0, 0.0)},
                                {"translate": model.Point(6.0, 0.0, 0.0), "rotate": [0, 90, 0]},
                            ],
                        },
                        {
                            "asset": "$lib/table.usda",
                            "group": "Furniture",
                            "pattern": {
                                "type": "linear",
                                "origin": model.Point(0.0, 0.0, 4.0),
                                "count": 2,
                                "spacing": model.Point(2.0, 0.0, 0.0),
                            },
                        },
                    ],
                },
                note="a crate grid, two named chairs, a row of two tables",
            ),
            model.Step(
                "place_layout",
                {
                    "placements": [
                        {
                            "asset": "$lib/nope.usda",
                            "group": "Props",
                            "transforms": [{"translate": model.Point(0.0, 0.0, 0.0)}],
                        },
                        {"asset": "$lib/crate.usda", "group": "Props"},
                    ],
                },
                note="two bad entries: both are reported, nothing is placed",
            ),
            model.Step("list_scene"),
        ),
    ),
    model.Scenario(
        "placement/project_assets",
        "The project's asset copies: listing, deleting, and what is still in use.",
        (
            _place("chair.usda", "Chair", "Furniture", save="chair"),
            _place("crate.usda", "Crate", "Props", 1.0, save="crate"),
            model.Step("list_project_assets"),
            model.Step("list_project_assets", {"query": "cra"}, note="filtered"),
            model.Step("delete_project_asset", {"name": "crate"}, note="still used by a placement"),
            model.Step("remove_prim", {"prim_path": "$crate"}),
            model.Step("list_project_assets", note="the crate copy is now unused"),
            model.Step("delete_project_asset", {"name": "crate"}),
            model.Step("delete_project_asset", {"name": "nope"}, note="an asset the project lacks"),
            model.Step(
                "delete_project_texture",
                {"file_name": "nope.png"},
                note="a texture the project lacks",
            ),
        ),
    ),
    model.Scenario(
        "placement/freeze_asset",
        "freeze_asset moves a project asset's root transform onto its parts.",
        (
            _place("unfrozen.usda", "Unfrozen", fix_root_transforms=True, save="unfrozen"),
            model.Step("freeze_asset", {"name": "unfrozen"}, note="already frozen on intake"),
            model.Step("freeze_asset", note="every project asset"),
            model.Step("freeze_asset", {"name": "nope"}, note="an asset the project lacks"),
        ),
    ),
    model.Scenario(
        "placement/read_only_calls",
        "Placement listings on an empty project.",
        (
            model.Step("list_project_assets"),
            model.Step("cleanup_unused_contents"),
        ),
    ),
)
