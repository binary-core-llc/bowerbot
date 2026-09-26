# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for scatter: surface scatter, path scatter, drop to surface."""

import asyncio
import math
import re
import tempfile
from pathlib import Path

import numpy as np
from pxr import Gf, Usd, UsdGeom, Vt

from bowerbot.config import UpAxis
from bowerbot.project import Project
from bowerbot.state import SceneState
from bowerbot.utils import surface_utils
from tests._helpers import exec_tool


def _new_asset(path: Path, *, up: str = "Y", mpu: float = 1.0) -> Usd.Stage:
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(stage, up)
    UsdGeom.SetStageMetersPerUnit(stage, mpu)
    root = UsdGeom.Xform.Define(stage, f"/{path.stem}")
    stage.SetDefaultPrim(root.GetPrim())
    return stage


def _box_asset(
    path: Path, size: tuple[float, float, float], *, up: str = "Y", mpu: float = 1.0,
) -> None:
    """A box asset whose base sits at its origin (pivot on the ground)."""
    stage = _new_asset(path, up=up, mpu=mpu)
    cube = UsdGeom.Cube.Define(stage, f"/{path.stem}/geom")
    cube.CreateSizeAttr(1.0)
    lift = [0.0, 0.0, 0.0]
    lift[1 if up == "Y" else 2] = (size[1] if up == "Y" else size[2]) / 2.0
    cube.AddTranslateOp().Set(Gf.Vec3d(*lift))
    cube.AddScaleOp().Set(Gf.Vec3f(*size))
    stage.Save()


def _tree_asset(
    path: Path, *, trunk: float = 0.3, crown: float = 8.0, lean: float = 0.0,
) -> None:
    """A thin trunk under a wide crown shifted *lean* along X; pivot at the trunk base."""
    stage = _new_asset(path)
    parts = (
        ("trunk", (trunk, 3.0, trunk), (0.0, 1.5, 0.0)),
        ("crown", (crown, 3.0, crown), (lean, 4.5, 0.0)),
    )
    for name, size, offset in parts:
        cube = UsdGeom.Cube.Define(stage, f"/{path.stem}/{name}")
        cube.CreateSizeAttr(1.0)
        cube.AddTranslateOp().Set(Gf.Vec3d(*offset))
        cube.AddScaleOp().Set(Gf.Vec3f(*size))
    stage.Save()


def _stone_asset(path: Path, size: tuple[float, float, float]) -> None:
    """An ellipsoid stone of *size*, thinnest along Y, resting on its origin."""
    stage = _new_asset(path)
    sphere = UsdGeom.Sphere.Define(stage, f"/{path.stem}/geom")
    sphere.CreateRadiusAttr(1.0)
    sphere.AddTranslateOp().Set(Gf.Vec3d(0.0, size[1] / 2.0, 0.0))
    sphere.AddScaleOp().Set(Gf.Vec3f(*(s / 2.0 for s in size)))
    stage.Save()


def _instance_shapes(project: Project, prim_path: str) -> list[np.ndarray]:
    """World-space vertices of every instance of a scatter."""
    stage = Usd.Stage.Open(str(project.scene_path))
    instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(prim_path))
    time = Usd.TimeCode.Default()
    matrices = instancer.ComputeInstanceTransformsAtTime(
        time, time, UsdGeom.PointInstancer.ExcludeProtoXform,
    )
    shapes = []
    for target in instancer.GetPrototypesRel().GetTargets():
        tris = surface_utils.collect_triangles(stage, [str(target)], up=1)
        shapes.append(np.concatenate([tris.v0, tris.v1, tris.v2]))
    out = []
    for proto, m in zip(instancer.GetProtoIndicesAttr().Get(), matrices, strict=True):
        mat = np.array(m)
        out.append(shapes[proto] @ mat[:3, :3] + mat[3, :3])
    return out


def _grid_mesh(
    path: Path,
    height,
    *,
    n: int = 31,
    size: float = 20.0,
    up: str = "Y",
    mpu: float = 1.0,
    flip: bool = False,
) -> None:
    """A square height-field mesh centred on the origin."""
    stage = _new_asset(path, up=up, mpu=mpu)
    mesh = UsdGeom.Mesh.Define(stage, f"/{path.stem}/ground")
    a, b = np.meshgrid(
        np.linspace(-size / 2, size / 2, n), np.linspace(-size / 2, size / 2, n),
        indexing="ij",
    )
    h = height(a, b)
    pts = np.stack([a, h, b], -1) if up == "Y" else np.stack([a, b, h], -1)
    faces = []
    for i in range(n - 1):
        for j in range(n - 1):
            q = [i * n + j, i * n + j + 1, (i + 1) * n + j + 1, (i + 1) * n + j]
            if up == "Z":
                q = q[::-1]
            faces += q[::-1] if flip else q
    mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(pts.reshape(-1, 3).astype(np.float32)))
    mesh.CreateFaceVertexCountsAttr([4] * (n - 1) ** 2)
    mesh.CreateFaceVertexIndicesAttr(faces)
    stage.Save()


def _setup(tmp, *, up: UpAxis = UpAxis.Y, mpu: float = 1.0):
    tmp_path = Path(tmp)
    lib = tmp_path / "lib"
    lib.mkdir()
    project = Project.create(tmp_path / "projects", "test", up_axis=up, meters_per_unit=mpu)
    state = SceneState(up_axis=up, meters_per_unit=mpu, library_dir=lib)
    state.project = project
    state.stage_path = project.scene_path
    asyncio.run(exec_tool(state, "create_stage", {"filename": "scene.usda"}))
    return state, project, lib


def _place(state: SceneState, asset: str, name: str, group: str = "Architecture",
           at=(0.0, 0.0, 0.0)) -> str:
    result = asyncio.run(exec_tool(state, "place_asset", {
        "asset_file_path": asset, "asset_name": name, "group": group,
        "translate_x": at[0], "translate_y": at[1], "translate_z": at[2],
    }))
    assert result.success, result.error
    return result.data["prim_path"]


def _instance_matrices(project: Project, prim_path: str) -> list[Gf.Matrix4d]:
    stage = Usd.Stage.Open(str(project.scene_path))
    instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(prim_path))
    assert instancer, f"{prim_path} is not a PointInstancer"
    time = Usd.TimeCode.Default()
    return list(instancer.ComputeInstanceTransformsAtTime(time, time))


def _instance_boxes(project: Project, prim_path: str) -> list[Gf.Range3d]:
    stage = Usd.Stage.Open(str(project.scene_path))
    instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(prim_path))
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    ids = list(range(len(instancer.GetProtoIndicesAttr().Get())))
    return [b.ComputeAlignedRange() for b in cache.ComputePointInstanceWorldBounds(instancer, ids)]


def _ground_heights(project: Project, prim_path: str, points: np.ndarray, up: int) -> np.ndarray:
    stage = Usd.Stage.Open(str(project.scene_path))
    triangles = surface_utils.collect_triangles(stage, [prim_path], up=up)
    index = surface_utils.build_vertical_index(triangles, up)
    _, heights, _ = surface_utils.surface_under(index, points, mode="top")
    return heights


def _bumps(x, z):
    return 0.8 * np.sin(x * 0.5) * np.cos(z * 0.4)


