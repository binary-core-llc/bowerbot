# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""World space: every tool that places, moves or converts geometry puts it where it says.

A clean USD file can still hold a part in the wrong place, so these tests
measure the composed result (world bounds, world positions, headings and
aiming directions) in Y-up and Z-up scenes, in meters and in centimeters.
The library boxes are centered on their origin, so a placement's bounds
center is its position.
"""

from __future__ import annotations

import asyncio
import math
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pxr import Gf, Sdf, Usd, UsdGeom

from bowerbot.state import SceneState
from tests._helpers import exec_tool, library_state

CONVENTIONS = [("Y", 1.0), ("Z", 0.01), ("Y", 0.01), ("Z", 1.0)]
# Library box sizes in meters: (width along X, height, depth).
SIZES = {"table": (1.2, 0.1, 0.8), "post": (0.2, 1.0, 0.2), "chair_cm": (0.5, 0.5, 0.5),
         "chair": (0.5, 0.5, 0.5), "crate": (0.3, 0.3, 0.3), "stone": (0.2, 0.2, 0.2),
         "ground": (10.0, 0.1, 10.0)}
TOL = 1e-4


class _Scene:
    """A project in one convention, with helpers speaking plan / up coordinates."""

    def __init__(self, state: SceneState, up: str, mpu: float) -> None:
        self.state, self.up, self.mpu = state, up, mpu
        self.up_i = 1 if up == "Y" else 2
        self.depth_i = 2 if up == "Y" else 1

    def call(self, tool: str, **params: Any) -> dict[str, Any]:
        result = asyncio.run(exec_tool(self.state, tool, params))
        assert result.success, f"{tool}({params}): {result.error}"
        return result.data or {}

    def u(self, meters: float) -> float:
        """Meters in scene units."""
        return meters / self.mpu

    def at(self, x: float, depth: float, height: float) -> dict[str, float]:
        """translate_x/y/z for a point given as x, depth and height in meters."""
        point = [0.0, 0.0, 0.0]
        point[0], point[self.depth_i], point[self.up_i] = x, depth, height
        return {f"translate_{a}": self.u(v) for a, v in zip("xyz", point, strict=True)}

    def vec(self, x: float, depth: float, height: float) -> Gf.Vec3d:
        point = [0.0, 0.0, 0.0]
        point[0], point[self.depth_i], point[self.up_i] = x, depth, height
        return Gf.Vec3d(*(self.u(v) for v in point))

    def turn(self, degrees: float) -> dict[str, float]:
        return {f"rotate_{self.up.lower()}": degrees}

    def size(self, asset: str, *, turned: bool = False) -> Gf.Vec3d:
        """An asset's expected world size in scene units, optionally turned 90° on the floor."""
        width, height, depth = SIZES[asset]
        if turned:
            width, depth = depth, width
        return self.vec(width, depth, height)

    def stage(self) -> Usd.Stage:
        return self.state.require_stage()

    def bounds(self, path: str) -> Gf.Range3d:
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"],
                                  useExtentsHint=False)
        return cache.ComputeWorldBound(self.stage().GetPrimAtPath(path)).ComputeAlignedRange()

    def world(self, path: str) -> Gf.Matrix4d:
        return UsdGeom.Xformable(self.stage().GetPrimAtPath(path)).ComputeLocalToWorldTransform(
            Usd.TimeCode.Default(),
        )


@contextmanager
def _scene(up: str, mpu: float) -> Iterator[_Scene]:
    with tempfile.TemporaryDirectory() as tmp:
        yield _Scene(library_state(Path(tmp), up=up, mpu=mpu), up, mpu)


def _close(a: Gf.Vec3d, b: Gf.Vec3d, scene: _Scene) -> bool:
    return all(abs(a[i] - b[i]) <= scene.u(TOL) for i in range(3))


def _assert_box(scene: _Scene, path: str, center: Gf.Vec3d, size: Gf.Vec3d) -> None:
    box = scene.bounds(path)
    assert _close(box.GetMidpoint(), center, scene), (path, box.GetMidpoint(), center)
    assert _close(box.GetSize(), size, scene), (path, box.GetSize(), size)


# ── placing and moving ──


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_placed_assets_land_at_their_position_in_scene_units_and_axes(up, mpu):
    """A meter Y-up box, a Z-up post and a centimeter chair, straight and turned on the floor."""
    with _scene(up, mpu) as scene:
        for i, asset in enumerate(("table", "post", "chair_cm")):
            for turned in (False, True):
                where = (2.0 * i, 3.0 if turned else 0.0, 0.5)
                path = scene.call("place_asset", asset=asset, asset_name=asset.title(),
                                  group="Props", **scene.at(*where),
                                  **scene.turn(90.0 if turned else 0.0))["prim_path"]
                _assert_box(scene, path, scene.vec(*where), scene.size(asset, turned=turned))


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_moving_and_renaming_keep_the_geometry_where_they_say(up, mpu):
    with _scene(up, mpu) as scene:
        path = scene.call("place_asset", asset="table", asset_name="Table", group="Furniture",
                          **scene.at(0, 0, 0))["prim_path"]
        scene.call("move_asset", prim_path=path, **scene.at(1.5, -2.0, 0.25), **scene.turn(90))
        _assert_box(scene, path, scene.vec(1.5, -2.0, 0.25), scene.size("table", turned=True))

        # One axis only: the others keep their values.
        scene.call("move_asset", prim_path=path, translate_x=scene.u(3.0))
        _assert_box(scene, path, scene.vec(3.0, -2.0, 0.25), scene.size("table", turned=True))

        before = scene.bounds(path)
        moved = scene.call("rename_prim", old_path=path, new_path="/Scene/Dining/Room/Table")
        after = scene.bounds(moved["new_path"])
        assert _close(after.GetMin(), before.GetMin(), scene)
        assert _close(after.GetMax(), before.GetMax(), scene)


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_a_layout_places_every_entry_where_its_pattern_or_transform_says(up, mpu):
    with _scene(up, mpu) as scene:
        origin = scene.vec(4.0, 1.0, 0.5)
        spacing = [scene.u(0.5), scene.u(0.75)]
        scene.call("place_layout", placements=[
            {"asset": "crate", "group": "Grid",
             "pattern": {"type": "grid", "origin": list(origin), "count": [3, 2],
                         "spacing": spacing}},
            {"asset": "table", "group": "Listed",
             "transforms": [{"translate": list(scene.vec(-3, 0, 0.2)),
                             "rotate": [90 if up == "X" else 0, 90 if up == "Y" else 0,
                                        90 if up == "Z" else 0]}]},
        ])
        stage = scene.stage()
        crates = sorted(p.GetName() for p in stage.GetPrimAtPath("/Scene/Grid").GetChildren())
        assert len(crates) == 6
        centers = sorted(
            tuple(round(v, 4) for v in scene.bounds(f"/Scene/Grid/{name}").GetMidpoint())
            for name in crates
        )
        expected = sorted(
            tuple(round(v, 4) for v in origin + Gf.Vec3d(i * spacing[0], j * spacing[1], 0))
            for i in range(3) for j in range(2)
        )
        assert centers == expected
        table = stage.GetPrimAtPath("/Scene/Listed").GetChildren()[0].GetPath()
        _assert_box(scene, str(table), scene.vec(-3, 0, 0.2), scene.size("table", turned=True))


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_a_tilt_about_a_literal_scene_axis(up, mpu):
    """rotate_x turns about the scene's X axis in both conventions: height and Y/Z size swap."""
    with _scene(up, mpu) as scene:
        path = scene.call("place_asset", asset="table", asset_name="Table", group="Props",
                          **scene.at(0, 0, 1.0), rotate_x=90.0)["prim_path"]
        size = scene.size("table")
        _assert_box(scene, path, scene.vec(0, 0, 1.0), Gf.Vec3d(size[0], size[2], size[1]))


