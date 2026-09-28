# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scene editing: move, rename, remove, attributes, snapshots, and the scene listings."""

from __future__ import annotations

from tests.golden.model import Meters, Scenario, Step, at


def _place(asset: str, name: str, group: str = "Furniture", x: float = 0.0,
           save: str | None = None) -> Step:
    return Step(
        "place_asset",
        {"asset_file_path": f"$lib/{asset}", "asset_name": name, "group": group, **at(x)},
        save=save, note=f"place {asset} as {name} in {group}",
    )


SCENARIOS = (
    Scenario(
        "editing/create_stage",
        "create_stage reopens the project's scene; the filename is only a label.",
        (
            _place("chair.usda", "Chair"),
            Step("create_stage", {"filename": "other_name"}),
            Step("create_stage"),
            Step("list_scene"),
        ),
    ),
    Scenario(
        "editing/move",
        "move_asset: position only, rotation only, both, and a part of an asset.",
        (
            _place("chair.usda", "Chair", save="chair"),
            Step("move_asset", {"prim_path": "$chair", **at(2.0, 0.0, 1.0)}, note="move it"),
            Step("move_asset", {"prim_path": "$chair", "rotate_y": 45.0}, note="turn it only"),
            Step("move_asset", {"prim_path": "$chair", "translate_x": Meters(0.5)},
                 note="change only x"),
            Step("move_asset", {"prim_path": "$chair/asset/Seat", **at(0.0, 1.0, 0.0)},
                 note="move a part inside the asset"),
            Step("move_asset", {"prim_path": "/Scene/Furniture/Nope", **at(0.0)},
                 note="a prim that does not exist"),
            Step("list_scene"),
        ),
    ),
    Scenario(
        "editing/move_nested",
        "Moving a placement nested inside another asset.",
        (
            _place("table.usda", "Table", save="table"),
            Step("place_asset_inside",
                 {"asset_file_path": "$lib/crate.usda", "asset_name": "Crate",
                  "container_prim_path": "$table", "group": "Props", **at(0.0)},
                 save="crate", note="a crate on the table"),
            Step("move_asset", {"prim_path": "$crate", **at(0.3, 0.8, 0.0)},
                 note="move the nested crate"),
            Step("move_asset", {"prim_path": "$table", **at(3.0)},
                 note="move the table: the crate goes with it"),
        ),
    ),
    Scenario(
        "editing/rename",
        "rename_prim: a placement, into another group, onto a taken name, a group itself.",
        (
            _place("chair.usda", "Chair", save="chair"),
            _place("crate.usda", "Crate", "Props", 1.0, save="crate"),
            Step("rename_prim", {"old_path": "$chair", "new_path": "/Scene/Furniture/Armchair"}),
            Step("rename_prim", {"old_path": "/Scene/Furniture/Armchair",
                                 "new_path": "/Scene/Props/Armchair"},
                 note="into another group"),
            Step("rename_prim", {"old_path": "/Scene/Props/Armchair", "new_path": "$crate"},
                 note="onto a name another placement has"),
            Step("rename_prim", {"old_path": "/Scene/Props", "new_path": "/Scene/Storage"},
                 note="rename a whole group"),
            Step("rename_prim", {"old_path": "/Scene/Nope", "new_path": "/Scene/Other"},
                 note="a prim that does not exist"),
            Step("list_scene"),
        ),
    ),
    Scenario(
        "editing/remove",
        "remove_prim: a placement, a part, a group, a missing prim, the scene root.",
        (
            _place("chair.usda", "Chair", save="chair"),
            _place("table.usda", "Table", x=2.0, save="table"),
            _place("crate.usda", "Crate", "Props", 4.0),
            Step("remove_prim", {"prim_path": "$chair"}, note="remove a placement"),
            Step("remove_prim", {"prim_path": "$table/asset/Leg_L"},
                 note="remove a part of an asset"),
            Step("remove_prim", {"prim_path": "/Scene/Props"}, note="remove a group"),
            Step("remove_prim", {"prim_path": "/Scene/Nope"}, note="a prim that does not exist"),
            Step("remove_prim", {"prim_path": "/Scene"}, note="the scene root"),
            Step("list_scene"),
            Step("list_project_assets", note="which copies are still in use"),
        ),
    ),
    Scenario(
        "editing/attributes",
        "set_prim_attribute and list_prim_attributes on a placement and a part.",
        (
            _place("chair.usda", "Chair", save="chair"),
            Step("list_prim_attributes", {"prim_path": "$chair"}),
            Step("list_prim_attributes", {"prim_path": "$chair/asset/Seat"}),
            Step("set_prim_attribute",
                 {"prim_path": "$chair", "attribute_name": "visibility", "value": "invisible"},
                 note="hide the chair"),
            Step("set_prim_attribute",
                 {"prim_path": "$chair", "attribute_name": "visibility", "value": None},
                 note="clear it again"),
            Step("set_prim_attribute",
                 {"prim_path": "$chair/asset/Seat", "attribute_name": "size", "value": 2.0},
                 note="a part's own attribute, overridden in the scene"),
            Step("set_prim_attribute",
                 {"prim_path": "$chair", "attribute_name": "userProperties:note",
                  "value": "front row"},
                 note="custom user data"),
            Step("set_prim_attribute",
                 {"prim_path": "$chair", "attribute_name": "xformOp:scale", "value": [2, 2, 2]},
                 note="scale the placement"),
            Step("set_prim_attribute",
                 {"prim_path": "$chair", "attribute_name": "visibility", "value": 5},
                 note="a value of the wrong type"),
            Step("set_prim_attribute",
                 {"prim_path": "/Scene/Nope", "attribute_name": "visibility", "value": "invisible"},
                 note="a prim that does not exist"),
            Step("list_prim_attributes", {"prim_path": "$chair"}),
        ),
    ),
    Scenario(
        "editing/snapshots",
        "Named snapshots: save, list, overwrite, delete.",
        (
            _place("chair.usda", "Chair"),
            Step("save_scene_snapshot", {"name": "first"}),
            _place("crate.usda", "Crate", "Props", 1.0),
            Step("save_scene_snapshot", {"name": "first"}, note="the name is taken"),
            Step("save_scene_snapshot", {"name": "first", "force": True}, note="overwrite it"),
            Step("save_scene_snapshot", {"name": "scene"}, note="the scene's own name"),
            Step("save_scene_snapshot", {"name": "with space!"}, note="a name to be cleaned"),
            Step("list_scene_snapshots"),
            Step("delete_scene_snapshot", {"name": "first"}),
            Step("delete_scene_snapshot", {"name": "nope"}, note="a snapshot that does not exist"),
            Step("list_scene_snapshots"),
        ),
    ),
    Scenario(
        "editing/grid_layout",
        "compute_grid_layout only computes positions; it places nothing.",
        (
            Step("compute_grid_layout", {"count": 6, "spacing": Meters(2.0)}),
            Step("compute_grid_layout", {"count": 1}),
            Step("compute_grid_layout", {"count": 0}, note="zero items"),
        ),
    ),
    Scenario(
        "editing/listings",
        "list_scene and list_prim_children on a scene with groups, parts and nested assets.",
        (
            Step("list_scene", note="an empty scene"),
            _place("table.usda", "Table", save="table"),
            Step("place_asset_inside",
                 {"asset_file_path": "$lib/crate.usda", "asset_name": "Crate",
                  "container_prim_path": "$table", "group": "Props", **at(0.0)}),
            _place("lamp/lamp.usda", "Lamp", "Props", 2.0),
            Step("list_scene"),
            Step("list_prim_children", {"prim_path": "/Scene"}),
            Step("list_prim_children", {"prim_path": "$table"}),
            Step("list_prim_children", {"prim_path": "$table/asset"}),
            Step("list_prim_children", {"prim_path": "/Scene/Nope"}),
        ),
    ),
)