def _ridges(x, z):
    """Tilled ridges: low (0.3 m) but steep (about 31 degrees)."""
    return 0.15 * np.sin(x * 4.0) + 0.0 * z


def _log_end_gaps(project: Project, prim_path: str, ground: str) -> np.ndarray:
    """Height above the ground of each 2.5 x 0.25 m log's four bottom corners (n, 4)."""
    corners = [(dx, 0.0, dz) for dx in (-1.25, 1.25) for dz in (-0.125, 0.125)]
    pts = np.array([
        [list(m.Transform(Gf.Vec3d(*c))) for c in corners]
        for m in _instance_matrices(project, prim_path)
    ]).reshape(-1, 3)
    return (pts[:, 1] - _ground_heights(project, ground, pts, 1)).reshape(-1, 4)


def _pivot_depths(project: Project, prim_path: str, ground: str) -> np.ndarray:
    """Ground height minus pivot height per instance (positive = buried)."""
    pts = np.array([list(m.ExtractTranslation()) for m in _instance_matrices(project, prim_path)])
    return _ground_heights(project, ground, pts, 1) - pts[:, 1]


# ── scatter_on_surface ──


def test_one_piece_moves_through_the_positions_array():
    """Reading positions and writing them back with one entry changed moves only that piece."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _box_asset(lib / "ground.usda", (10.0, 0.1, 10.0))
        _box_asset(lib / "stone.usda", (0.2, 0.2, 0.2))
        ground = _place(state, "ground.usda", "Ground")
        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Stones", "group": "Nature", "assets": [{"asset": "stone.usda"}],
            "surfaces": [ground], "count": 5, "seed": 1,
        }))
        assert result.success, result.error
        stones = "/Scene/Nature/Stones"
        before = [m.ExtractTranslation() for m in _instance_matrices(project, stones)]

        listed = asyncio.run(exec_tool(state, "list_prim_attributes", {"prim_path": stones}))
        positions = next(a["value"] for a in listed.data["attributes"] if a["name"] == "positions")
        positions[2][0] += 3.0
        moved = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": stones, "attribute_name": "positions", "value": positions,
        }))
        assert moved.success, moved.error

        after = [m.ExtractTranslation() for m in _instance_matrices(project, stones)]
        assert abs(after[2][0] - before[2][0] - 3.0) < 1e-4
        assert all((after[i] - before[i]).GetLength() < 1e-6 for i in (0, 1, 3, 4))


def test_pieces_rest_on_uneven_ground_aligned_to_the_surface():
    """Each piece's base sits on the terrain with its up axis along the ground under it."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "terrain.usda", _bumps)
        _box_asset(lib / "stone.usda", (0.2, 0.2, 0.2))
        ground = _place(state, "terrain.usda", "Terrain")

        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Stones", "group": "Nature", "assets": [{"asset": "stone.usda"}],
            "surfaces": [ground], "count": 400, "align": "surface", "seed": 3,
        }))
        assert result.success, result.error
        assert result.data["instances"] == 400

        matrices = _instance_matrices(project, "/Scene/Nature/Stones")
        base = np.array([list(m.Transform(Gf.Vec3d(0, 0, 0))) for m in matrices])
        ups = np.array([list(m.TransformDir(Gf.Vec3d(0, 1, 0)).GetNormalized()) for m in matrices])
        heights = _ground_heights(project, ground, base, up=1)
        # Settled so no corner floats: at most a centimetre into the bumps.
        assert (base[:, 1] - heights).max() < 1e-3
        assert (heights - base[:, 1]).max() < 0.01

        stage = Usd.Stage.Open(str(project.scene_path))
        triangles = surface_utils.collect_triangles(stage, [ground], up=1)
        index = surface_utils.build_vertical_index(triangles, 1)
        _, _, tris = surface_utils.surface_under(index, base, mode="top")
        assert np.einsum("ij,ij->i", ups, triangles.normals[tris]).min() > 0.99


def test_upright_pieces_on_a_slope_never_float():
    """Upright pieces on a slope sink until the downhill edge touches; none float."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "slope.usda", lambda x, z: 0.5 * x)
        _box_asset(lib / "post.usda", (0.3, 1.0, 0.3))
        ground = _place(state, "slope.usda", "Slope")

        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Posts", "assets": [{"asset": "post.usda"}], "surfaces": [ground],
            "count": 60, "align": "up", "seed": 1,
        })).success
        for m in _instance_matrices(project, "/Scene/Scatter/Posts"):
            assert abs(m.TransformDir(Gf.Vec3d(0, 1, 0)).GetNormalized()[1] - 1.0) < 1e-3
            corners = np.array([
                list(m.Transform(Gf.Vec3d(dx, 0, dz)))
                for dx in (-0.15, 0.15) for dz in (-0.15, 0.15)
            ])
            clearance = corners[:, 1] - 0.5 * corners[:, 0]
            assert clearance.max() < 1e-3, "an upright post floats above the slope"
            assert clearance.max() > -0.25


def test_wide_crowned_trees_stand_on_their_trunks_on_ridged_ground():
    """Upright seating follows the trunk's footprint, not the crown's, on both scatter tools."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "field.usda", _ridges, n=81)
        _tree_asset(lib / "tree.usda")
        ground = _place(state, "field.usda", "Field")

        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Orchard", "assets": [{"asset": "tree.usda"}], "surfaces": [ground],
            "count": 40, "align": "up", "seed": 3,
        })).success
        assert asyncio.run(exec_tool(state, "scatter_along_path", {
            "name": "Row", "assets": [{"asset": "tree.usda"}], "surfaces": [ground],
            "points": [[-8, 0, 2], [8, 0, 2]], "spacing": 3.0, "output": "instancer",
        })).success
        for prim_path in ("/Scene/Scatter/Orchard", "/Scene/Scatter/Row"):
            depth = _pivot_depths(project, prim_path, ground)
            assert depth.min() > -1e-3, f"{prim_path}: a trunk floats above the ground"
            assert depth.max() < 0.2, f"{prim_path}: sunk {depth.max():.2f} m by its crown"


def test_long_branches_lie_along_tilled_ridges():
    """Surface-aligned logs follow the ground under their length, not one ridge face."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "field.usda", _ridges, n=81)
        _box_asset(lib / "log.usda", (2.5, 0.25, 0.25))
        ground = _place(state, "field.usda", "Field")

        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Logs", "assets": [{"asset": "log.usda"}], "surfaces": [ground],
            "count": 60, "align": "surface", "seed": 4,
            "region": {"polygon": [[-8, 0, -8], [8, 0, -8], [8, 0, 8], [-8, 0, 8]]},
        })).success
        gaps = _log_end_gaps(project, "/Scene/Scatter/Logs", ground)
        assert gaps.max() < 1e-3, f"a log end floats {gaps.max():.2f} m"
        assert gaps.min() > -0.35, f"a log end is buried {-gaps.min():.2f} m"


def test_a_lopsided_crown_keeps_its_trunk_on_the_ground():
    """The trunk, not the bounding-box centre, lands on the sampled point, so none hang off."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "field.usda", lambda x, z: 0.0 * x)
        _tree_asset(lib / "tree.usda", lean=3.0)
        ground = _place(state, "field.usda", "Field")

        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Leaning", "assets": [{"asset": "tree.usda"}], "surfaces": [ground],
            "count": 80, "align": "up", "seed": 2,
        })).success
        trunks = np.array([list(m.ExtractTranslation()) for m in
                           _instance_matrices(project, "/Scene/Scatter/Leaning")])
        assert np.abs(trunks[:, [0, 2]]).max() <= 10.0 + 1e-6, "a trunk stands off the ground"


