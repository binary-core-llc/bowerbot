# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Per-project scene defaults: up-axis, units, and the placement conform."""

import asyncio
import json
import tempfile
from pathlib import Path

from pxr import Gf, Usd, UsdGeom

from bowerbot.config import UpAxis
from bowerbot.project import Project
from bowerbot.services import project_service
from bowerbot.state import SceneState
from bowerbot.utils.core.metrics import asset_conform
from tests._helpers import exec_tool


def _make_asset(directory: Path, name: str, up_axis: str) -> Path:
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(
        stage, UsdGeom.Tokens.z if up_axis == "Z" else UsdGeom.Tokens.y,
    )
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, f"/{name}/Mesh").GetSizeAttr().Set(1.0)
    stage.Save()
    return path


def _state(tmp: str) -> SceneState:
    state = SceneState(library_dir=Path(tmp))
    state.projects_dir = Path(tmp)
    return state


# ── Project.create authors per-project metadata ──


def test_create_project_authors_up_axis_and_units():
    """A Z-up centimeter project authors those into scene.usda and project.json."""
    with tempfile.TemporaryDirectory() as tmp:
        project = Project.create(
            Path(tmp), "warehouse", up_axis=UpAxis.Z, meters_per_unit=0.01,
        )
        stage = Usd.Stage.Open(str(project.scene_path))
        assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z
        assert UsdGeom.GetStageMetersPerUnit(stage) == 0.01
        raw = json.loads(project.meta_path.read_text(encoding="utf-8"))
        assert raw["up_axis"] == "Z"
        assert raw["meters_per_unit"] == 0.01


def test_create_project_defaults_to_y_meters():
    """Defaults are Y-up, meters."""
    with tempfile.TemporaryDirectory() as tmp:
        project = Project.create(Path(tmp), "p")
        stage = Usd.Stage.Open(str(project.scene_path))
        assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y
        assert UsdGeom.GetStageMetersPerUnit(stage) == 1.0


def test_old_project_json_migrates_to_defaults():
    """A project.json without the new fields loads with Y / 1.0 defaults."""
    with tempfile.TemporaryDirectory() as tmp:
        pdir = Path(tmp) / "legacy"
        pdir.mkdir()
        (pdir / "assets").mkdir()
        (pdir / "project.json").write_text(
            json.dumps({"name": "legacy", "scene_file": "scene.usda"}),
            encoding="utf-8",
        )
        project = Project.load(pdir)
        assert project.meta.up_axis is UpAxis.Y
        assert project.meta.meters_per_unit == 1.0


# ── create_project service + tool ──


def test_create_project_service_threads_and_focuses():
    """The service stores the chosen axis/units and reflects them on state."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _state(tmp)
        data = project_service.create_project(
            state, {"name": "wh", "up_axis": "Z", "meters_per_unit": 0.01},
        )
        assert data["up_axis"] == "Z"
        assert data["meters_per_unit"] == 0.01
        assert state.up_axis is UpAxis.Z
        assert state.meters_per_unit == 0.01


def test_create_project_tool_accepts_params():
    """The create_project tool accepts up_axis + meters_per_unit."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _state(tmp)
        r = asyncio.run(exec_tool(
            state, "create_project",
            {"name": "wh", "up_axis": "Z", "meters_per_unit": 0.01},
        ))
        assert r.success, r.error
        assert r.data["up_axis"] == "Z"


# ── up-axis correction in add_reference ──


def test_up_axis_correction_signs():
    """Y->Z is +90, Z->Y is -90, matching axes is None."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        y_asset = _make_asset(d, "y_asset", "Y")
        z_asset = _make_asset(d, "z_asset", "Z")
        z_scene = Usd.Stage.CreateNew(str(d / "z_scene.usda"))
        UsdGeom.SetStageUpAxis(z_scene, UsdGeom.Tokens.z)
        z_scene.Save()
        y_scene = Usd.Stage.CreateNew(str(d / "y_scene.usda"))
        UsdGeom.SetStageUpAxis(y_scene, UsdGeom.Tokens.y)
        y_scene.Save()
        assert asset_conform(z_scene, str(y_asset))[1] == 90.0
        assert asset_conform(y_scene, str(z_asset))[1] == -90.0
        assert asset_conform(y_scene, str(y_asset))[1] is None


def test_y_asset_stands_up_in_z_scene():
    """A Y-up asset placed in a Z-up project gets a +90 rotateX mapping +Y to +Z."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project = Project.create(tmp_path, "wh", up_axis=UpAxis.Z)
        state = SceneState(up_axis=UpAxis.Z, library_dir=tmp_path)
        state.project = project
        state.stage_path = project.scene_path
        asyncio.run(exec_tool(state, "create_stage", {"filename": "scene"}))

        asset = _make_asset(tmp_path, "widget", "Y")
        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Widget",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        asset_prim = stage.GetPrimAtPath(r.data["prim_path"] + "/asset")
        local = UsdGeom.Xformable(asset_prim).GetLocalTransformation()
        up = local.TransformDir(Gf.Vec3d(0, 1, 0))
        assert abs(up[2] - 1.0) < 1e-6
        assert abs(up[0]) < 1e-6
        assert abs(up[1]) < 1e-6