# ── nesting ──


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_a_nested_placement_lands_where_asked_in_a_turned_container(up, mpu):
    """absolute takes world coordinates; bounds_offset offsets from the container's top."""
    with _scene(up, mpu) as scene:
        table = scene.call("place_asset", asset="table", asset_name="Table", group="Furniture",
                           **scene.at(2.0, 1.0, 0.5), **scene.turn(90))["prim_path"]
        crate = scene.call("place_asset_inside", asset="crate", asset_name="Crate",
                           container_prim_path=table, group="Props",
                           **scene.at(2.1, 1.2, 0.7))["prim_path"]
        _assert_box(scene, crate, scene.vec(2.1, 1.2, 0.7), scene.size("crate"))

        # 0.15 m above the top, 0.2 m along X of the unrotated table: the offset turns with it.
        stone = scene.call("place_asset_inside", asset="stone", asset_name="Stone",
                           container_prim_path=table, group="Props",
                           position_mode="bounds_offset",
                           translate_x=0.2, **{f"translate_{up.lower()}": 0.15,
                                               f"translate_{'z' if up == 'Y' else 'y'}": 0.0})
        top = 0.5 + 0.05
        # Unrotated +X turned 90° about up: Y-up turns +X to -Z; Z-up turns +X to +Y.
        depth_shift = -0.2 if up == "Y" else 0.2
        _assert_box(scene, stone["prim_path"], scene.vec(2.0, 1.0 + depth_shift, top + 0.15),
                    scene.size("stone"))


# ── resting on surfaces ──


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_dropped_objects_rest_on_the_surface_below_them(up, mpu):
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        floating = scene.call("place_asset", asset="crate", asset_name="Floating", group="Props",
                              **scene.at(1.0, 1.0, 2.0))["prim_path"]
        sunk = scene.call("place_asset", asset="chair", asset_name="Sunk", group="Props",
                          **scene.at(-1.0, 2.0, 0.0))["prim_path"]
        scene.call("drop_to_surface", prim_paths=[floating, sunk], surfaces=[ground])
        for path, asset, x, depth in ((floating, "crate", 1.0, 1.0), (sunk, "chair", -1.0, 2.0)):
            _rests_on(scene, path, 0.05)
            box = scene.bounds(path)
            assert _close(box.GetSize(), scene.size(asset), scene)
            plan = box.GetMidpoint()
            assert abs(plan[0] - scene.u(x)) <= scene.u(TOL)
            assert abs(plan[scene.depth_i] - scene.u(depth)) <= scene.u(TOL)


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
@pytest.mark.parametrize("output", ["instancer", "placements"])
def test_scattered_pieces_rest_on_the_surface_inside_it(up, mpu, output):
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(1.0, -1.0, 0.0))["prim_path"]
        scene.call("scatter_on_surface", name="Stones", group="Nature",
                   assets=[{"asset": "stone"}], surfaces=[ground], count=12, seed=3,
                   align="up", output=output)
        boxes = _instance_boxes(scene, "/Scene/Nature/Stones")
        assert len(boxes) == 12
        for box in boxes:
            assert abs(box.GetMin()[scene.up_i] - scene.u(0.05)) <= scene.u(1e-3), box
            # Each piece turns at random about the up axis: its height stays 0.2 m and its
            # plan footprint is that of a 0.2 m square at some heading.
            size = box.GetSize()
            assert abs(size[scene.up_i] - scene.u(0.2)) <= scene.u(TOL), box
            widest = scene.u(0.2 * math.sqrt(2)) + scene.u(TOL)
            for axis in (0, scene.depth_i):
                assert scene.u(0.2) - scene.u(TOL) <= size[axis] <= widest, box
            # The sample point (the piece's center) lies on the ground; a piece near
            # the edge may hang over it.
            for axis, center in ((0, 1.0), (scene.depth_i, -1.0)):
                middle = box.GetMidpoint()[axis]
                assert scene.u(center - 5.0) <= middle <= scene.u(center + 5.0), box


