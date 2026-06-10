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
from bowerbot.utils import stage_utils
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
    state = SceneState()
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
        assert stage_utils._asset_conform(z_scene, str(y_asset))[1] == 90.0
        assert stage_utils._asset_conform(y_scene, str(z_asset))[1] == -90.0
        assert stage_utils._asset_conform(y_scene, str(y_asset))[1] is None


def test_y_asset_stands_up_in_z_scene():
    """A Y-up asset placed in a Z-up project gets a +90 rotateX mapping +Y to +Z."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project = Project.create(tmp_path, "wh", up_axis=UpAxis.Z)
        state = SceneState(up_axis=UpAxis.Z)
        state.project = project
        state.stage_path = project.scene_path
        asyncio.run(exec_tool(state, "create_stage", {"filename": "scene"}))

        asset = _make_asset(tmp_path, "widget", "Y")
        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset), "asset_name": "Widget",
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
        state = SceneState(up_axis=UpAxis.Y)
        state.project = project
        state.stage_path = project.scene_path
        asyncio.run(exec_tool(state, "create_stage", {"filename": "scene"}))

        asset = _make_asset(tmp_path, "widget", "Y")
        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset), "asset_name": "Widget",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        asset_prim = stage.GetPrimAtPath(r.data["prim_path"] + "/asset")
        ops = UsdGeom.Xformable(asset_prim).GetOrderedXformOps()
        assert ops == []
