# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""World space: scatter paths put every piece where the path is.

A clean USD file can still hold a piece in the wrong place, so these tests
measure the composed result (world bounds and headings) in Y-up and Z-up
scenes, in meters and in centimeters. The library boxes are centered on
their origin, so a piece's bounds center is its position.
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
