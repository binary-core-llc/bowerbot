# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scene editing: move, rename, remove, attributes, snapshots, and the scene listings."""

from __future__ import annotations

from tests.golden import model


def _place(
    asset: str, name: str, group: str = "Furniture", x: float = 0.0, save: str | None = None
) -> model.Step:
    return model.Step(
        "place_asset",
        {"asset_file_path": f"$lib/{asset}", "asset_name": name, "group": group, **model.at(x)},
        save=save,
        note=f"place {asset} as {name} in {group}",
    )


SCENARIOS = (
    model.Scenario(
        "editing/create_stage",
        "create_stage reopens the project's scene; the filename is only a label.",
        (
            _place("chair.usda", "Chair"),
            model.Step("create_stage", {"filename": "other_name"}),
            model.Step("create_stage"),
            model.Step("list_scene"),
        ),
    ),
    model.Scenario(
        "editing/move",
        "move_asset: position only, rotation only, both, and a part of an asset.",
        (
            _place("chair.usda", "Chair", save="chair"),
            model.Step(
                "move_asset", {"prim_path": "$chair", **model.at(2.0, 0.0, 1.0)}, note="move it"
            ),
            model.Step(
                "move_asset", {"prim_path": "$chair", "rotate_y": 45.0}, note="turn it only"
            ),
            model.Step(
                "move_asset",
                {"prim_path": "$chair", "translate_x": model.Meters(0.5)},
                note="change only x",
            ),
            model.Step(
                "move_asset",
                {"prim_path": "$chair/asset/Seat", **model.at(0.0, 1.0, 0.0)},
                note="move a part inside the asset",
            ),
            model.Step(
                "move_asset",
                {"prim_path": "/Scene/Furniture/Nope", **model.at(0.0)},
                note="a prim that does not exist",
            ),
            model.Step("list_scene"),
        ),
    ),
    model.Scenario(
        "editing/move_nested",
        "Moving a placement nested inside another asset.",
        (
            _place("table.usda", "Table", save="table"),
            model.Step(
                "place_asset_inside",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "Crate",
                    "container_prim_path": "$table",
                    "group": "Props",
                    **model.at(0.0),
                },
                save="crate",
                note="a crate on the table",
            ),
            model.Step(
                "move_asset",
                {"prim_path": "$crate", **model.at(0.3, 0.8, 0.0)},
                note="move the nested crate",
            ),
            model.Step(
                "move_asset",
                {"prim_path": "$table", **model.at(3.0)},
                note="move the table: the crate goes with it",
            ),
        ),
    ),
    model.Scenario(
        "editing/rename",
        "rename_prim: a placement, into another group, onto a taken name, a group itself.",
        (
            _place("chair.usda", "Chair", save="chair"),
            _place("crate.usda", "Crate", "Props", 1.0, save="crate"),
            model.Step(
                "rename_prim", {"old_path": "$chair", "new_path": "/Scene/Furniture/Armchair"}
            ),
            model.Step(
                "rename_prim",
                {"old_path": "/Scene/Furniture/Armchair", "new_path": "/Scene/Props/Armchair"},
                note="into another group",
            ),
            model.Step(
                "rename_prim",
                {"old_path": "/Scene/Props/Armchair", "new_path": "$crate"},
                note="onto a name another placement has",
            ),
            model.Step(
                "rename_prim",
                {"old_path": "/Scene/Props", "new_path": "/Scene/Storage"},
                note="rename a whole group",
            ),
            model.Step(
                "rename_prim",
                {"old_path": "/Scene/Nope", "new_path": "/Scene/Other"},
                note="a prim that does not exist",
            ),
            model.Step("list_scene"),
        ),
    ),
    model.Scenario(
        "editing/remove",
        "remove_prim: a placement, a part, a group, a missing prim, the scene root.",
        (
            _place("chair.usda", "Chair", save="chair"),
            _place("table.usda", "Table", x=2.0, save="table"),
            _place("crate.usda", "Crate", "Props", 4.0),
            model.Step("remove_prim", {"prim_path": "$chair"}, note="remove a placement"),
            model.Step(
                "remove_prim", {"prim_path": "$table/asset/Leg_L"}, note="remove a part of an asset"
            ),
            model.Step("remove_prim", {"prim_path": "/Scene/Props"}, note="remove a group"),
            model.Step(
                "remove_prim", {"prim_path": "/Scene/Nope"}, note="a prim that does not exist"
            ),
            model.Step("remove_prim", {"prim_path": "/Scene"}, note="the scene root"),
            model.Step("list_scene"),
            model.Step("list_project_assets", note="which copies are still in use"),
        ),
    ),
    model.Scenario(
        "editing/attributes",
        "set_prim_attribute and list_prim_attributes on a placement and a part.",
        (
            _place("chair.usda", "Chair", save="chair"),
            model.Step("list_prim_attributes", {"prim_path": "$chair"}),
            model.Step("list_prim_attributes", {"prim_path": "$chair/asset/Seat"}),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$chair", "attribute_name": "visibility", "value": "invisible"},
                note="hide the chair",
            ),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$chair", "attribute_name": "visibility", "value": None},
                note="clear it again",
            ),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$chair/asset/Seat", "attribute_name": "size", "value": 2.0},
                note="a part's own attribute, overridden in the scene",
            ),
            model.Step(
                "set_prim_attribute",
                {
                    "prim_path": "$chair",
                    "attribute_name": "userProperties:note",
                    "value": "front row",
                },
                note="custom user data",
            ),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$chair", "attribute_name": "xformOp:scale", "value": [2, 2, 2]},
                note="scale the placement",
            ),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$chair", "attribute_name": "visibility", "value": 5},
                note="a value of the wrong type",
            ),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "/Scene/Nope", "attribute_name": "visibility", "value": "invisible"},
                note="a prim that does not exist",
            ),
            model.Step("list_prim_attributes", {"prim_path": "$chair"}),
        ),
    ),
    model.Scenario(
        "editing/snapshots",
        "Named snapshots: save, list, overwrite, delete.",
        (
            _place("chair.usda", "Chair"),
            model.Step("save_scene_snapshot", {"name": "first"}),
            _place("crate.usda", "Crate", "Props", 1.0),
            model.Step("save_scene_snapshot", {"name": "first"}, note="the name is taken"),
            model.Step(
                "save_scene_snapshot", {"name": "first", "force": True}, note="overwrite it"
            ),
            model.Step("save_scene_snapshot", {"name": "scene"}, note="the scene's own name"),
            model.Step("save_scene_snapshot", {"name": "with space!"}, note="a name to be cleaned"),
            model.Step("list_scene_snapshots"),
            model.Step("delete_scene_snapshot", {"name": "first"}),
            model.Step(
                "delete_scene_snapshot", {"name": "nope"}, note="a snapshot that does not exist"
            ),
            model.Step("list_scene_snapshots"),
        ),
    ),
    model.Scenario(
        "editing/grid_layout",
        "compute_grid_layout only computes positions; it places nothing.",
        (
            model.Step("compute_grid_layout", {"count": 6, "spacing": model.Meters(2.0)}),
            model.Step("compute_grid_layout", {"count": 1}),
            model.Step("compute_grid_layout", {"count": 0}, note="zero items"),
        ),
    ),
    model.Scenario(
        "editing/listings",
        "list_scene and list_prim_children on a scene with groups, parts and nested assets.",
        (
            model.Step("list_scene", note="an empty scene"),
            _place("table.usda", "Table", save="table"),
            model.Step(
                "place_asset_inside",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "Crate",
                    "container_prim_path": "$table",
                    "group": "Props",
                    **model.at(0.0),
                },
            ),
            _place("lamp/lamp.usda", "Lamp", "Props", 2.0),
            model.Step("list_scene"),
            model.Step("list_prim_children", {"prim_path": "/Scene"}),
            model.Step("list_prim_children", {"prim_path": "$table"}),
            model.Step("list_prim_children", {"prim_path": "$table/asset"}),
            model.Step("list_prim_children", {"prim_path": "/Scene/Nope"}),
        ),
    ),
)