def test_matching_axis_adds_no_correction():
    """A Y-up asset in a Y-up project authors no corrective rotation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project = Project.create(tmp_path, "studio", up_axis=UpAxis.Y)
        state = SceneState(up_axis=UpAxis.Y, library_dir=tmp_path)
        state.project = project
        state.stage_path = project.scene_path
        asyncio.run(exec_tool(state, "create_stage", {"filename": "scene"}))

        asset = _make_asset(tmp_path, "widget", "Y")
        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Widget",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        asset_prim = stage.GetPrimAtPath(r.data["prim_path"] + "/asset")
        ops = UsdGeom.Xformable(asset_prim).GetOrderedXformOps()
        assert ops == []


# ── placement in the scene's axes and units ──


def _plank(
    directory: Path, name: str, up_axis: str, *, mpu: float = 1.0,
    size: tuple[float, float, float] = (4.0, 0.2, 0.5),
) -> Path:
    """A box asset of *size* in its own axes (so orientation shows in world bounds)."""
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, mpu)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z if up_axis == "Z" else UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    board = UsdGeom.Cube.Define(stage, f"/{name}/Board")
    board.GetSizeAttr().Set(1.0)
    board.AddScaleOp().Set(Gf.Vec3f(*size))
    stage.Save()
    return path


def _project(tmp: str, up_axis: str, mpu: float = 1.0) -> SceneState:
    state = _state(tmp)
    r = asyncio.run(exec_tool(state, "create_project", {
        "name": "p", "up_axis": up_axis, "meters_per_unit": mpu,
    }))
    assert r.success, r.error
    return state


def _call(state: SceneState, tool: str, params: dict) -> dict:
    r = asyncio.run(exec_tool(state, tool, params))
    assert r.success, r.error
    return r.data


def _place(state: SceneState, asset: str, *, at=(0.0, 0.0, 0.0), **extra) -> str:
    return _call(state, "place_asset", {
        "asset": asset, "asset_name": asset.title(), "group": "Props",
        "translate_x": at[0], "translate_y": at[1], "translate_z": at[2], **extra,
    })["prim_path"]


def _world_size(state: SceneState, path: str) -> tuple[float, ...]:
    stage = Usd.Stage.Open(str(state.stage_path))
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    size = cache.ComputeWorldBound(stage.GetPrimAtPath(path)).ComputeAlignedRange().GetSize()
    return tuple(round(v, 4) for v in size)


def _world_pos(state: SceneState, path: str) -> tuple[float, ...]:
    stage = Usd.Stage.Open(str(state.stage_path))
    matrix = UsdGeom.XformCache().GetLocalToWorldTransform(stage.GetPrimAtPath(path))
    return tuple(round(v, 4) for v in matrix.ExtractTranslation())


def test_rotate_about_the_up_axis_turns_an_asset_in_a_z_up_scene():
    """rotate_z turns a placement on the floor of a Z-up scene, placed or moved."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _project(tmp, "Z")
        _plank(Path(tmp), "plank", "Y")
        placed = _place(state, "plank", rotate_z=90.0)
        assert _world_size(state, placed) == (0.5, 4.0, 0.2)

        other = _place(state, "plank", at=(5.0, 0.0, 0.0))
        assert _world_size(state, other) == (4.0, 0.5, 0.2)
        moved = _call(state, "move_asset", {"prim_path": other, "rotate_z": 90.0})
        assert moved["rotation"] == {"x": 0.0, "y": 0.0, "z": 90.0}
        assert moved["position"] == {"x": 5.0, "y": 0.0, "z": 0.0}
        assert _world_size(state, other) == (0.5, 4.0, 0.2)