def _ground_plane(scene: _Scene, path: str) -> tuple[Gf.Vec3d, Gf.Vec3d]:
    """A point on the ground box's mid-plane and the plane's unit normal (its up axis)."""
    world = scene.world(path)
    up_axis = Gf.Vec3d(0, 0, 0)
    up_axis[scene.up_i] = 1.0
    return world.ExtractTranslation(), world.TransformDir(up_axis).GetNormalized()


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_pieces_scattered_on_a_slope_lie_flat_on_it(up, mpu):
    """align='surface' on a tilted ground: each piece's up is the slope's normal, its base on it."""
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0), rotate_x=15.0)["prim_path"]
        scene.call("scatter_on_surface", name="Stones", group="Nature",
                   assets=[{"asset": "stone"}], surfaces=[ground], count=8, seed=5,
                   align="surface", output="placements")
        origin, normal = _ground_plane(scene, ground)
        pieces = scene.stage().GetPrimAtPath("/Scene/Nature/Stones").GetChildren()
        assert len(pieces) == 8
        up_axis = Gf.Vec3d(0, 0, 0)
        up_axis[scene.up_i] = 1.0
        for piece in pieces:
            world = scene.world(str(piece.GetPath()))
            piece_up = world.TransformDir(up_axis).GetNormalized()
            assert Gf.Dot(piece_up, normal) > 1 - 1e-6, (piece.GetPath(), piece_up, normal)
            center = scene.bounds(str(piece.GetPath())).GetMidpoint()
            height = Gf.Dot(center - origin, normal)
            assert abs(height - scene.u(0.05 + 0.1)) <= scene.u(1e-3), (piece.GetPath(), height)


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_a_scatter_is_reseated_when_its_ground_moves(up, mpu):
    """drop_to_surface on a whole scatter: every instance rests on the ground's new height."""
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        scene.call("scatter_on_surface", name="Stones", group="Nature",
                   assets=[{"asset": "stone"}], surfaces=[ground], count=10, seed=2, align="up")
        scene.call("move_asset", prim_path=ground, **{f"translate_{up.lower()}": scene.u(0.5)})
        scene.call("drop_to_surface", prim_paths=["/Scene/Nature/Stones"], surfaces=[ground])
        boxes = _instance_boxes(scene, "/Scene/Nature/Stones")
        assert len(boxes) == 10
        for box in boxes:
            assert abs(box.GetMin()[scene.up_i] - scene.u(0.55)) <= scene.u(1e-3), box


def _plan(box: Gf.Range3d, scene: _Scene) -> tuple[float, float, float, float]:
    return (box.GetMin()[0], box.GetMax()[0], box.GetMin()[scene.depth_i],
            box.GetMax()[scene.depth_i])


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_scatter_options_embed_scale_spacing_and_avoid(up, mpu):
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        crate = scene.call("place_asset", asset="crate", asset_name="Crate", group="Props",
                           **scene.at(1.0, 0.5, 0.2))["prim_path"]

        scene.call("scatter_on_surface", name="Buried", group="Nature",
                   assets=[{"asset": "stone"}], surfaces=[ground], count=6, seed=1,
                   align="up", embed=0.5)
        for box in _instance_boxes(scene, "/Scene/Nature/Buried"):
            assert abs(box.GetMin()[scene.up_i] - scene.u(0.05 - 0.1)) <= scene.u(1e-3), box

        scene.call("scatter_on_surface", name="Sized", group="Nature",
                   assets=[{"asset": "stone"}], surfaces=[ground], count=10, seed=1,
                   align="up", scale_range=[0.5, 1.5])
        for box in _instance_boxes(scene, "/Scene/Nature/Sized"):
            height = box.GetSize()[scene.up_i]
            assert scene.u(0.1) - scene.u(TOL) <= height <= scene.u(0.3) + scene.u(TOL), box
            assert abs(box.GetMin()[scene.up_i] - scene.u(0.05)) <= scene.u(1e-3), box

        scene.call("scatter_on_surface", name="Spaced", group="Nature",
                   assets=[{"asset": "stone"}], surfaces=[ground], count=10, seed=1,
                   align="up", min_spacing=scene.u(1.0))
        centers = [box.GetMidpoint() for box in _instance_boxes(scene, "/Scene/Nature/Spaced")]
        for i, a in enumerate(centers):
            for b in centers[i + 1:]:
                gap = math.hypot(a[0] - b[0], a[scene.depth_i] - b[scene.depth_i])
                assert gap >= scene.u(1.0) - scene.u(TOL), (a, b, gap)

        scene.call("scatter_on_surface", name="Around", group="Nature",
                   assets=[{"asset": "stone"}], surfaces=[ground], count=60, seed=1,
                   align="up", avoid=[crate])
        x0, x1, d0, d1 = _plan(scene.bounds(crate), scene)
        for box in _instance_boxes(scene, "/Scene/Nature/Around"):
            px0, px1, pd0, pd1 = _plan(box, scene)
            overlaps = px0 < x1 and px1 > x0 and pd0 < d1 and pd1 > d0
            assert not overlaps, ("a stone lies under the avoided crate", box)


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_rows_and_a_pile_rest_on_the_ground(up, mpu):
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        scene.call("scatter_on_surface", name="Rows", group="Crops",
                   assets=[{"asset": "stone"}], surfaces=[ground], arrangement="rows",
                   spacing=scene.u(1.0), row_spacing=scene.u(2.0), row_direction_degrees=0,
                   align="up", random_yaw=False, seed=1)
        boxes = _instance_boxes(scene, "/Scene/Crops/Rows")
        assert boxes
        depths = sorted({round(box.GetMidpoint()[scene.depth_i] / scene.u(1.0), 3)
                         for box in boxes})
        gaps = [b - a for a, b in zip(depths, depths[1:], strict=False)]
        assert all(abs(gap - 2.0) <= 1e-3 for gap in gaps), depths
        for box in boxes:
            assert abs(box.GetMin()[scene.up_i] - scene.u(0.05)) <= scene.u(1e-3), box

        scene.call("scatter_on_surface", name="Heap", group="Crops",
                   assets=[{"asset": "stone"}], surfaces=[ground], arrangement="pile",
                   count=40, region={"center": list(scene.vec(2.0, 2.0, 0)),
                                     "radius": scene.u(1.0)}, seed=1)
        for box in _instance_boxes(scene, "/Scene/Crops/Heap"):
            assert box.GetMin()[scene.up_i] >= scene.u(0.05) - scene.u(1e-3), (
                "a pile piece sinks into the ground", box)
            reach = math.hypot(box.GetMidpoint()[0] - scene.u(2.0),
                               box.GetMidpoint()[scene.depth_i] - scene.u(2.0))
            assert reach <= scene.u(1.0) + scene.u(0.2), box