def test_density_is_per_square_meter_and_count_is_exact():
    """density is instances per square meter; count places exactly that many."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "flat.usda", lambda x, z: 0.0 * x, size=10.0)
        _box_asset(lib / "leaf.usda", (0.05, 0.01, 0.05))
        ground = _place(state, "flat.usda", "Flat")

        dense = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Leaves", "assets": [{"asset": "leaf.usda"}], "surfaces": [ground],
            "density": 20,
        }))
        assert dense.success, dense.error
        assert abs(dense.data["instances"] - 2000) < 150

        exact = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Few", "assets": [{"asset": "leaf.usda"}], "surfaces": [ground], "count": 37,
        }))
        assert exact.data["instances"] == 37


def test_same_seed_gives_the_same_scatter_and_replace_regenerates():
    """Same seed reproduces the scatter; replace=true regenerates, a new seed changes it."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "terrain.usda", _bumps)
        _box_asset(lib / "stone.usda", (0.2, 0.2, 0.2))
        ground = _place(state, "terrain.usda", "Terrain")
        params = {
            "name": "Stones", "assets": [{"asset": "stone.usda"}], "surfaces": [ground],
            "density": 3, "variation": 0.8, "scale_range": [0.5, 1.5], "seed": 11,
        }
        assert asyncio.run(exec_tool(state, "scatter_on_surface", params)).success
        first = _instance_matrices(project, "/Scene/Scatter/Stones")

        refused = asyncio.run(exec_tool(state, "scatter_on_surface", params))
        assert not refused.success and "replace=true" in refused.error

        replaced = asyncio.run(exec_tool(
            state, "scatter_on_surface", {**params, "replace": True},
        ))
        assert replaced.success
        assert _instance_matrices(project, "/Scene/Scatter/Stones") == first

        reseeded = asyncio.run(exec_tool(
            state, "scatter_on_surface", {**params, "replace": True, "seed": 12},
        ))
        assert reseeded.success
        assert _instance_matrices(project, "/Scene/Scatter/Stones") != first


def test_min_spacing_keeps_every_pair_apart():
    """Spacing is measured between contact points (the pivot, for surface-aligned pieces)."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "park.usda", _bumps)
        _box_asset(lib / "tree.usda", (0.5, 3.0, 0.5))
        ground = _place(state, "park.usda", "Park")

        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Trees", "assets": [{"asset": "tree.usda"}], "surfaces": [ground],
            "count": 120, "min_spacing": 1.2, "align": "surface",
        }))
        assert result.success, result.error
        pts = np.array([list(m.ExtractTranslation()) for m in
                        _instance_matrices(project, "/Scene/Scatter/Trees")])
        dist = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=-1)
        np.fill_diagonal(dist, np.inf)
        assert dist.min() >= 1.2 - 1e-3


def test_avoid_keeps_the_path_footprint_clear():
    """Nothing lands under an avoided prim's plan footprint or its margin."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "lawn.usda", lambda x, z: 0.0 * x, size=10.0)
        _box_asset(lib / "path.usda", (1.0, 0.05, 10.0))
        _box_asset(lib / "grass.usda", (0.05, 0.2, 0.05))
        lawn = _place(state, "lawn.usda", "Lawn")
        path = _place(state, "path.usda", "Path", at=(1.0, 0.0, 0.0))

        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Grass", "assets": [{"asset": "grass.usda"}], "surfaces": [lawn],
            "density": 30, "avoid": [path], "avoid_margin": 0.25, "align": "up",
        })).success
        x = np.array([m.ExtractTranslation()[0] for m in
                      _instance_matrices(project, "/Scene/Scatter/Grass")])
        assert x.size > 1000
        assert not np.any((x > 0.25) & (x < 1.75)), "grass grew on the path or its margin"


def test_avoid_keeps_a_scattered_crop_block_clear():
    """A scatter in avoid clears every instance's footprint; the margin closes the rows."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "field.usda", lambda x, z: 0.0 * x)
        _box_asset(lib / "corn.usda", (0.2, 1.5, 0.2))
        _box_asset(lib / "pebble.usda", (0.05, 0.05, 0.05))
        field = _place(state, "field.usda", "Field")
        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Block_A", "group": "Crops", "assets": [{"asset": "corn.usda"}],
            "surfaces": [field], "arrangement": "rows", "spacing": 0.3, "row_spacing": 0.8,
            "align": "up",
            "region": {"polygon": [[-9, 0, -9], [-2, 0, -9], [-2, 0, 9], [-9, 0, 9]]},
        })).success
        crop = _instance_boxes(project, "/Scene/Crops/Block_A")
        lo_x, hi_x = min(b.GetMin()[0] for b in crop), max(b.GetMax()[0] for b in crop)
        lo_z, hi_z = min(b.GetMin()[2] for b in crop), max(b.GetMax()[2] for b in crop)

        params = {
            "name": "Pebbles", "assets": [{"asset": "pebble.usda"}], "surfaces": [field],
            "density": 20, "avoid": ["/Scene/Crops/Block_A"], "avoid_margin": 0.35,
            "align": "up",
        }
        estimate = asyncio.run(exec_tool(state, "scatter_on_surface", {
            **params, "validate_only": True,
        }))
        assert estimate.success, estimate.error
        assert estimate.data["estimated_instances"] < 0.8 * 400 * 20

        result = asyncio.run(exec_tool(state, "scatter_on_surface", params))
        assert result.success, result.error
        pts = np.array([list(m.ExtractTranslation()) for m in
                        _instance_matrices(project, "/Scene/Scatter/Pebbles")])
        assert pts.shape[0] > 3000
        inside = (
            (pts[:, 0] > lo_x) & (pts[:, 0] < hi_x) & (pts[:, 2] > lo_z) & (pts[:, 2] < hi_z)
        )
        assert not inside.any(), "pebbles landed inside the crop block"

        as_surface = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "OnCrops", "assets": [{"asset": "pebble.usda"}],
            "surfaces": ["/Scene/Crops/Block_A"], "count": 10,
        }))
        assert not as_surface.success
        assert "scatter can't be a surface" in as_surface.error


def test_min_spacing_fills_a_thin_region_of_a_large_surface():
    """Spaced candidates are drawn inside the region, not thinned out of the whole surface."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        # One quad for the whole field, so the strip is a sliver of each triangle.
        _grid_mesh(lib / "field.usda", lambda x, z: 0.0 * x, n=2, size=100.0)
        _box_asset(lib / "shrub.usda", (1.0, 1.0, 1.0))
        field = _place(state, "field.usda", "Field")

        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Shrubs", "assets": [{"asset": "shrub.usda"}], "surfaces": [field],
            "count": 40, "min_spacing": 1.5, "align": "up",
            "region": {"polygon": [[-50, 0, 46], [50, 0, 46], [50, 0, 48], [-50, 0, 48]]},
        }))
        assert result.success, result.error
        assert not result.data["warnings"], result.data["warnings"]
        z = np.array([m.ExtractTranslation()[2] for m in
                      _instance_matrices(project, "/Scene/Scatter/Shrubs")])
        assert z.size == 40
        assert np.all((z >= 46) & (z <= 48))


