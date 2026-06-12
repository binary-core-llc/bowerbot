# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for cameras: list properties, create, update, remove."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Gf, Usd, UsdGeom

from bowerbot.config import UpAxis
from bowerbot.project import Project
from bowerbot.state import SceneState
from tests._helpers import exec_tool, make_state


def _setup(tmp):
    tmp_path = Path(tmp)
    state, project = make_state(tmp_path)
    asyncio.run(exec_tool(state, "create_stage", {"filename": "test"}))
    return tmp_path, state, project


def _setup_z_up(tmp):
    project = Project.create(Path(tmp), "test", up_axis=UpAxis.Z)
    state = SceneState()
    state.project = project
    state.stage_path = project.scene_path
    asyncio.run(exec_tool(state, "create_stage", {"filename": "test"}))
    return state, project


def _forward(scene_path, prim_path):
    stage = Usd.Stage.Open(str(scene_path))
    cache = UsdGeom.XformCache()
    m = cache.GetLocalToWorldTransform(stage.GetPrimAtPath(prim_path))
    return m.TransformDir(Gf.Vec3d(0, 0, -1)).GetNormalized()


# ── list_camera_properties ──


def test_list_camera_properties():
    """Returns Camera attributes including focalLength and projection tokens."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_camera_properties", {}))
        assert r.success, r.error
        by_name = {p["name"]: p for p in r.data["properties"]}
        assert "focalLength" in by_name
        assert "clippingRange" in by_name
        assert "perspective" in by_name["projection"]["allowed_tokens"]


# ── create_camera ──


def test_create_camera_defaults():
    """Creates a camera with translate, rotate, and a scaled clippingRange."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        r = asyncio.run(exec_tool(state, "create_camera", {
            "camera_name": "Hero_Cam",
            "translate_x": 1.0, "translate_y": 2.0, "translate_z": 3.0,
        }))
        assert r.success, r.error
        assert r.data["prim_path"].startswith("/Scene/Cameras/")

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.IsA(UsdGeom.Camera)
        t = prim.GetAttribute("xformOp:translate").Get()
        assert tuple(t) == (1.0, 2.0, 3.0)
        clipping = prim.GetAttribute("clippingRange").Get()
        assert abs(clipping[0] - 0.01) < 1e-6
        assert abs(clipping[1] - 100_000.0) < 1e-2
        assert not prim.GetAttribute("focalLength").HasAuthoredValue()


def test_create_camera_look_at_points_at_target():
    """look_at aims the camera's -Z axis at the target in a Y-up scene."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        eye, target = (10.0, 5.0, 10.0), (0.0, 1.0, 0.0)
        r = asyncio.run(exec_tool(state, "create_camera", {
            "camera_name": "Cam",
            "translate_x": eye[0], "translate_y": eye[1], "translate_z": eye[2],
            "look_at": list(target),
        }))
        assert r.success, r.error

        fwd = _forward(project.scene_path, r.data["prim_path"])
        expected = (Gf.Vec3d(*target) - Gf.Vec3d(*eye)).GetNormalized()
        assert (fwd - expected).GetLength() < 1e-5


def test_create_camera_look_at_z_up():
    """look_at is up-axis aware: the image stays upright in a Z-up scene."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project = _setup_z_up(tmp)
        eye, target = (10.0, -10.0, 5.0), (0.0, 0.0, 1.0)
        r = asyncio.run(exec_tool(state, "create_camera", {
            "camera_name": "Cam",
            "translate_x": eye[0], "translate_y": eye[1], "translate_z": eye[2],
            "look_at": list(target),
        }))
        assert r.success, r.error

        fwd = _forward(project.scene_path, r.data["prim_path"])
        expected = (Gf.Vec3d(*target) - Gf.Vec3d(*eye)).GetNormalized()
        assert (fwd - expected).GetLength() < 1e-5

        stage = Usd.Stage.Open(str(project.scene_path))
        cache = UsdGeom.XformCache()
        m = cache.GetLocalToWorldTransform(
            stage.GetPrimAtPath(r.data["prim_path"]),
        )
        up = m.TransformDir(Gf.Vec3d(0, 1, 0))
        assert Gf.Dot(up, Gf.Vec3d(0, 0, 1)) > 0