# ── swapping and converting the asset in a slot ──


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_a_model_selection_variant_conforms_each_choice_like_a_placement(up, mpu):
    """A meter chair, its centimeter twin and a Z-up post all stand in the slot, true size."""
    with _scene(up, mpu) as scene:
        where = (1.0, -1.0, 0.3)
        slot = scene.call("place_asset", asset="chair", asset_name="Seat", group="Furniture",
                          **scene.at(*where), **scene.turn(90))["prim_path"]
        scene.call("add_scene_model_selection_variant", prim_path=slot, variant_set="model",
                   variant_name="cm", asset="chair_cm")
        scene.call("add_scene_model_selection_variant", prim_path=slot, variant_set="model",
                   variant_name="post", asset="post")
        for variant, asset in (("chair", "chair"), ("cm", "chair_cm"), ("post", "post")):
            scene.call("select_scene_variant", prim_path=slot, variant_set="model",
                       variant_name=variant)
            _assert_box(scene, slot, scene.vec(*where), scene.size(asset, turned=True))


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_every_lod_and_a_frozen_asset_measure_like_the_source(up, mpu):
    """An LOD in other units and a frozen export keep the size and place of the original."""
    with _scene(up, mpu) as scene:
        library = scene.state.library_dir
        stage = Usd.Stage.CreateNew(str(library / "lamp_cm.usda"))
        UsdGeom.SetStageMetersPerUnit(stage, 0.01)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        stage.SetDefaultPrim(stage.DefinePrim("/lamp_cm", "Xform"))
        for part in ("Base", "Shade"):
            cube = UsdGeom.Cube.Define(stage, f"/lamp_cm/{part}")
            cube.AddScaleOp().Set(Gf.Vec3f(20.0, 20.0, 30.0))  # 0.4 x 0.4 x 0.6 m, Z-up
        stage.Save()
        where = (1.0, 1.0, 0.3)
        lamp = scene.call("place_asset", asset="lamp", asset_name="Lamp", group="Props",
                          **scene.at(*where), **scene.turn(90))["prim_path"]
        high = scene.bounds(lamp)
        scene.call("setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
                   variants={"high": "./geo.usda", "cm": "lamp_cm"}, default_variant="high",
                   conform_units=True)
        scene.call("select_asset_variant_for_instance", prim_path=lamp, variant_set="lod",
                   variant_name="cm")
        low = scene.bounds(lamp)
        assert _close(low.GetMin(), high.GetMin(), scene) and _close(low.GetMax(), high.GetMax(),
                                                                     scene)

        unfrozen = Usd.Stage.CreateNew(str(library / "unfrozen.usda"))
        UsdGeom.SetStageMetersPerUnit(unfrozen, 1.0)
        UsdGeom.SetStageUpAxis(unfrozen, UsdGeom.Tokens.y)
        root = UsdGeom.Xform.Define(unfrozen, "/unfrozen")
        unfrozen.SetDefaultPrim(root.GetPrim())
        root.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.5, 0.0))
        root.AddRotateYOp().Set(90.0)
        arm = UsdGeom.Xform.Define(unfrozen, "/unfrozen/arm")
        arm.AddTranslateOp().Set(Gf.Vec3d(1.0, 0.0, 0.0))
        UsdGeom.Cube.Define(unfrozen, "/unfrozen/arm/Box").GetSizeAttr().Set(0.4)
        unfrozen.Save()
        # The source, placed at the origin unturned: in a Y-up scene the box sits at
        # (0, 0.5, -1); turned into a Z-up scene, Y-up depth -1 becomes +1 along Y.
        path = scene.call("place_asset", asset="unfrozen", asset_name="Unfrozen", group="Props",
                          **scene.at(0, 0, 0), fix_root_transforms=True)["prim_path"]
        _assert_box(scene, path, scene.vec(0.0, 1.0 if up == "Z" else -1.0, 0.5),
                    scene.vec(0.4, 0.4, 0.4))


# ── lights and cameras ──


def _position(scene: _Scene, path: str) -> Gf.Vec3d:
    return scene.world(path).ExtractTranslation()


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_lights_land_where_asked(up, mpu):
    """Scene lights, and asset lights in absolute and bounds_offset modes on a turned lamp."""
    with _scene(up, mpu) as scene:
        key = scene.call("create_light", light_type="SphereLight", light_name="Key",
                         **scene.at(1.0, 2.0, 3.0))["prim_path"]
        assert _close(_position(scene, key), scene.vec(1.0, 2.0, 3.0), scene)
        scene.call("update_light", prim_path=key, translate_x=scene.u(-1.0))
        assert _close(_position(scene, key), scene.vec(-1.0, 2.0, 3.0), scene)

        lamp = scene.call("place_asset", asset="lamp", asset_name="Lamp", group="Props",
                          **scene.at(2.0, 1.0, 0.3), **scene.turn(90))["prim_path"]
        bulb = scene.call("create_light", light_type="SphereLight", light_name="Bulb",
                          asset_prim_path=lamp, position_mode="absolute",
                          **scene.at(2.1, 1.1, 1.0))["prim_path"]
        assert _close(_position(scene, bulb), scene.vec(2.1, 1.1, 1.0), scene)
        scene.call("update_light", prim_path=bulb, position_mode="absolute",
                   **scene.at(1.9, 0.9, 1.2))
        assert _close(_position(scene, bulb), scene.vec(1.9, 0.9, 1.2), scene)

        # 0.2 m above the lamp's top, 0.1 m along the unrotated lamp's +X.
        glow = scene.call("create_light", light_type="SphereLight", light_name="Glow",
                          asset_prim_path=lamp, position_mode="bounds_offset",
                          translate_x=0.1, **{f"translate_{up.lower()}": 0.2,
                                              f"translate_{'z' if up == 'Y' else 'y'}": 0.0},
                          )["prim_path"]
        depth_shift = -0.1 if up == "Y" else 0.1
        top = 0.3 + 0.3
        assert _close(_position(scene, glow), scene.vec(2.0, 1.0 + depth_shift, top + 0.2),
                      scene)