def test_variation_makes_some_places_thicker_than_others():
    """variation=1 gives a far patchier density than an even scatter."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "ground.usda", _bumps)
        _box_asset(lib / "stone.usda", (0.1, 0.1, 0.1))
        ground = _place(state, "ground.usda", "Ground")

        def cell_counts(name: str, variation: float) -> np.ndarray:
            assert asyncio.run(exec_tool(state, "scatter_on_surface", {
                "name": name, "assets": [{"asset": "stone.usda"}], "surfaces": [ground],
                "count": 4000, "variation": variation, "variation_scale": 4.0, "seed": 5,
            })).success
            pts = np.array([list(m.ExtractTranslation()) for m in
                            _instance_matrices(project, f"/Scene/Scatter/{name}")])
            counts, _, _ = np.histogram2d(pts[:, 0], pts[:, 2], bins=8, range=[[-10, 10]] * 2)
            return counts

        even = cell_counts("Even", 0.0)
        patchy = cell_counts("Patchy", 1.0)
        assert patchy.std() / patchy.mean() > 3 * (even.std() / even.mean())


def test_region_with_falloff_is_denser_at_the_centre():
    """A circular region around a prim with smooth falloff is densest at its centre."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "ground.usda", lambda x, z: 0.0 * x)
        _box_asset(lib / "tree.usda", (0.6, 4.0, 0.6))
        _box_asset(lib / "leaf.usda", (0.05, 0.01, 0.05))
        ground = _place(state, "ground.usda", "Ground")
        tree = _place(state, "tree.usda", "Tree", group="Props", at=(3.0, 0.0, -2.0))

        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Leaves", "assets": [{"asset": "leaf.usda"}], "surfaces": [ground],
            "count": 3000,
            "region": {"center_prim": tree, "radius": 4.0, "falloff": "smooth"},
        })).success
        pts = np.array([list(m.ExtractTranslation()) for m in
                        _instance_matrices(project, "/Scene/Scatter/Leaves")])
        r = np.hypot(pts[:, 0] - 3.0, pts[:, 2] + 2.0)
        assert r.max() <= 4.0 + 1e-6
        inner = (r < 2.0).sum() / (math.pi * 4.0)
        outer = (r >= 2.0).sum() / (math.pi * 12.0)
        assert inner > 3 * outer


def test_rows_drape_over_the_hillside():
    """Row arrangement keeps row spacing in plan and rests each plant on the hill."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "hill.usda", lambda x, z: 0.3 * z + 0.2 * np.sin(x))
        _box_asset(lib / "vine.usda", (0.2, 1.0, 0.2))
        hill = _place(state, "hill.usda", "Hill")

        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Vines", "assets": [{"asset": "vine.usda"}], "surfaces": [hill],
            "arrangement": "rows", "spacing": 1.0, "row_spacing": 2.5,
            "row_direction_degrees": 0, "align": "up", "random_yaw": False,
            "region": {"polygon": [[-5, 0, -5], [5, 0, -5], [5, 0, 5], [-5, 0, 5]]},
        }))
        assert result.success, result.error
        boxes = _instance_boxes(project, "/Scene/Scatter/Vines")
        centres = np.array([list((b.GetMin() + b.GetMax()) / 2) for b in boxes])
        rows = np.unique(np.round(centres[:, 2], 3))
        assert np.allclose(np.diff(rows), 2.5)
        bottoms = np.array([b.GetMin()[1] for b in boxes])
        ground = _ground_heights(project, hill, centres, up=1)
        assert np.abs(bottoms - ground).max() < 0.15


def test_a_pile_is_a_cone_at_its_angle_of_repose():
    """No taller than its cone, spread to the base radius, stones flat and none sunk."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "ground.usda", lambda x, z: 0.0 * x)
        _stone_asset(lib / "field_stone.usda", (0.23, 0.13, 0.16))
        _stone_asset(lib / "rock_a.usda", (0.4, 0.3, 0.35))
        _stone_asset(lib / "rock_b.usda", (0.3, 0.25, 0.3))
        ground = _place(state, "ground.usda", "Ground")

        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Heap", "surfaces": [ground], "arrangement": "pile", "count": 120,
            "repose_degrees": 30, "scale_range": [0.8, 1.2], "seed": 7,
            "assets": [{"asset": "field_stone.usda", "weight": 3},
                       {"asset": "rock_a.usda"}, {"asset": "rock_b.usda"}],
            "region": {"center": [2.0, 0.0, 1.0], "radius": 1.8},
        }))
        assert result.success, result.error
        assert result.data["instances"] == 120
        assert not result.data["warnings"], result.data["warnings"]

        shapes = _instance_shapes(project, "/Scene/Scatter/Heap")
        lowest = np.array([s[:, 1].min() for s in shapes])
        highest = np.array([s[:, 1].max() for s in shapes])
        reach = np.array([np.hypot(*(s.mean(axis=0)[[0, 2]] - [2.0, 1.0])) for s in shapes])
        cone = 1.8 * math.tan(math.radians(30))
        assert highest.max() < cone + 0.5, f"the heap is {highest.max():.2f} tall"
        assert highest.max() > 0.4, "the stones did not heap up"
        assert reach.max() > 1.4, "the heap did not spread to its base radius"
        assert lowest.min() > -0.005, "a stone is sunk into the ground"
        for m in _instance_matrices(project, "/Scene/Scatter/Heap"):
            thin = np.array(m.TransformDir(Gf.Vec3d(0, 1, 0)).GetNormalized())
            assert abs(thin[1]) > math.cos(math.radians(11)), "a stone stands on its edge"


def test_a_small_pile_spreads_over_its_base_and_rests_on_the_ground():
    """Ten stones spread over the base and lie on the ground by their shape, not their box."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "ground.usda", lambda x, z: 0.0 * x)
        _stone_asset(lib / "field_stone.usda", (0.23, 0.13, 0.16))
        ground = _place(state, "ground.usda", "Ground")

        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Few", "assets": [{"asset": "field_stone.usda"}], "surfaces": [ground],
            "arrangement": "pile", "count": 10, "seed": 1,
            "region": {"center": [0.0, 0.0, 0.0], "radius": 3.0},
        })).success
        shapes = _instance_shapes(project, "/Scene/Scatter/Few")
        centres = np.array([s.mean(axis=0) for s in shapes])
        assert (np.hypot(centres[:, 0], centres[:, 2]) < 0.75).sum() <= 3
        lowest = np.array([s[:, 1].min() for s in shapes])
        assert lowest.min() > -0.005
        assert (lowest < 0.02).sum() >= 9, f"stones hover: {np.round(lowest, 3)}"


def test_a_pile_too_big_for_its_radius_spreads_and_warns():
    """More pieces than the cone holds widen the base instead of building a tower."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "ground.usda", lambda x, z: 0.0 * x)
        _box_asset(lib / "rock.usda", (0.25, 0.2, 0.3))
        ground = _place(state, "ground.usda", "Ground")

        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Heap", "assets": [{"asset": "rock.usda"}], "surfaces": [ground],
            "arrangement": "pile", "count": 400,
            "region": {"center": [2.0, 0.0, 1.0], "radius": 1.0},
        }))
        assert result.success, result.error
        assert result.data["instances"] == 400
        spread = re.search(r"spread to a radius of (\d+\.\d+)", " ".join(result.data["warnings"]))
        assert spread, result.data["warnings"]
        base = float(spread.group(1))
        boxes = _instance_boxes(project, "/Scene/Scatter/Heap")
        bottoms = np.array([b.GetMin()[1] for b in boxes])
        tops = np.array([b.GetMax()[1] for b in boxes])
        assert bottoms.min() > -0.02, "a piece is sunk into the ground"
        assert tops.max() > 0.8, "the pieces did not heap up"
        assert tops.max() < base * math.tan(math.radians(35)) + 0.5, "the heap is a tower"


