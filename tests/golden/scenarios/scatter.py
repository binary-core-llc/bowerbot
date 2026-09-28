# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter: on surfaces (random, rows, pile; instancer or placements), along paths, and
drop_to_surface."""

from __future__ import annotations

from tests.golden.model import Meters, Point, Scenario, Step, at


def _ground() -> Step:
    return Step(
        "place_asset",
        {"asset_file_path": "$lib/ground.usda", "asset_name": "Ground",
         "group": "Architecture", **at(0.0)},
        save="ground", note="a 10 x 10 m ground to scatter on",
    )


CRATES = [{"asset": "$lib/crate.usda"}]
MIXED = [{"asset": "$lib/crate.usda", "weight": 3}, {"asset": "$lib/chair.usda", "weight": 1}]


SCENARIOS = (
    Scenario(
        "scatter/random_instancer",
        "Crates scattered at random on the ground as one point instancer, then replaced.",
        (
            _ground(),
            Step("scatter_on_surface",
                 {"name": "Crates", "assets": CRATES, "surfaces": ["$ground"], "count": 5,
                  "seed": 1},
                 save="crates", note="5 crates at random (seed 1)"),
            Step("scatter_on_surface",
                 {"name": "Crates", "assets": CRATES, "surfaces": ["$ground"], "count": 3,
                  "seed": 2},
                 note="the same name again without replace"),
            Step("scatter_on_surface",
                 {"name": "Crates", "assets": MIXED, "surfaces": ["$ground"], "count": 4,
                  "seed": 2, "replace": True},
                 note="replace it with a mix of crates and chairs"),
            Step("list_scene"),
            Step("remove_prim", {"prim_path": "$crates"}, note="remove the whole scatter"),
        ),
    ),
    Scenario(
        "scatter/placements_rows_pile",
        "Scatter as separate placements, in rows, and as a pile.",
        (
            _ground(),
            Step("scatter_on_surface",
                 {"name": "Loose", "assets": CRATES, "surfaces": ["$ground"], "count": 3,
                  "seed": 3, "output": "placements"},
                 note="three separate crate placements"),
            Step("scatter_on_surface",
                 {"name": "Rows", "assets": CRATES, "surfaces": ["$ground"],
                  "arrangement": "rows", "spacing": Meters(1.5), "row_spacing": Meters(2.0),
                  "region": {"polygon": [Point(-2.0, 0.0, -2.0), Point(2.0, 0.0, -2.0),
                                         Point(2.0, 0.0, 2.0), Point(-2.0, 0.0, 2.0)]},
                  "seed": 4},
                 note="rows inside a 4 x 4 m square region"),
            Step("scatter_on_surface",
                 {"name": "Pile", "assets": CRATES, "surfaces": ["$ground"],
                  "arrangement": "pile", "count": 4, "seed": 5,
                  "region": {"center": Point(3.0, 0.0, 3.0), "radius": Meters(1.0)}},
                 note="a pile of four in a 1 m circle"),
            Step("scatter_on_surface",
                 {"name": "Check", "assets": CRATES, "surfaces": ["$ground"], "count": 50,
                  "seed": 6, "validate_only": True},
                 note="validate a scatter without making it"),
            Step("list_scene"),
        ),
    ),
    Scenario(
        "scatter/along_path",
        "Posts along a line, both sides of it, and around a closed loop.",
        (
            _ground(),
            Step("scatter_along_path",
                 {"name": "Fence", "assets": CRATES,
                  "points": [Point(-4.0, 0.0, 0.0), Point(4.0, 0.0, 0.0)],
                  "spacing": Meters(2.0)},
                 note="a crate every 2 m along a line"),
            Step("scatter_along_path",
                 {"name": "Avenue", "assets": CRATES,
                  "points": [Point(-4.0, 0.0, 2.0), Point(4.0, 0.0, 2.0)],
                  "count": 3, "sides": "both", "offset": Meters(1.0), "facing": "path"},
                 note="three stations with a crate on each side"),
            Step("scatter_along_path",
                 {"name": "Ring", "assets": CRATES,
                  "points": [Point(-1.0, 0.0, -1.0), Point(1.0, 0.0, -1.0),
                             Point(1.0, 0.0, 1.0), Point(-1.0, 0.0, 1.0)],
                  "closed": True, "count": 4, "surfaces": ["$ground"]},
                 note="four crates around a closed square, snapped to the ground"),
            Step("list_scene"),
        ),
    ),
    Scenario(
        "scatter/drop_to_surface",
        "Placements floating above the ground dropped onto it.",
        (
            _ground(),
            Step("place_asset",
                 {"asset_file_path": "$lib/crate.usda", "asset_name": "Crate", "group": "Props",
                  **at(1.0, 2.0, 0.0)},
                 save="crate", note="a crate 2 m above the ground"),
            Step("place_asset",
                 {"asset_file_path": "$lib/chair.usda", "asset_name": "Chair",
                  "group": "Furniture", **at(-1.0, 3.0, 0.0)},
                 save="chair", note="a chair 3 m above the ground"),
            Step("drop_to_surface", {"prim_paths": ["$crate", "$chair"], "surfaces": ["$ground"]},
                 note="drop both onto the ground"),
            Step("drop_to_surface", {"prim_paths": ["$crate"]},
                 note="drop again, with no surface named"),
            Step("drop_to_surface", {"prim_paths": ["/Scene/Nope"]}),
        ),
    ),
    Scenario(
        "scatter/refusals",
        "Scatter calls that cannot work.",
        (
            _ground(),
            Step("scatter_on_surface",
                 {"name": "Bad", "assets": CRATES, "surfaces": ["/Scene/Nope"], "count": 3},
                 note="a surface that does not exist"),
            Step("scatter_on_surface",
                 {"name": "Bad", "assets": [{"asset": "$lib/nope.usda"}],
                  "surfaces": ["$ground"], "count": 3},
                 note="an asset that does not exist"),
            Step("scatter_on_surface",
                 {"name": "Bad", "assets": CRATES, "surfaces": ["$ground"], "count": 0},
                 note="zero pieces"),
            Step("scatter_along_path",
                 {"name": "Bad", "assets": CRATES, "points": [Point(0.0, 0.0, 0.0)],
                  "count": 3},
                 note="a path with a single point"),
            Step("scatter_on_surface",
                 {"name": "Bad", "assets": CRATES, "surfaces": ["$ground"], "count": 3,
                  "density": 1.0},
                 note="count and density together"),
        ),
    ),
)