def _aims_at(scene: _Scene, path: str, target: Gf.Vec3d) -> None:
    world = scene.world(path)
    position = world.ExtractTranslation()
    forward = world.TransformDir(Gf.Vec3d(0, 0, -1)).GetNormalized()
    wanted = (target - position).GetNormalized()
    assert Gf.Dot(forward, wanted) > 1 - 1e-6, (forward, wanted)
    up_dir = world.TransformDir(Gf.Vec3d(0, 1, 0))
    assert up_dir[scene.up_i] > 0, "the camera is upside down or rolled onto its side"
    side = world.TransformDir(Gf.Vec3d(1, 0, 0))
    assert abs(side[scene.up_i]) <= 1e-6 * side.GetLength(), "the camera is rolled"


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_cameras_aim_at_their_look_at_point_level_and_upright(up, mpu):
    with _scene(up, mpu) as scene:
        target = scene.vec(0.5, -0.5, 0.4)
        cam = scene.call("create_camera", camera_name="Hero", **scene.at(4.0, 3.0, 2.0),
                         look_at=list(target))["prim_path"]
        assert _close(_position(scene, cam), scene.vec(4.0, 3.0, 2.0), scene)
        _aims_at(scene, cam, target)

        other = scene.vec(-2.0, 1.0, 0.0)
        scene.call("update_camera", prim_path=cam, look_at=list(other))
        assert _close(_position(scene, cam), scene.vec(4.0, 3.0, 2.0), scene)
        _aims_at(scene, cam, other)

        scene.call("update_camera", prim_path=cam, **scene.at(-3.0, -3.0, 5.0),
                   look_at=list(target))
        assert _close(_position(scene, cam), scene.vec(-3.0, -3.0, 5.0), scene)
        _aims_at(scene, cam, target)


def _emits(scene: _Scene, path: str) -> Gf.Vec3d:
    """The world direction a light shines along (its local -Z)."""
    return scene.world(path).TransformDir(Gf.Vec3d(0, 0, -1)).GetNormalized()


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_lights_and_cameras_face_where_their_rotation_says(up, mpu):
    """Rotations are about the scene's axes; an asset light's rotation turns with the placement."""
    with _scene(up, mpu) as scene:
        down = scene.vec(0, 0, -1.0).GetNormalized()
        # A rect light pointing down: rotate_x=-90 in Y-up, none in Z-up (lights face local -Z).
        panel = scene.call("create_light", light_type="RectLight", light_name="Panel",
                           **scene.at(0, 0, 3.0),
                           **({"rotate_x": -90.0} if up == "Y" else {}))["prim_path"]
        assert Gf.Dot(_emits(scene, panel), down) > 1 - 1e-6

        lamp = scene.call("place_asset", asset="lamp", asset_name="Lamp", group="Props",
                          **scene.at(0, 0, 0.3), **scene.turn(90))["prim_path"]
        # rotate_y=-90 aims the light at +X as the lamp stands unrotated; the lamp's 90° turn
        # then carries +X to -Z (Y-up) or +Y (Z-up).
        side = scene.call("create_light", light_type="RectLight", light_name="Side",
                          asset_prim_path=lamp, position_mode="absolute",
                          **scene.at(0.3, 0, 0.4), rotate_y=-90.0)["prim_path"]
        expected = Gf.Vec3d(0, 0, -1) if up == "Y" else Gf.Vec3d(0, 1, 0)
        assert Gf.Dot(_emits(scene, side), expected) > 1 - 1e-6, _emits(scene, side)

        # A camera turned 90° about a horizontal scene axis looks level and stays upright.
        cam = scene.call("create_camera", camera_name="Side", **scene.at(0, 0, 1.0),
                         **({"rotate_y": 90.0} if up == "Y" else {"rotate_x": 90.0}))["prim_path"]
        forward = scene.world(cam).TransformDir(Gf.Vec3d(0, 0, -1)).GetNormalized()
        expected = Gf.Vec3d(-1, 0, 0) if up == "Y" else Gf.Vec3d(0, 1, 0)
        assert Gf.Dot(forward, expected) > 1 - 1e-6, forward
        assert scene.world(cam).TransformDir(Gf.Vec3d(0, 1, 0))[scene.up_i] > 1 - 1e-6


# ── scatter paths ──


def _rests_on(scene: _Scene, path: str, surface_top: float) -> None:
    box = scene.bounds(path)
    assert abs(box.GetMin()[scene.up_i] - scene.u(surface_top)) <= scene.u(TOL), (
        path, box.GetMin()[scene.up_i], scene.u(surface_top))


def _instance_boxes(scene: _Scene, path: str) -> list[Gf.Range3d]:
    """World bounds of every piece of a scatter: placements, or PointInstancer instances."""
    prim = scene.stage().GetPrimAtPath(path)
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"],
                              useExtentsHint=False)
    if prim.IsA(UsdGeom.PointInstancer):
        instancer = UsdGeom.PointInstancer(prim)
        count = len(instancer.GetProtoIndicesAttr().Get())
        return [b.ComputeAlignedRange()
                for b in cache.ComputePointInstanceWorldBounds(instancer, list(range(count)))]
    return [cache.ComputeWorldBound(child).ComputeAlignedRange()
            for child in prim.GetChildren()]


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_pieces_along_a_path_sit_on_it_evenly_spaced(up, mpu):
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        start, end = scene.vec(-3.0, 2.0, 0.0), scene.vec(3.0, 2.0, 0.0)
        scene.call("scatter_along_path", name="Posts", group="Street",
                   assets=[{"asset": "crate"}], points=[list(start), list(end)], count=5,
                   surfaces=[ground])
        boxes = _instance_boxes(scene, "/Scene/Street/Posts")
        assert len(boxes) == 5
        xs = sorted(box.GetMidpoint()[0] for box in boxes)
        steps = [b - a for a, b in zip(xs, xs[1:], strict=False)]
        assert all(abs(s - steps[0]) <= scene.u(TOL) for s in steps), steps
        assert scene.u(-3.0) - scene.u(TOL) <= xs[0] and xs[-1] <= scene.u(3.0) + scene.u(TOL)
        for box in boxes:
            assert abs(box.GetMidpoint()[scene.depth_i] - scene.u(2.0)) <= scene.u(TOL)
            assert abs(box.GetMin()[scene.up_i] - scene.u(0.05)) <= scene.u(1e-3), box


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_pieces_around_a_circle_sit_on_it(up, mpu):
    """A circle path is a circle: every piece at exactly its radius, resting on the ground."""
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        center = scene.vec(1.0, -1.0, 0.0)
        scene.call("scatter_along_path", name="Ring", group="Street",
                   assets=[{"asset": "crate"}], circle={"center": list(center),
                                                        "radius": scene.u(4.0)},
                   count=7, surfaces=[ground])
        boxes = _instance_boxes(scene, "/Scene/Street/Ring")
        assert len(boxes) == 7
        for box in boxes:
            mid = box.GetMidpoint()
            radius = math.hypot(mid[0] - center[0], mid[scene.depth_i] - center[scene.depth_i])
            assert abs(radius - scene.u(4.0)) <= scene.u(1e-6), radius
            assert abs(box.GetMin()[scene.up_i] - scene.u(0.05)) <= scene.u(1e-3), box


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_path_sides_and_facing(up, mpu):
    """sides='both' offsets both ways; 'tangent' turns the front (+Z in Y-up, -Y in Z-up)
    along the path."""
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        line = [list(scene.vec(-3.0, 3.0, 0)), list(scene.vec(3.0, 3.0, 0))]
        scene.call("scatter_along_path", name="Fence", group="Street",
                   assets=[{"asset": "crate"}], points=line, count=3, sides="both",
                   offset=scene.u(0.5), surfaces=[ground])
        depths = sorted(round(box.GetMidpoint()[scene.depth_i] / scene.u(1.0), 4)
                        for box in _instance_boxes(scene, "/Scene/Street/Fence"))
        assert depths == [2.5, 2.5, 2.5, 3.5, 3.5, 3.5]