def test_moss_covers_every_face_of_a_curved_rock():
    """max_slope_degrees=180 covers the whole curved surface, undersides included."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        stage = _new_asset(lib / "rock.usda")
        UsdGeom.Sphere.Define(stage, "/rock/geom").CreateRadiusAttr(1.0)
        stage.Save()
        _box_asset(lib / "moss.usda", (0.05, 0.02, 0.05))
        rock = _place(state, "rock.usda", "Rock", group="Props", at=(0.0, 2.0, 0.0))

        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Moss", "assets": [{"asset": "moss.usda"}], "surfaces": [rock],
            "density": 60, "max_slope_degrees": 180, "align": "surface",
        })).success
        matrices = _instance_matrices(project, "/Scene/Scatter/Moss")
        base = np.array([list(m.ExtractTranslation()) for m in matrices])
        radial = base - np.array([0.0, 2.0, 0.0])
        radius = np.linalg.norm(radial, axis=1)
        assert np.abs(radius - 1.0).max() < 0.02
        assert (radial[:, 1] < -0.5).sum() > 50, "the underside got no moss"
        ups = np.array([list(m.TransformDir(Gf.Vec3d(0, 1, 0)).GetNormalized()) for m in matrices])
        assert np.einsum("ij,ij->i", ups, radial / radius[:, None]).min() > 0.98


def test_flipped_normals_are_diagnosed():
    """A surface whose normals point down is refused with a clear diagnosis."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "flipped.usda", lambda x, z: 0.0 * x, flip=True)
        _box_asset(lib / "stone.usda", (0.1, 0.1, 0.1))
        ground = _place(state, "flipped.usda", "Flipped")
        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Stones", "assets": [{"asset": "stone.usda"}], "surfaces": [ground],
            "count": 10,
        }))
        assert not result.success
        assert "point downward" in result.error and "180" in result.error


def test_validate_only_estimates_and_writes_nothing():
    """validate_only reports the estimated count and area without authoring."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "flat.usda", lambda x, z: 0.0 * x, size=10.0)
        _box_asset(lib / "grass.usda", (0.05, 0.2, 0.05))
        ground = _place(state, "flat.usda", "Flat")
        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Grass", "assets": [{"asset": "grass.usda"}], "surfaces": [ground],
            "density": 1000, "validate_only": True,
        }))
        assert result.success, result.error
        assert abs(result.data["estimated_instances"] - 100_000) < 2_000
        assert round(result.data["eligible_area_m2"]) == 100
        assert not Usd.Stage.Open(str(project.scene_path)).GetPrimAtPath("/Scene/Scatter/Grass")


def test_validate_only_measures_an_l_shaped_region():
    """The eligible area is the region's own area, not its bounding box's."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "flat.usda", lambda x, z: 0.0 * x)
        _box_asset(lib / "grass.usda", (0.05, 0.2, 0.05))
        ground = _place(state, "flat.usda", "Flat")
        l_shape = [[-10, 0, -10], [10, 0, -10], [10, 0, -6], [-6, 0, -6], [-6, 0, 10], [-10, 0, 10]]
        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Grass", "assets": [{"asset": "grass.usda"}], "surfaces": [ground],
            "density": 5, "region": {"polygon": l_shape}, "validate_only": True,
        }))
        assert result.success, result.error
        assert abs(result.data["eligible_area_m2"] - 144) < 144 * 0.05
        assert abs(result.data["estimated_instances"] - 720) < 720 * 0.1


def test_placements_output_is_individually_editable():
    """output='placements' writes regular wrappers that move_asset can edit."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "floor.usda", lambda x, z: 0.0 * x)
        _box_asset(lib / "crate.usda", (0.5, 0.5, 0.5))
        _box_asset(lib / "barrel.usda", (0.4, 0.8, 0.4))
        floor = _place(state, "floor.usda", "Floor")

        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Debris", "group": "Warehouse", "surfaces": [floor], "count": 20,
            "assets": [{"asset": "crate.usda", "weight": 3}, {"asset": "barrel.usda"}],
            "align": "up", "output": "placements",
        }))
        assert result.success, result.error
        assert sum(result.data["by_asset"].values()) == 20
        stage = Usd.Stage.Open(str(project.scene_path))
        wrappers = stage.GetPrimAtPath("/Scene/Warehouse/Debris").GetChildren()
        assert len(wrappers) == 20
        moved = asyncio.run(exec_tool(state, "move_asset", {
            "prim_path": str(wrappers[0].GetPath()), "translate_x": 5.0,
        }))
        assert moved.success, moved.error


def test_z_up_centimeter_scene_with_y_up_meter_assets():
    """Y-up meter assets scattered into a Z-up centimeter scene are conformed and rest on it."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp, up=UpAxis.Z, mpu=0.01)
        _grid_mesh(lib / "terrain.usda", lambda a, b: 30.0 * np.sin(a / 200.0),
                   size=2000.0, up="Z", mpu=0.01)
        _box_asset(lib / "stone.usda", (0.2, 0.2, 0.2))
        ground = _place(state, "terrain.usda", "Terrain")

        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Stones", "assets": [{"asset": "stone.usda"}], "surfaces": [ground],
            "density": 2, "align": "up", "random_yaw": False,
        }))
        assert result.success, result.error
        assert abs(result.data["instances"] - 800) < 80
        boxes = _instance_boxes(project, "/Scene/Scatter/Stones")
        sizes = np.array([list(b.GetMax() - b.GetMin()) for b in boxes])
        assert np.allclose(sizes[:, 2], 20.0, atol=0.1), "stone is not 20 cm tall along +Z"
        centres = np.array([list((b.GetMin() + b.GetMax()) / 2) for b in boxes])
        ground_z = _ground_heights(project, ground, centres, up=2)
        assert np.abs(np.array([b.GetMin()[2] for b in boxes]) - ground_z).max() < 3.0