def test_move_asset_keeps_the_rotation_axes_it_does_not_name():
    """A move naming one rotation axis (or none) keeps the others."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _project(tmp, "Y")
        _plank(Path(tmp), "plank", "Y")
        placed = _place(state, "plank", rotate_x=10.0, rotate_y=20.0, rotate_z=30.0)
        _call(state, "move_asset", {"prim_path": placed, "rotate_y": 45.0})
        _call(state, "move_asset", {"prim_path": placed, "translate_x": 2.0})

        stage = Usd.Stage.Open(str(state.stage_path))
        prim = stage.GetPrimAtPath(placed)
        assert tuple(prim.GetAttribute("xformOp:rotateXYZ").Get()) == (10.0, 45.0, 30.0)
        assert tuple(prim.GetAttribute("xformOp:translate").Get()) == (2.0, 0.0, 0.0)


def test_list_scene_reports_world_positions_and_placement_paths():
    """Placements (top level and nested) and asset lights are listed where they are."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _project(tmp, "Y")
        _plank(Path(tmp), "shelf", "Y", size=(2.0, 1.0, 1.0))
        _plank(Path(tmp), "book", "Y", size=(0.2, 0.3, 0.1))
        shelf = _place(state, "shelf", at=(3.0, 0.0, 1.0))
        book = _call(state, "place_asset_inside", {
            "asset": "book", "asset_name": "Book", "container_prim_path": shelf,
            "group": "Props", "translate_x": 3.5, "translate_y": 0.5, "translate_z": 1.0,
        })["prim_path"]
        light = _call(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Bulb",
            "asset_prim_path": shelf, "translate_y": 0.5,
        })

        listed = {o["prim_path"]: o["position"] for o in _call(state, "list_scene", {})["objects"]}
        assert listed[shelf] == {"x": 3.0, "y": 0.0, "z": 1.0}
        assert listed[book] == {"x": 3.5, "y": 0.5, "z": 1.0}
        assert listed[light["prim_path"]] == {"x": 3.0, "y": 1.0, "z": 1.0}
        assert light["position"] == {"x": 3.0, "y": 1.0, "z": 1.0}
        assert f"{shelf}/asset" not in listed


def test_compute_grid_layout_follows_the_up_axis_and_units():
    """The grid lies on the ground plane, in scene units (2 m apart by default)."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _project(tmp, "Z", mpu=0.01)
        grid = _call(state, "compute_grid_layout", {"count": 2})
        first, second = grid["positions"]
        assert first["z"] == second["z"] == 0.0
        assert second["x"] - first["x"] == 200.0
        assert first["y"] == 400.0


def test_model_selection_variants_keep_their_own_units_and_up_axis():
    """Each model variant is conformed on its own; removing the set keeps the active one's."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _project(tmp, "Y")
        _plank(Path(tmp), "plank", "Y")
        _plank(Path(tmp), "plank_cm", "Y", mpu=0.01, size=(400.0, 20.0, 50.0))
        _plank(Path(tmp), "plank_z", "Z", size=(4.0, 0.5, 0.2))
        placed = _place(state, "plank")
        for variant, asset in (("cm", "plank_cm"), ("zup", "plank_z")):
            _call(state, "add_scene_model_selection_variant", {
                "prim_path": placed, "variant_set": "model", "variant_name": variant,
                "asset": asset, "set_as_default": True,
            })
            assert _world_size(state, placed) == (4.0, 0.2, 0.5), variant

        _call(state, "select_scene_variant", {
            "prim_path": placed, "variant_set": "model", "variant_name": "cm",
        })
        _call(state, "remove_scene_variant_set", {"prim_path": placed, "variant_set": "model"})
        assert _world_size(state, placed) == (4.0, 0.2, 0.5)


def test_model_selection_moves_an_older_placements_unit_scale_off_the_wrapper():
    """A placement authored with the unit scale on its wrapper keeps its size in every variant."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _project(tmp, "Y")
        _plank(Path(tmp), "plank", "Y")
        _plank(Path(tmp), "plank_cm", "Y", mpu=0.01, size=(400.0, 20.0, 50.0))
        placed = _place(state, "plank_cm")
        stage = state.require_stage()
        child = stage.GetPrimAtPath(f"{placed}/asset")
        UsdGeom.Xformable(child).ClearXformOpOrder()
        child.RemoveProperty("xformOp:scale")
        stage.GetPrimAtPath(placed).GetAttribute("xformOp:scale").Set(Gf.Vec3f(0.01, 0.01, 0.01))
        stage.Save()
        assert _world_size(state, placed) == (4.0, 0.2, 0.5)

        _call(state, "add_scene_model_selection_variant", {
            "prim_path": placed, "variant_set": "model", "variant_name": "meters",
            "asset": "plank", "set_as_default": True,
        })
        assert _world_size(state, placed) == (4.0, 0.2, 0.5)
        _call(state, "select_scene_variant", {
            "prim_path": placed, "variant_set": "model", "variant_name": "plank_cm",
        })
        assert _world_size(state, placed) == (4.0, 0.2, 0.5)
        stage = Usd.Stage.Open(str(state.stage_path))
        assert tuple(stage.GetPrimAtPath(placed).GetAttribute("xformOp:scale").Get()) == (1, 1, 1)


def test_asset_lights_use_the_scene_axes_in_a_z_up_scene():
    """absolute and bounds_offset positions and rotations follow the Z-up scene."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _project(tmp, "Z")
        _make_asset(Path(tmp), "table", "Y")
        table = _place(state, "table", at=(5.0, 2.0, 0.0))

        absolute = _call(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Abs", "asset_prim_path": table,
            "position_mode": "absolute", "translate_x": 5.0, "translate_y": 2.0, "translate_z": 3.0,
        })["prim_path"]
        assert _world_pos(state, absolute) == (5.0, 2.0, 3.0)

        above = _call(state, "create_light", {
            "light_type": "RectLight", "light_name": "Panel", "asset_prim_path": table,
            "translate_z": 0.5, "rotate_x": 90.0,
        })["prim_path"]
        assert _world_pos(state, above) == (5.0, 2.0, 1.0)
        stage = Usd.Stage.Open(str(state.stage_path))
        facing = UsdGeom.XformCache().GetLocalToWorldTransform(
            stage.GetPrimAtPath(above),
        ).TransformDir(Gf.Vec3d(0, 0, -1))
        assert [round(v, 4) + 0.0 for v in facing] == [0.0, 1.0, 0.0]