def _arrow(library: Path) -> None:
    """A Y-up meter asset whose front (+Z) carries a nose: 0.2 m body, nose 0.3 m ahead."""
    stage = Usd.Stage.CreateNew(str(library / "arrow.usda"))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, "/arrow").GetPrim())
    UsdGeom.Cube.Define(stage, "/arrow/Body").GetSizeAttr().Set(0.2)
    nose = UsdGeom.Cube.Define(stage, "/arrow/Nose")
    nose.GetSizeAttr().Set(0.1)
    nose.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.3))
    stage.Save()


def _noses(scene: _Scene, path: str) -> list[tuple[Gf.Vec3d, Gf.Vec3d]]:
    """(body center, plan unit direction to the nose) for every arrow of a scatter."""
    out = []
    for piece in scene.stage().GetPrimAtPath(path).GetChildren():
        body = scene.bounds(f"{piece.GetPath()}/asset/Body").GetMidpoint()
        nose = scene.bounds(f"{piece.GetPath()}/asset/Nose").GetMidpoint()
        heading = nose - body
        heading[scene.up_i] = 0.0
        out.append((body, heading.GetNormalized()))
    return out


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_each_facing_mode_turns_the_front_where_it_says(up, mpu):
    """The asset's front (+Z in Y-up, -Y in Z-up once conformed) for every facing mode."""
    with _scene(up, mpu) as scene:
        _arrow(scene.state.library_dir)
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        along = scene.vec(1.0, 0, 0).GetNormalized()
        line = [list(scene.vec(-3.0, 1.0, 0)), list(scene.vec(3.0, 1.0, 0))]

        def scatter(name: str, **how: Any) -> list[tuple[Gf.Vec3d, Gf.Vec3d]]:
            scene.call("scatter_along_path", name=name, group="Street", surfaces=[ground],
                       assets=[{"asset": "arrow"}], count=3, **how)
            return _noses(scene, f"/Scene/Street/{name}")

        for _, heading in scatter("Tangent", points=line, facing="tangent"):
            assert abs(abs(Gf.Dot(heading, along)) - 1.0) <= 1e-6, heading  # long axis on path
        for body, heading in scatter("Path", points=line, facing="path", sides="both",
                                     offset=scene.u(0.5)):
            toward_line = scene.vec(0, 1.0, 0) - scene.vec(0, 0, 0)
            toward_line[0] = 0.0
            toward_line[scene.depth_i] -= body[scene.depth_i]
            assert Gf.Dot(heading, toward_line.GetNormalized()) > 1 - 1e-6, (body, heading)
        center = scene.vec(0.5, -0.5, 0)
        circle = {"center": list(center), "radius": scene.u(2.0)}
        for mode, sign in (("center", 1.0), ("outward", -1.0)):
            for body, heading in scatter(mode.title(), circle=circle, facing=mode):
                inward = center - body
                inward[scene.up_i] = 0.0
                assert Gf.Dot(heading, inward.GetNormalized() * sign) > 1 - 1e-4, (mode, heading)
        for _, heading in scatter("Fixed", points=line, facing="fixed", direction_degrees=90):
            # 90 degrees is +Z in a Y-up scene and +Y in a Z-up scene.
            expected = Gf.Vec3d(0, 0, 1) if up == "Y" else Gf.Vec3d(0, 1, 0)
            assert Gf.Dot(heading, expected) > 1 - 1e-6, heading


def _cubic(basis: str, p: list[Gf.Vec3d], t: float) -> Gf.Vec3d:
    """One cubic segment of USD's bezier, bspline or catmullRom basis at *t*."""
    s = 1.0 - t
    if basis == "bezier":
        w = (s**3, 3 * s * s * t, 3 * s * t * t, t**3)
    elif basis == "bspline":
        w = (s**3 / 6, (3 * t**3 - 6 * t * t + 4) / 6, (-3 * t**3 + 3 * t * t + 3 * t + 1) / 6,
             t**3 / 6)
    else:  # catmullRom
        w = ((-t**3 + 2 * t * t - t) / 2, (3 * t**3 - 5 * t * t + 2) / 2,
             (-3 * t**3 + 4 * t * t + t) / 2, (t**3 - t * t) / 2)
    return sum((p[i] * w[i] for i in range(4)), Gf.Vec3d(0, 0, 0))