def test_list_scene_remove_and_validate_treat_a_scatter_as_one_object():
    """list_scene, validate_scene, remove_prim and asset deletion treat a scatter as one object."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "terrain.usda", _bumps)
        _box_asset(lib / "stone.usda", (0.2, 0.2, 0.2))
        ground = _place(state, "terrain.usda", "Terrain")
        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Stones", "assets": [{"asset": "stone.usda"}], "surfaces": [ground],
            "count": 500,
        })).success

        objects = asyncio.run(exec_tool(state, "list_scene")).data["objects"]
        scatters = [o for o in objects if o["kind"] == "scatter"]
        found = [(o["prim_path"], o["instances"]) for o in scatters]
        assert found == [("/Scene/Scatter/Stones", 500)]
        assert not any("Prototypes" in o["prim_path"] for o in objects)

        report = asyncio.run(exec_tool(state, "validate_scene")).data
        assert [i for i in report["issues"] if i["severity"] == "error"] == []

        listed = asyncio.run(exec_tool(state, "list_project_assets")).data["assets"]
        in_scene = {a["name"]: a["in_scene"] for a in listed}
        assert in_scene["stone"] is True
        refused = asyncio.run(exec_tool(state, "delete_project_asset", {"name": "stone"}))
        assert not refused.success and "still referenced" in refused.error

        removed = asyncio.run(exec_tool(
            state, "remove_prim", {"prim_path": "/Scene/Scatter/Stones"},
        ))
        assert removed.success
        listed = asyncio.run(exec_tool(state, "list_project_assets")).data["assets"]
        in_scene = {a["name"]: a["in_scene"] for a in listed}
        assert in_scene["stone"] is False
        assert asyncio.run(exec_tool(state, "delete_project_asset", {"name": "stone"})).success


def test_scatter_is_authored_in_the_scene_like_placements():
    """The instancer lives in scene.usda; each prototype is a place_asset-style wrapper."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "terrain.usda", _bumps)
        _box_asset(lib / "stone.usda", (0.2, 0.2, 0.2))
        _box_asset(lib / "crate.usda", (0.5, 0.5, 0.5))
        ground = _place(state, "terrain.usda", "Terrain")
        crate = _place(state, "crate.usda", "Crate", group="Props", at=(3.0, 2.0, 3.0))
        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Stones", "group": "Nature", "assets": [{"asset": "stone.usda"}],
            "surfaces": [ground], "count": 50,
        })).success

        assert sorted(p.name for p in project.path.iterdir()) == [
            "assets", "project.json", "scene.usda",
        ]
        stage = Usd.Stage.Open(str(project.scene_path))
        instancer = stage.GetPrimAtPath("/Scene/Nature/Stones")
        assert instancer.GetTypeName() == "PointInstancer"
        assert instancer.GetPrimStack()[0].layer == stage.GetRootLayer()
        proto_asset = stage.GetPrimAtPath("/Scene/Nature/Stones/Prototypes/stone/asset")
        refs = proto_asset.GetMetadata("references").prependedItems
        assert [r.assetPath for r in refs] == ["assets/stone/stone.usda"]

        moved = asyncio.run(exec_tool(
            state, "move_asset", {"prim_path": "/Scene/Nature/Stones", "translate_x": 1.0},
        ))
        assert moved.success, moved.error
        stage = Usd.Stage.Open(str(project.scene_path))
        world = UsdGeom.Xformable(stage.GetPrimAtPath("/Scene/Nature/Stones"))
        moved_to = world.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        assert moved_to.ExtractTranslation()[0] == 1.0

        dropped = asyncio.run(exec_tool(
            state, "drop_to_surface", {"prim_paths": ["/Scene/Props", "/Scene/Nature"]},
        ))
        assert dropped.success, dropped.error
        moved_paths = {r["prim_path"] for r in dropped.data["moved"]}
        assert crate in moved_paths
        assert not any("Prototypes" in p for p in moved_paths)


def test_a_large_scatter_stays_fast():
    """A quarter-million instances scatter in one call and warn about scene size."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "terrain.usda", _bumps, n=101, size=100.0)
        _box_asset(lib / "blade.usda", (0.02, 0.1, 0.02))
        ground = _place(state, "terrain.usda", "Terrain")
        result = asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Grass", "assets": [{"asset": "blade.usda"}], "surfaces": [ground],
            "count": 250_000, "variation": 0.5, "align": "up",
        }))
        assert result.success, result.error
        assert result.data["instances"] == 250_000
        assert any("MB to scene.usda" in w for w in result.data["warnings"])


# ── scatter_along_path ──


def test_chairs_round_a_table_face_the_centre():
    """Chairs on a circle around a table face it, rest on the floor, and survive move_asset."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "floor.usda", lambda x, z: 0.0 * x)
        _box_asset(lib / "table.usda", (1.2, 0.75, 1.2))
        _box_asset(lib / "chair.usda", (0.5, 0.9, 0.5))
        _place(state, "floor.usda", "Floor")
        table = _place(state, "table.usda", "Table", group="Furniture", at=(2.0, 0.0, 3.0))

        result = asyncio.run(exec_tool(state, "scatter_along_path", {
            "name": "Chairs", "group": "Furniture", "assets": [{"asset": "chair.usda"}],
            "circle": {"center_prim": table, "radius": 1.1}, "count": 6, "facing": "center",
        }))
        assert result.success, result.error
        stage = Usd.Stage.Open(str(project.scene_path))
        chairs = stage.GetPrimAtPath("/Scene/Furniture/Chairs").GetChildren()
        assert len(chairs) == 6
        for chair in chairs:
            m = UsdGeom.Xformable(chair).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            pos = np.array(m.ExtractTranslation())
            front = np.array(m.TransformDir(Gf.Vec3d(0, 0, 1)).GetNormalized())
            to_table = np.array([2.0, 0.0, 3.0]) - pos
            to_table /= np.linalg.norm(to_table)
            assert front @ to_table > 0.999
            assert abs(np.hypot(pos[0] - 2.0, pos[2] - 3.0) - 1.1) < 1e-3
            assert abs(pos[1]) < 1e-4
            rx, _, rz = chair.GetAttribute("xformOp:rotateXYZ").Get()
            assert rx == 0.0 and rz == 0.0, "upright chairs should be written as a pure yaw"

        # move_asset edits only the Y angle; a pure-yaw chair keeps facing the table.
        first = str(chairs[0].GetPath())
        nudged = asyncio.run(exec_tool(
            state, "move_asset", {"prim_path": first, "translate_y": 0.0},
        ))
        assert nudged.success
        stage = Usd.Stage.Open(str(project.scene_path))
        m = UsdGeom.Xformable(stage.GetPrimAtPath(first)).ComputeLocalToWorldTransform(
            Usd.TimeCode.Default(),
        )
        front = np.array(m.TransformDir(Gf.Vec3d(0, 0, 1)).GetNormalized())
        to_table = np.array([2.0, 0.0, 3.0]) - np.array(m.ExtractTranslation())
        assert front @ (to_table / np.linalg.norm(to_table)) > 0.999


