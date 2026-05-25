# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the core stage primitives + validation + grid layout."""

import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom

from bowerbot.utils import stage_utils, validation_utils
from bowerbot.utils.geometry_utils import suggest_grid_layout


def test_create_empty_stage():
    """stage_utils.create_stage produces a stage with BowerBot defaults."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_utils.create_stage(stage_path)
        stage_utils.save_stage(stage)

        assert stage_path.exists()

        reopened = Usd.Stage.Open(str(stage_path))
        assert reopened is not None
        assert UsdGeom.GetStageMetersPerUnit(reopened) == 1.0
        assert UsdGeom.GetStageUpAxis(reopened) == UsdGeom.Tokens.y

        default_prim = reopened.GetDefaultPrim()
        assert default_prim.IsValid()
        assert str(default_prim.GetPath()) == "/Scene"
        assert len(default_prim.GetChildren()) == 0


def test_validate_empty_stage():
    """validation_utils.validate_stage approves a correctly built empty stage."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"
        stage = stage_utils.create_stage(stage_path)
        stage_utils.save_stage(stage)

        result = validation_utils.validate_stage(stage_path)
        assert result.is_valid, [i.message for i in result.issues]
        assert result.error_count == 0


def test_grid_layout():
    """geometry_utils.suggest_grid_layout returns N (x, y, z) tuples."""
    placements = suggest_grid_layout(
        4, spacing=2.0, room_bounds=(10.0, 3.0, 8.0),
    )

    assert len(placements) == 4
    for p in placements:
        assert p[1] == 0.0

    for i, a in enumerate(placements):
        for j, b in enumerate(placements):
            if i >= j:
                continue
            dx = a[0] - b[0]
            dz = a[2] - b[2]
            dist = (dx**2 + dz**2) ** 0.5
            assert dist >= 1.9, f"Objects {i} and {j} too close: {dist:.2f}m"


def test_list_prims_includes_scene_authored_cubes():
    """A raw Cube defined directly in scene.usda must appear in list_prims."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"
        stage = stage_utils.create_stage(stage_path)
        UsdGeom.Cube.Define(stage, "/Scene/Cube_Anchor")
        UsdGeom.Cube.Define(stage, "/Scene/Cube_Bob")
        stage_utils.save_stage(stage)

        reopened = Usd.Stage.Open(str(stage_path))
        prims = stage_utils.list_prims(reopened)
        paths = {p["prim_path"] for p in prims}
        assert "/Scene/Cube_Anchor" in paths
        assert "/Scene/Cube_Bob" in paths
        for entry in prims:
            assert entry["type"] == "Cube"


def test_list_prims_includes_scene_authored_mesh():
    """A raw Mesh defined directly in scene.usda must appear in list_prims."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"
        stage = stage_utils.create_stage(stage_path)
        UsdGeom.Mesh.Define(stage, "/Scene/Plane")
        stage_utils.save_stage(stage)

        reopened = Usd.Stage.Open(str(stage_path))
        prims = stage_utils.list_prims(reopened)
        paths = {p["prim_path"] for p in prims}
        assert "/Scene/Plane" in paths


def test_list_prim_attributes_handles_cube_extent():
    """list_prim_attributes must not crash on a Cube's Vec3f[] extent attribute."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"
        stage = stage_utils.create_stage(stage_path)
        UsdGeom.Cube.Define(stage, "/Scene/Cube")
        stage_utils.save_stage(stage)

        attrs = stage_utils.list_prim_attributes(stage, "/Scene/Cube")
        extent = next(a for a in attrs if a["name"] == "extent")
        assert extent["value"] == [
            [-1.0, -1.0, -1.0], [1.0, 1.0, 1.0],
        ]


def test_list_prim_attributes_handles_mesh_points():
    """A Mesh's point3f[] points attribute must serialize as nested floats."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"
        stage = stage_utils.create_stage(stage_path)
        mesh = UsdGeom.Mesh.Define(stage, "/Scene/Plane")
        from pxr import Gf, Vt
        mesh.CreatePointsAttr(Vt.Vec3fArray([
            Gf.Vec3f(-0.5, 0, -0.5),
            Gf.Vec3f(0.5, 0, -0.5),
            Gf.Vec3f(0.5, 0, 0.5),
            Gf.Vec3f(-0.5, 0, 0.5),
        ]))
        stage_utils.save_stage(stage)

        attrs = stage_utils.list_prim_attributes(stage, "/Scene/Plane")
        points = next(a for a in attrs if a["name"] == "points")
        assert len(points["value"]) == 4
        assert points["value"][0] == [-0.5, 0.0, -0.5]


def test_list_prim_attributes_handles_int_array():
    """A Mesh's int[] faceVertexCounts must serialize as a flat int list."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"
        stage = stage_utils.create_stage(stage_path)
        mesh = UsdGeom.Mesh.Define(stage, "/Scene/Plane")
        from pxr import Vt
        mesh.CreateFaceVertexCountsAttr(Vt.IntArray([4]))
        mesh.CreateFaceVertexIndicesAttr(Vt.IntArray([0, 1, 2, 3]))
        stage_utils.save_stage(stage)

        attrs = stage_utils.list_prim_attributes(stage, "/Scene/Plane")
        counts = next(a for a in attrs if a["name"] == "faceVertexCounts")
        assert counts["value"] == [4.0]
        indices = next(a for a in attrs if a["name"] == "faceVertexIndices")
        assert indices["value"] == [0.0, 1.0, 2.0, 3.0]