def _curve_samples(basis: str, wrap: str, points: list[Gf.Vec3d]) -> list[Gf.Vec3d]:
    """Dense samples of a cubic curve, as USD evaluates it."""
    pts = list(points)
    if wrap == "pinned" and basis != "bezier":
        pts = [2 * pts[0] - pts[1], *pts, 2 * pts[-1] - pts[-2]]
    step = 3 if basis == "bezier" else 1
    if wrap == "periodic":
        segments = [[pts[(i + k) % len(pts)] for k in range(4)]
                    for i in range(0, len(pts), step)]
    else:
        segments = [pts[i:i + 4] for i in range(0, len(pts) - 3, step)]
    return [_cubic(basis, seg, k / 400) for seg in segments for k in range(401)]


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
@pytest.mark.parametrize(("basis", "wrap"), [
    ("bezier", "nonperiodic"), ("bezier", "periodic"),
    ("bspline", "nonperiodic"), ("bspline", "pinned"), ("bspline", "periodic"),
    ("catmullRom", "nonperiodic"), ("catmullRom", "pinned"), ("catmullRom", "periodic"),
])
def test_pieces_follow_a_cubic_curve_not_its_control_points(up, mpu, basis, wrap):
    """A curve_prim path is the curve USD draws: cubic bases don't follow their control polygon."""
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        # A wavy road on the floor, in meters (x, depth).
        if basis == "bezier":
            plan = [(-4, 0), (-4, 3), (0, 3), (0, 0), (0, -3), (4, -3), (4, 0)]
            if wrap == "periodic":  # 3k points: the last segment closes back to the start
                plan = [(-4, 0), (-4, 3), (0, 3), (0, 0), (0, -3), (4, -3)]
        else:
            plan = [(-4, 0), (-2, 3), (0, -1), (2, 3), (4, 0)]
        control = [scene.vec(x, d, 0.05) for x, d in plan]
        curve = UsdGeom.BasisCurves.Define(scene.stage(), "/Scene/Guides/Road")
        curve.CreateTypeAttr(UsdGeom.Tokens.cubic)
        curve.CreateBasisAttr(basis)
        curve.CreateWrapAttr(wrap)
        curve.CreatePointsAttr([Gf.Vec3f(*v) for v in control])
        curve.CreateCurveVertexCountsAttr([len(control)])
        scene.stage().GetRootLayer().Save()

        scene.call("scatter_along_path", name="Posts", group="Street",
                   assets=[{"asset": "stone"}], curve_prim="/Scene/Guides/Road", count=9,
                   surfaces=[ground])
        samples = _curve_samples(basis, wrap, control)
        boxes = _instance_boxes(scene, "/Scene/Street/Posts")
        assert len(boxes) == 9
        plan = np.array([[q[0], q[scene.depth_i]] for q in samples])
        start, run = plan[:-1], np.diff(plan, axis=0)
        for box in boxes:
            mid = box.GetMidpoint()
            point = np.array([mid[0], mid[scene.depth_i]])
            # Distance to the nearest chord of the densely sampled curve, in plan view.
            along = np.clip(np.einsum("ij,ij->i", point - start, run)
                            / np.maximum(np.einsum("ij,ij->i", run, run), 1e-30), 0.0, 1.0)
            off = float(np.min(np.linalg.norm(start + run * along[:, None] - point, axis=1)))
            assert off <= scene.u(1e-4), f"a piece sits {off / scene.u(1.0):.6f} m off the curve"


def _road(scene: _Scene, plan: list[tuple[float, float]], **curve_type: str) -> list[Gf.Vec3d]:
    control = [scene.vec(x, d, 0.05) for x, d in plan]
    curve = UsdGeom.BasisCurves.Define(scene.stage(), "/Scene/Guides/Road")
    for name, value in curve_type.items():
        curve.GetPrim().CreateAttribute(name, Sdf.ValueTypeNames.Token).Set(value)
    curve.CreatePointsAttr([Gf.Vec3f(*v) for v in control])
    curve.CreateCurveVertexCountsAttr([len(control)])
    scene.stage().GetRootLayer().Save()
    return control


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_a_linear_curve_is_followed_through_its_points(up, mpu):
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        control = _road(scene, [(-4, 0), (0, 3), (4, 0)], type="linear")
        scene.call("scatter_along_path", name="Posts", group="Street",
                   assets=[{"asset": "stone"}], curve_prim="/Scene/Guides/Road", count=3,
                   surfaces=[ground])
        mids = sorted((box.GetMidpoint() for box in _instance_boxes(scene, "/Scene/Street/Posts")),
                      key=lambda v: v[0])
        for mid, point in zip(mids, control, strict=True):
            assert abs(mid[0] - point[0]) <= scene.u(TOL)
            assert abs(mid[scene.depth_i] - point[scene.depth_i]) <= scene.u(TOL)


def test_a_cubic_curve_usd_cannot_draw_is_refused():
    """A nonperiodic bezier needs 3k+1 points: 5 points is refused, and nothing is written."""
    with _scene("Y", 1.0) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        _road(scene, [(-4, 0), (-2, 3), (0, -1), (2, 3), (4, 0)], basis="bezier")
        before = scene.state.require_project().scene_path.read_text()
        result = asyncio.run(exec_tool(scene.state, "scatter_along_path", {
            "name": "Posts", "group": "Street", "assets": [{"asset": "stone"}],
            "curve_prim": "/Scene/Guides/Road", "count": 3, "surfaces": [ground],
        }))
        assert not result.success
        assert "3k+1 points" in result.error
        assert scene.state.require_project().scene_path.read_text() == before


# ── lights are not geometry ──


def _lamp_with_lights(scene: _Scene, **where: float) -> str:
    """A lamp (0.4 x 0.6 x 0.4 m) with a bulb above it and a light hanging below it."""
    lamp = scene.call("place_asset", asset="lamp", asset_name="Lamp", group="Props",
                      **where)["prim_path"]
    scene.call("create_light", light_type="SphereLight", light_name="Bulb", asset_prim_path=lamp)
    scene.call("create_light", light_type="SphereLight", light_name="Under", asset_prim_path=lamp,
               position_mode="bounds_offset", translate_x=0.0,
               **{f"translate_{scene.up.lower()}": -0.2,
                  f"translate_{'z' if scene.up == 'Y' else 'y'}": 0.0})
    return lamp