def test_streetlights_on_both_sides_face_the_road():
    """sides='both' with an offset puts lamps on each side, facing the road line."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "ground.usda", _bumps)
        _box_asset(lib / "lamp.usda", (0.2, 4.0, 0.2))
        ground = _place(state, "ground.usda", "Ground")

        result = asyncio.run(exec_tool(state, "scatter_along_path", {
            "name": "Lights", "assets": [{"asset": "lamp.usda"}],
            "points": [[-8, 0, 0], [8, 0, 0]], "spacing": 4.0,
            "sides": "both", "offset": 3.0, "facing": "path", "surfaces": [ground],
        }))
        assert result.success, result.error
        assert result.data["instances"] == 10
        stage = Usd.Stage.Open(str(project.scene_path))
        for lamp in stage.GetPrimAtPath("/Scene/Scatter/Lights").GetChildren():
            m = UsdGeom.Xformable(lamp).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            pos = np.array(m.ExtractTranslation())
            assert abs(abs(pos[2]) - 3.0) < 1e-3
            front = np.array(m.TransformDir(Gf.Vec3d(0, 0, 1)).GetNormalized())
            assert front[2] * np.sign(pos[2]) < -0.999, "lamp does not face the road"
            assert abs(pos[1] - _bumps(pos[0], pos[2])) < 0.2


def test_fence_sections_butt_end_to_end_and_follow_the_slope():
    """Automatic spacing butts sections end to end; follow_slope pitches them with the hill."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "slope.usda", lambda x, z: 0.25 * x)
        _box_asset(lib / "section.usda", (2.0, 1.0, 0.1))
        slope = _place(state, "slope.usda", "Slope")

        result = asyncio.run(exec_tool(state, "scatter_along_path", {
            "name": "Fence", "assets": [{"asset": "section.usda"}],
            "points": [[-5, 0, 2], [5, 0, 2]], "facing": "tangent",
            "follow_slope": True, "surfaces": [slope], "start_offset": 1.0,
        }))
        assert result.success, result.error
        assert result.data["instances"] == 5
        stage = Usd.Stage.Open(str(project.scene_path))
        sections = stage.GetPrimAtPath("/Scene/Scatter/Fence").GetChildren()
        xs = []
        for section in sections:
            m = UsdGeom.Xformable(section).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            long_axis = np.array(m.TransformDir(Gf.Vec3d(1, 0, 0)).GetNormalized())
            assert abs(abs(long_axis[0]) - math.cos(math.atan(0.25))) < 1e-3
            assert abs(abs(long_axis[1]) - math.sin(math.atan(0.25))) < 1e-3
            xs.append(m.ExtractTranslation()[0])
        assert np.allclose(np.diff(sorted(xs)), 2.0, atol=1e-3)


def test_products_along_a_shelf_rest_on_the_shelf_not_the_floor():
    """Path points at shelf height snap to the shelf top, not the floor below."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "floor.usda", lambda x, z: 0.0 * x)
        _box_asset(lib / "shelf.usda", (3.0, 1.0, 0.5))
        _box_asset(lib / "can.usda", (0.1, 0.15, 0.1))
        _place(state, "floor.usda", "Floor")
        shelf = _place(state, "shelf.usda", "Shelf", group="Furniture", at=(0.0, 0.0, -4.0))

        result = asyncio.run(exec_tool(state, "scatter_along_path", {
            "name": "Cans", "assets": [{"asset": "can.usda"}],
            "points": [[-1.4, 1.0, -4.0], [1.4, 1.0, -4.0]], "gap": 0.02,
            "facing": "fixed", "direction_degrees": 90,
        }))
        assert result.success, result.error
        assert result.data["instances"] == 24
        stage = Usd.Stage.Open(str(project.scene_path))
        for can in stage.GetPrimAtPath("/Scene/Scatter/Cans").GetChildren():
            m = UsdGeom.Xformable(can).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            assert abs(m.ExtractTranslation()[1] - 1.0) < 1e-4
        assert shelf


def test_fence_around_a_closed_boundary_uses_even_sections():
    """A closed boundary gets evenly spaced sections running along each edge."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "ground.usda", lambda x, z: 0.0 * x)
        _box_asset(lib / "section.usda", (2.0, 1.0, 0.1))
        _place(state, "ground.usda", "Ground")

        result = asyncio.run(exec_tool(state, "scatter_along_path", {
            "name": "Paddock", "assets": [{"asset": "section.usda"}], "closed": True,
            "points": [[-4, 0, -4], [4, 0, -4], [4, 0, 4], [-4, 0, 4]],
            "start_offset": 1.0,
        }))
        assert result.success, result.error
        assert result.data["instances"] == 16
        stage = Usd.Stage.Open(str(project.scene_path))
        for section in stage.GetPrimAtPath("/Scene/Scatter/Paddock").GetChildren():
            m = UsdGeom.Xformable(section).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            pos = np.array(m.ExtractTranslation())
            assert abs(max(abs(pos[0]), abs(pos[2])) - 4.0) < 1e-3, "section left the boundary"
            long_axis = np.array(m.TransformDir(Gf.Vec3d(1, 0, 0)).GetNormalized())
            along_x_edge = abs(abs(pos[2]) - 4.0) < 1e-3
            assert abs(long_axis[0 if along_x_edge else 2]) > 0.999


def test_posts_follow_a_winding_curve_prim():
    """Posts follow a BasisCurves prim and rest on the ground under it."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "ground.usda", _bumps)
        _box_asset(lib / "post.usda", (0.15, 1.2, 0.15))
        ground = _place(state, "ground.usda", "Ground")
        stage = Usd.Stage.Open(str(project.scene_path))
        road = UsdGeom.BasisCurves.Define(stage, "/Scene/Roads/Road")
        t = np.linspace(-8.0, 8.0, 40)
        road.CreatePointsAttr([Gf.Vec3f(float(x), 0.0, float(3.0 * np.sin(x / 3.0))) for x in t])
        road.CreateCurveVertexCountsAttr([len(t)])
        road.CreateTypeAttr(UsdGeom.Tokens.linear)
        stage.Save()

        result = asyncio.run(exec_tool(state, "scatter_along_path", {
            "name": "Posts", "assets": [{"asset": "post.usda"}], "curve_prim": "/Scene/Roads/Road",
            "spacing": 2.0, "surfaces": [ground],
        }))
        assert result.success, result.error
        stage = Usd.Stage.Open(str(project.scene_path))
        posts = stage.GetPrimAtPath("/Scene/Scatter/Posts").GetChildren()
        assert len(posts) >= 10
        for post in posts:
            pos = np.array(UsdGeom.Xformable(post).ComputeLocalToWorldTransform(
                Usd.TimeCode.Default()).ExtractTranslation())
            assert abs(pos[2] - 3.0 * np.sin(pos[0] / 3.0)) < 0.05, "post left the road line"
            assert abs(pos[1] - _bumps(pos[0], pos[2])) < 0.05, "post is not on the ground"


# ── drop_to_surface ──


def test_drop_to_surface_lifts_sunken_and_lowers_floating_objects():
    """Dropped placements rest on the highest ground under their footprint."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "terrain.usda", _bumps)
        _box_asset(lib / "crate.usda", (0.6, 0.6, 0.6))
        ground = _place(state, "terrain.usda", "Terrain")
        floating = _place(state, "crate.usda", "Floating", group="Props", at=(2.0, 5.0, 1.0))
        sunken = _place(state, "crate.usda", "Sunken", group="Props", at=(-3.0, -2.0, 4.0))

        result = asyncio.run(exec_tool(state, "drop_to_surface", {"prim_paths": ["/Scene/Props"]}))
        assert result.success, result.error
        assert {r["prim_path"] for r in result.data["moved"]} == {floating, sunken}

        stage = Usd.Stage.Open(str(project.scene_path))
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
        for path in (floating, sunken):
            box = cache.ComputeWorldBound(stage.GetPrimAtPath(path)).ComputeAlignedRange()
            lo, hi = box.GetMin(), box.GetMax()
            grid = np.linspace(0.1, 0.9, 3)
            footprint = np.array([
                [lo[0] + a * (hi[0] - lo[0]), 0.0, lo[2] + b * (hi[2] - lo[2])]
                for a in grid for b in grid
            ])
            highest = np.nanmax(_ground_heights(project, ground, footprint, up=1))
            assert abs(lo[1] - highest) < 1e-3