def test_bounds_offset_up_value_for_a_z_up_asset_in_a_y_up_scene():
    """translate_y is height in a Y-up scene even when the asset itself is Z-up."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _project(tmp, "Y")
        _plank(Path(tmp), "plank_z", "Z", size=(4.0, 0.5, 0.2))
        placed = _place(state, "plank_z", at=(0.0, 0.0, 5.0))
        light = _call(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Bulb",
            "asset_prim_path": placed, "translate_y": 0.5,
        })["prim_path"]
        assert _world_pos(state, light) == (0.0, 0.6, 5.0)


def test_place_asset_inside_uses_the_containers_frame_in_a_z_up_scene():
    """Nested absolute positions land where asked, and rotate_z turns on the floor."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _project(tmp, "Z")
        _make_asset(Path(tmp), "table", "Y")
        _plank(Path(tmp), "plank", "Y")
        table = _place(state, "table", at=(10.0, 0.0, 0.0))
        nested = _call(state, "place_asset_inside", {
            "asset": "plank", "asset_name": "Board", "container_prim_path": table,
            "group": "Props", "translate_x": 10.0, "translate_y": 1.0, "translate_z": 0.5,
            "rotate_z": 90.0,
        })
        assert nested["position"] == {"x": 10.0, "y": 1.0, "z": 0.5}
        assert _world_pos(state, nested["prim_path"]) == (10.0, 1.0, 0.5)
        assert _world_size(state, nested["prim_path"]) == (0.5, 4.0, 0.2)

        moved = _call(state, "move_asset", {"prim_path": nested["prim_path"], "translate_z": 1.5})
        assert moved["position"] == {"x": 10.0, "y": 1.0, "z": 1.5}
        assert moved["rotation"] == {"x": 0.0, "y": 0.0, "z": 90.0}
        assert _world_size(state, nested["prim_path"]) == (0.5, 4.0, 0.2)


def test_nested_assets_conform_to_their_container():
    """A Z-up asset nested in a Y-up centimeter container stands up at its real size,
    and moving it lands where asked."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _project(tmp, "Y")
        _plank(Path(tmp), "shelf", "Y", mpu=0.01, size=(200.0, 200.0, 200.0))
        _plank(Path(tmp), "post", "Z", size=(0.2, 0.2, 1.0))
        shelf = _place(state, "shelf", at=(10.0, 0.0, 0.0))
        post = _call(state, "place_asset_inside", {
            "asset": "post", "asset_name": "Post", "container_prim_path": shelf,
            "group": "Props", "translate_x": 10.5, "translate_y": 1.0, "translate_z": 0.0,
        })["prim_path"]
        assert _world_size(state, post) == (0.2, 1.0, 0.2)
        assert _world_pos(state, post) == (10.5, 1.0, 0.0)

        _call(state, "move_asset", {"prim_path": post, "translate_x": 10.2})
        assert _world_pos(state, post) == (10.2, 1.0, 0.0)


def test_open_project_reports_axes_and_units():
    """open_project and get_current_project say which axes and units positions use."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _project(tmp, "Z", mpu=0.01)
        for tool, params in (("open_project", {"name": "p"}), ("get_current_project", {})):
            data = _call(state, tool, params)
            assert data["up_axis"] == "Z"
            assert data["meters_per_unit"] == 0.01