def _reported(scene: _Scene, bounds: dict[str, dict[str, float]]) -> Gf.Range3d:
    return Gf.Range3d(Gf.Vec3d(*(bounds["min"][a] for a in "xyz")),
                      Gf.Vec3d(*(bounds["max"][a] for a in "xyz")))


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_lights_do_not_count_as_an_objects_bounds(up, mpu):
    """list_scene reports the lamp's geometry, and a drop rests the geometry on the ground."""
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, -1.0))["prim_path"]
        lamp = _lamp_with_lights(scene, **scene.at(1.0, 0, 0))
        size = scene.vec(0.4, 0.4, 0.6)
        listed = next(o for o in scene.call("list_scene")["objects"] if o["prim_path"] == lamp)
        assert _close(_reported(scene, listed["bounds"]).GetSize(), size, scene), listed

        scene.call("drop_to_surface", prim_paths=[lamp], surfaces=[ground])
        _rests_on(scene, f"{lamp}/asset/Base", -1.0 + 0.05)


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_lit_assets_scatter_by_their_geometry(up, mpu):
    """Streetlights along a road butt end to end and rest on it, whatever their lights."""
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        _lamp_with_lights(scene, **scene.at(0, 4.0, 1.0))
        line = [list(scene.vec(-2.0, 2.0, 0)), list(scene.vec(2.0, 2.0, 0))]
        scene.call("scatter_along_path", name="Lights", group="Street",
                   assets=[{"asset": "lamp"}], points=line, surfaces=[ground])
        boxes = [scene.bounds(f"{piece.GetPath()}/asset/Base")
                 for piece in scene.stage().GetPrimAtPath("/Scene/Street/Lights").GetChildren()]
        xs = sorted(box.GetMidpoint()[0] for box in boxes)
        assert len(xs) >= 2
        steps = [b - a for a, b in zip(xs, xs[1:], strict=False)]
        assert all(abs(step - scene.u(0.4)) <= scene.u(TOL) for step in steps), steps
        for box in boxes:
            assert abs(box.GetMin()[scene.up_i] - scene.u(0.05)) <= scene.u(1e-3), box


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_default_light_sizes_are_meters_in_any_units(up, mpu):
    """Unset sizes are USD's defaults in meters: a 0.5 m sphere, a 1 x 1 m rect; a size the
    caller gives is kept in scene units (scene light) or meters (asset light)."""
    with _scene(up, mpu) as scene:
        for name, kind in (("Bulb", "SphereLight"), ("Panel", "RectLight"),
                           ("Disk", "DiskLight"), ("Tube", "CylinderLight")):
            scene.call("create_light", light_type=kind, light_name=name)
        scene.call("create_light", light_type="SphereLight", light_name="Given",
                   attributes={"inputs:radius": scene.u(0.05)})
        seat = scene.call("place_asset", asset="chair_cm", asset_name="Seat", group="Props",
                          **scene.at(1.0, 0, 0))["prim_path"]
        inner = scene.call("create_light", light_type="SphereLight", light_name="Inner",
                           asset_prim_path=seat)["prim_path"]
        fixed = scene.call("create_light", light_type="SphereLight", light_name="Fixed",
                           asset_prim_path=seat, attributes={"inputs:radius": 0.1})["prim_path"]

        def meters(path: str, name: str) -> float:
            prim = scene.stage().GetPrimAtPath(path)
            stretch = scene.world(path).TransformDir(Gf.Vec3d(1, 0, 0)).GetLength()
            return prim.GetAttribute(name).Get() * stretch * mpu

        expected = {("Bulb", "inputs:radius"): 0.5, ("Panel", "inputs:width"): 1.0,
                    ("Panel", "inputs:height"): 1.0, ("Disk", "inputs:radius"): 0.5,
                    ("Tube", "inputs:radius"): 0.5, ("Tube", "inputs:length"): 1.0,
                    ("Given", "inputs:radius"): 0.05}
        for (name, attr), size in expected.items():
            assert abs(meters(f"/Scene/Lighting/{name}", attr) - size) <= 1e-6, (name, attr)
        assert abs(meters(inner, "inputs:radius") - 0.5) <= 1e-6
        assert abs(meters(fixed, "inputs:radius") - 0.1) <= 1e-6
        if mpu == 1.0:  # a meter scene gets nothing more than before
            bulb = scene.stage().GetPrimAtPath("/Scene/Lighting/Bulb")
            assert not bulb.GetAttribute("inputs:radius").HasAuthoredValue()


def _instance_geometry_bottoms(scene: _Scene, path: str) -> list[float]:
    """The lowest geometry point (up axis) of each instance of a scatter: gprims only."""
    stage = scene.stage()
    instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(path))
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    time = Usd.TimeCode.Default()
    xforms = instancer.ComputeInstanceTransformsAtTime(time, time)
    world = UsdGeom.Xformable(instancer).ComputeLocalToWorldTransform(time)
    targets = instancer.GetPrototypesRel().GetTargets()
    bottoms = []
    for xform, index in zip(xforms, instancer.GetProtoIndicesAttr().Get(), strict=True):
        prototype = stage.GetPrimAtPath(targets[index])
        to_local = UsdGeom.Xformable(prototype).ComputeLocalToWorldTransform(time).GetInverse()
        low = math.inf
        for part in Usd.PrimRange(prototype):
            if part.IsA(UsdGeom.Gprim):
                box = cache.ComputeWorldBound(part)
                box.Transform(to_local * xform * world)
                low = min(low, box.ComputeAlignedRange().GetMin()[scene.up_i])
        bottoms.append(low)
    return bottoms


@pytest.mark.parametrize(("up", "mpu"), CONVENTIONS)
def test_a_lit_instancer_scatter_rests_by_its_geometry(up, mpu):
    """Lamps with lights, scattered as one PointInstancer, rest on the ground after a drop."""
    with _scene(up, mpu) as scene:
        ground = scene.call("place_asset", asset="ground", asset_name="Ground",
                            group="Architecture", **scene.at(0, 0, 0))["prim_path"]
        _lamp_with_lights(scene, **scene.at(0, 4.5, 1.0))
        scene.call("scatter_on_surface", name="Lamps", group="Street",
                   assets=[{"asset": "lamp"}], surfaces=[ground], count=5, seed=3, align="up")
        for bottom in _instance_geometry_bottoms(scene, "/Scene/Street/Lamps"):
            assert abs(bottom - scene.u(0.05)) <= scene.u(1e-3), bottom
        scene.call("move_asset", prim_path=ground, **{f"translate_{up.lower()}": scene.u(0.5)})
        scene.call("drop_to_surface", prim_paths=["/Scene/Street/Lamps"], surfaces=[ground])
        for bottom in _instance_geometry_bottoms(scene, "/Scene/Street/Lamps"):
            assert abs(bottom - scene.u(0.55)) <= scene.u(1e-3), bottom