def test_drop_to_surface_can_tilt_onto_the_slope():
    """align='surface' tilts a dropped placement onto the slope and seats it."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "slope.usda", lambda x, z: 0.3 * z)
        _box_asset(lib / "crate.usda", (0.6, 0.6, 0.6))
        _place(state, "slope.usda", "Slope")
        crate = _place(state, "crate.usda", "Crate", group="Props", at=(1.0, 4.0, 2.0))

        tilted = asyncio.run(exec_tool(
            state, "drop_to_surface", {"prim_paths": [crate], "align": "surface"},
        ))
        assert tilted.success
        stage = Usd.Stage.Open(str(project.scene_path))
        m = UsdGeom.Xformable(stage.GetPrimAtPath(crate)).ComputeLocalToWorldTransform(
            Usd.TimeCode.Default(),
        )
        up = np.array(m.TransformDir(Gf.Vec3d(0, 1, 0)).GetNormalized())
        expected = np.array([0.0, 1.0, -0.3]) / math.hypot(1.0, 0.3)
        assert up @ expected > 0.9999
        base = np.array(m.Transform(Gf.Vec3d(0, 0, 0)))
        assert abs(base[1] - 0.3 * base[2]) < 1e-3


def test_drop_to_surface_reseats_a_sunken_scatter_in_place():
    """Dropping a scatter lifts every instance onto the ground and keeps its variant sets."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "field.usda", _ridges, n=81)
        _tree_asset(lib / "tree.usda")
        ground = _place(state, "field.usda", "Field")
        scatter = "/Scene/Vegetation/Trees"
        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Trees", "group": "Vegetation", "assets": [{"asset": "tree.usda"}],
            "surfaces": [ground], "count": 30, "align": "up",
        })).success

        # Sink the scatter, push one tree off the field, add a variant set.
        instancer = UsdGeom.PointInstancer(state.stage.GetPrimAtPath(scatter))
        positions = np.asarray(instancer.GetPositionsAttr().Get()) - [0.0, 3.0, 0.0]
        positions[0, 0] = 15.0
        instancer.GetPositionsAttr().Set(Vt.Vec3fArray.FromNumpy(positions.astype(np.float32)))
        before_q = np.asarray(instancer.GetOrientationsAttr().Get())
        variants = state.stage.GetPrimAtPath(f"{scatter}/Prototypes/tree").GetVariantSets()
        model = variants.AddVariantSet("model")
        model.AddVariant("oak")
        model.AddVariant("poplar")
        model.SetVariantSelection("oak")
        state.stage.Save()
        assert np.nanmin(_pivot_depths(project, scatter, ground)) > 2.5

        result = asyncio.run(exec_tool(
            state, "drop_to_surface", {"prim_paths": ["/Scene/Vegetation"]},
        ))
        assert result.success, result.error
        report = result.data["scatters"][0]
        assert report["instances"] == 30
        assert report["no_surface_under"]["count"] == 1
        assert report["no_surface_under"]["instances"] == [0]
        assert "no surface under their base" in result.data["message"]
        depth = _pivot_depths(project, scatter, ground)[1:]
        assert depth.min() > -1e-3 and depth.max() < 0.2

        stage = Usd.Stage.Open(str(project.scene_path))
        instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(scatter))
        assert np.array_equal(np.asarray(instancer.GetOrientationsAttr().Get()), before_q)
        model = stage.GetPrimAtPath(f"{scatter}/Prototypes/tree").GetVariantSet("model")
        assert model.GetVariantNames() == ["oak", "poplar"]
        assert model.GetVariantSelection() == "oak"


def test_drop_to_surface_retilts_a_scatter_onto_the_ground_keeping_headings():
    """align='surface' re-tilts badly tilted scatter pieces onto the ground under them."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "field.usda", _ridges, n=81)
        _box_asset(lib / "log.usda", (2.5, 0.25, 0.25))
        ground = _place(state, "field.usda", "Field")
        scatter = "/Scene/Scatter/Logs"
        assert asyncio.run(exec_tool(state, "scatter_on_surface", {
            "name": "Logs", "assets": [{"asset": "log.usda"}], "surfaces": [ground],
            "count": 30, "align": "surface", "random_yaw": False,
            "region": {"polygon": [[-8, 0, -8], [8, 0, -8], [8, 0, 8], [-8, 0, 8]]},
        })).success

        # Tip every log 25 degrees along its length, as one ridge face would.
        instancer = UsdGeom.PointInstancer(state.stage.GetPrimAtPath(scatter))
        tip = Gf.Quath(math.cos(math.radians(12.5)), Gf.Vec3h(0, 0, math.sin(math.radians(12.5))))
        instancer.GetOrientationsAttr().Set(Vt.QuathArray([tip] * 30))
        state.stage.Save()
        assert np.abs(_log_end_gaps(project, scatter, ground)).max() > 0.4

        result = asyncio.run(exec_tool(
            state, "drop_to_surface", {"prim_paths": [scatter], "align": "surface"},
        ))
        assert result.success, result.error
        assert result.data["scatters"][0]["retilted"] == 30
        gaps = _log_end_gaps(project, scatter, ground)
        assert gaps.max() < 1e-3 and gaps.min() > -0.35
        for m in _instance_matrices(project, scatter):
            length_axis = np.array(m.TransformDir(Gf.Vec3d(1, 0, 0)))
            length_axis[1] = 0.0
            assert length_axis[0] / np.linalg.norm(length_axis) > 0.99, "heading changed"


# ── parameter validation ──


def test_parameter_rules_are_reported_clearly():
    """Cross-field and missing-prim problems come back as clear errors."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project, lib = _setup(tmp)
        _grid_mesh(lib / "ground.usda", lambda x, z: 0.0 * x)
        _box_asset(lib / "rock.usda", (0.2, 0.2, 0.2))
        ground = _place(state, "ground.usda", "Ground")
        base = {"name": "Rocks", "assets": [{"asset": "rock.usda"}], "surfaces": [ground]}

        both = asyncio.run(exec_tool(
            state, "scatter_on_surface", {**base, "count": 5, "density": 1},
        ))
        assert "exactly one of 'count' or 'density'" in both.error
        pile = asyncio.run(exec_tool(
            state, "scatter_on_surface", {**base, "arrangement": "pile", "count": 5},
        ))
        assert "circular 'region'" in pile.error
        missing = asyncio.run(exec_tool(
            state, "scatter_on_surface", {**base, "surfaces": ["/Scene/Nope"], "count": 5},
        ))
        assert "not found" in missing.error
        path = asyncio.run(exec_tool(state, "scatter_along_path", {
            "name": "Posts", "assets": [{"asset": "rock.usda"}],
            "points": [[0, 0, 0], [1, 0, 0]], "circle": {"center": [0, 0, 0], "radius": 1},
        }))
        assert "exactly one of 'points', 'circle', or 'curve_prim'" in path.error
