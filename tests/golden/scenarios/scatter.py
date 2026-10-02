# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter: on surfaces (random, rows, pile; instancer or placements), along paths, and
drop_to_surface."""

from __future__ import annotations

from tests.golden import model


def _ground() -> model.Step:
    return model.Step(
        "place_asset",
        {
            "asset_file_path": "$lib/ground.usda",
            "asset_name": "Ground",
            "group": "Architecture",
            **model.at(0.0),
        },
        save="ground",
        note="a 10 x 10 m ground to scatter on",
    )


CRATES = [{"asset": "$lib/crate.usda"}]
MIXED = [{"asset": "$lib/crate.usda", "weight": 3}, {"asset": "$lib/chair.usda", "weight": 1}]


SCENARIOS = (
    model.Scenario(
        "scatter/what_a_scatter_holds_changes",
        "The model inside a scatter changes after it was scattered: its stored box must follow.",
        (
            _ground(),
            model.Step(
                "scatter_on_surface",
                {"name": "Crates", "assets": CRATES, "surfaces": ["$ground"], "count": 5,
                 "seed": 1},
                save="crates",
                note="5 crates at random",
            ),
            model.Step(
                "add_scene_model_selection_variant",
                {
                    "prim_path": "$crates/Prototypes/crate",
                    "variant_set": "model",
                    "variant_name": "table",
                    "asset_file_path": "$lib/table.usda",
                },
                note="the scattered model can also be a table (taller and wider)",
            ),
            model.Step(
                "select_scene_variant",
                {"prim_path": "$crates/Prototypes/crate", "variant_set": "model",
                 "variant_name": "table"},
                note="switch every instance to the table",
            ),
            model.Step(
                "scatter_on_surface",
                {"name": "Chairs", "assets": [{"asset": "$lib/chair.usda"}],
                 "surfaces": ["$ground"], "count": 4, "seed": 3},
                save="chairs",
                note="4 chairs at random",
            ),
            model.Step(
                "add_asset_to_asset",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "Crate",
                    "parent_prim_path": "$chairs/Prototypes/chair",
                    "group": "Props",
                    **model.at(0.0, 1.0, 0.0),
                },
                note="the chair asset itself gets a crate on top: every instance is taller",
            ),
            model.Step(
                "set_prim_attribute",
                {"prim_path": "$chairs/Prototypes/chair", "attribute_name": "xformOp:scale",
                 "value": [2, 2, 2]},
                note="the scattered model is made twice as big",
            ),
            model.Step("validate_scene"),
        ),
    ),
    model.Scenario(
        "scatter/random_instancer",
        "Crates scattered at random on the ground as one point instancer, then replaced.",
        (
            _ground(),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Crates",
                    "assets": CRATES,
                    "surfaces": ["$ground"],
                    "count": 5,
                    "seed": 1,
                },
                save="crates",
                note="5 crates at random (seed 1)",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Crates",
                    "assets": CRATES,
                    "surfaces": ["$ground"],
                    "count": 3,
                    "seed": 2,
                },
                note="the same name again without replace",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Crates",
                    "assets": MIXED,
                    "surfaces": ["$ground"],
                    "count": 4,
                    "seed": 2,
                    "replace": True,
                },
                note="replace it with a mix of crates and chairs",
            ),
            model.Step("list_scene"),
            model.Step("remove_prim", {"prim_path": "$crates"}, note="remove the whole scatter"),
        ),
    ),
    model.Scenario(
        "scatter/placements_rows_pile",
        "Scatter as separate placements, in rows, and as a pile.",
        (
            _ground(),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Loose",
                    "assets": CRATES,
                    "surfaces": ["$ground"],
                    "count": 3,
                    "seed": 3,
                    "output": "placements",
                },
                note="three separate crate placements",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Rows",
                    "assets": CRATES,
                    "surfaces": ["$ground"],
                    "arrangement": "rows",
                    "spacing": model.Meters(1.5),
                    "row_spacing": model.Meters(2.0),
                    "region": {
                        "polygon": [
                            model.Point(-2.0, 0.0, -2.0),
                            model.Point(2.0, 0.0, -2.0),
                            model.Point(2.0, 0.0, 2.0),
                            model.Point(-2.0, 0.0, 2.0),
                        ]
                    },
                    "seed": 4,
                },
                note="rows inside a 4 x 4 m square region",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Pile",
                    "assets": CRATES,
                    "surfaces": ["$ground"],
                    "arrangement": "pile",
                    "count": 4,
                    "seed": 5,
                    "region": {"center": model.Point(3.0, 0.0, 3.0), "radius": model.Meters(1.0)},
                },
                note="a pile of four in a 1 m circle",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Check",
                    "assets": CRATES,
                    "surfaces": ["$ground"],
                    "count": 50,
                    "seed": 6,
                    "validate_only": True,
                },
                note="validate a scatter without making it",
            ),
            model.Step("list_scene"),
        ),
    ),
    model.Scenario(
        "scatter/along_path",
        "Posts along a line, both sides of it, and around a closed loop.",
        (
            _ground(),
            model.Step(
                "scatter_along_path",
                {
                    "name": "Fence",
                    "assets": CRATES,
                    "points": [model.Point(-4.0, 0.0, 0.0), model.Point(4.0, 0.0, 0.0)],
                    "spacing": model.Meters(2.0),
                },
                note="a crate every 2 m along a line",
            ),
            model.Step(
                "scatter_along_path",
                {
                    "name": "Avenue",
                    "assets": CRATES,
                    "points": [model.Point(-4.0, 0.0, 2.0), model.Point(4.0, 0.0, 2.0)],
                    "count": 3,
                    "sides": "both",
                    "offset": model.Meters(1.0),
                    "facing": "path",
                },
                note="three stations with a crate on each side",
            ),
            model.Step(
                "scatter_along_path",
                {
                    "name": "Ring",
                    "assets": CRATES,
                    "points": [
                        model.Point(-1.0, 0.0, -1.0),
                        model.Point(1.0, 0.0, -1.0),
                        model.Point(1.0, 0.0, 1.0),
                        model.Point(-1.0, 0.0, 1.0),
                    ],
                    "closed": True,
                    "count": 4,
                    "surfaces": ["$ground"],
                },
                note="four crates around a closed square, snapped to the ground",
            ),
            model.Step("list_scene"),
        ),
    ),
    model.Scenario(
        "scatter/drop_to_surface",
        "Placements floating above the ground dropped onto it.",
        (
            _ground(),
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/crate.usda",
                    "asset_name": "Crate",
                    "group": "Props",
                    **model.at(1.0, 2.0, 0.0),
                },
                save="crate",
                note="a crate 2 m above the ground",
            ),
            model.Step(
                "place_asset",
                {
                    "asset_file_path": "$lib/chair.usda",
                    "asset_name": "Chair",
                    "group": "Furniture",
                    **model.at(-1.0, 3.0, 0.0),
                },
                save="chair",
                note="a chair 3 m above the ground",
            ),
            model.Step(
                "drop_to_surface",
                {"prim_paths": ["$crate", "$chair"], "surfaces": ["$ground"]},
                note="drop both onto the ground",
            ),
            model.Step(
                "drop_to_surface",
                {"prim_paths": ["$crate"]},
                note="drop again, with no surface named",
            ),
            model.Step("drop_to_surface", {"prim_paths": ["/Scene/Nope"]}),
        ),
    ),
    model.Scenario(
        "scatter/refusals",
        "Scatter calls that cannot work.",
        (
            _ground(),
            model.Step(
                "scatter_on_surface",
                {"name": "Bad", "assets": CRATES, "surfaces": ["/Scene/Nope"], "count": 3},
                note="a surface that does not exist",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Bad",
                    "assets": [{"asset": "$lib/nope.usda"}],
                    "surfaces": ["$ground"],
                    "count": 3,
                },
                note="an asset that does not exist",
            ),
            model.Step(
                "scatter_on_surface",
                {"name": "Bad", "assets": CRATES, "surfaces": ["$ground"], "count": 0},
                note="zero pieces",
            ),
            model.Step(
                "scatter_along_path",
                {
                    "name": "Bad",
                    "assets": CRATES,
                    "points": [model.Point(0.0, 0.0, 0.0)],
                    "count": 3,
                },
                note="a path with a single point",
            ),
            model.Step(
                "scatter_on_surface",
                {
                    "name": "Bad",
                    "assets": CRATES,
                    "surfaces": ["$ground"],
                    "count": 3,
                    "density": 1.0,
                },
                note="count and density together",
            ),
        ),
    ),
)