def test_create_camera_rejects_both_aims():
    """Passing look_at and rotate angles together is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "create_camera", {
            "camera_name": "Cam",
            "look_at": [0, 0, 0],
            "rotate_x": -30.0,
        }))
        assert not r.success
        assert "exactly one" in r.error


def test_create_camera_attributes():
    """Camera attributes author by exact name through the coercion path."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        r = asyncio.run(exec_tool(state, "create_camera", {
            "camera_name": "Cam",
            "attributes": {"focalLength": 35, "fStop": 2.8},
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert abs(prim.GetAttribute("focalLength").Get() - 35.0) < 1e-6
        assert abs(prim.GetAttribute("fStop").Get() - 2.8) < 1e-6


def test_create_camera_unknown_attribute_refused():
    """An unknown attribute name is refused and nothing is authored."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "create_camera", {
            "camera_name": "Cam",
            "attributes": {"focalLenght": 35},
        }))
        assert not r.success
        assert "list_camera_properties" in r.error
        assert not state.stage.GetPrimAtPath("/Scene/Cameras/Cam").IsValid()


# ── update_camera ──


def test_update_camera_look_at_from_current_position():
    """look_at without new translate re-aims from the camera's position."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        created = asyncio.run(exec_tool(state, "create_camera", {
            "camera_name": "Cam",
            "translate_x": 0.0, "translate_y": 2.0, "translate_z": 10.0,
        }))
        path = created.data["prim_path"]

        r = asyncio.run(exec_tool(state, "update_camera", {
            "prim_path": path,
            "look_at": [5.0, 0.0, 0.0],
        }))
        assert r.success, r.error

        fwd = _forward(project.scene_path, path)
        expected = (
            Gf.Vec3d(5, 0, 0) - Gf.Vec3d(0, 2, 10)
        ).GetNormalized()
        assert (fwd - expected).GetLength() < 1e-5


def test_update_camera_translate():
    """New translate values are authored on the existing op."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        created = asyncio.run(exec_tool(state, "create_camera", {
            "camera_name": "Cam",
        }))
        path = created.data["prim_path"]

        r = asyncio.run(exec_tool(state, "update_camera", {
            "prim_path": path,
            "translate_x": 4.0, "translate_y": 5.0, "translate_z": 6.0,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        t = stage.GetPrimAtPath(path).GetAttribute("xformOp:translate").Get()
        assert tuple(t) == (4.0, 5.0, 6.0)


def test_update_camera_rejects_non_camera():
    """Updating a non-camera prim is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
        }))
        r = asyncio.run(exec_tool(state, "update_camera", {
            "prim_path": created.data["prim_path"],
            "translate_x": 1.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert not r.success
        assert "not a Camera" in r.error


# ── remove_camera ──


def test_remove_camera():
    """Removes the camera and reports suspect variant sets."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        created = asyncio.run(exec_tool(state, "create_camera", {
            "camera_name": "Cam",
        }))
        path = created.data["prim_path"]

        r = asyncio.run(exec_tool(state, "remove_camera", {"prim_path": path}))
        assert r.success, r.error
        assert "suspect_variant_sets" in r.data

        stage = Usd.Stage.Open(str(project.scene_path))
        assert not stage.GetPrimAtPath(path).IsValid()


def test_remove_camera_rejects_non_camera():
    """Removing a non-camera prim via remove_camera is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
        }))
        r = asyncio.run(exec_tool(state, "remove_camera", {
            "prim_path": created.data["prim_path"],
        }))
        assert not r.success
        assert "not a Camera" in r.error


# ── list_scene interplay ──


def test_list_scene_shows_camera():
    """list_scene reports cameras with kind, projection, and focal length."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        created = asyncio.run(exec_tool(state, "create_camera", {
            "camera_name": "Cam",
            "attributes": {"focalLength": 35},
        }))
        r = asyncio.run(exec_tool(state, "list_scene", {}))
        assert r.success, r.error
        cameras = [o for o in r.data["objects"] if o.get("kind") == "camera"]
        assert len(cameras) == 1
        assert cameras[0]["prim_path"] == created.data["prim_path"]
        assert cameras[0]["focal_length"] == 35.0
