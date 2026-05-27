# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for stage: create, list, rename, remove, move, attrs, snapshots, grid."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom

from tests._helpers import exec_tool, make_state


def _asset(directory: Path, name: str) -> Path:
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, f"/{name}/Mesh").GetSizeAttr().Set(1.0)
    stage.Save()
    return path


def _setup(tmp):
    tmp_path = Path(tmp)
    state, project = make_state(tmp_path)
    asyncio.run(exec_tool(state, "create_stage", {"filename": "test"}))
    return tmp_path, state, project


def _place(tmp_path, state, name="table", group="Furniture"):
    asset = _asset(tmp_path, name)
    r = asyncio.run(exec_tool(state, "place_asset", {
        "asset_file_path": str(asset), "asset_name": name.title(),
        "group": group,
        "translate_x": 3.0, "translate_y": 0.0, "translate_z": 4.0,
    }))
    assert r.success, r.error
    return r


# ── create_stage ──


def test_create_stage():
    """Creates a valid USD file with defaultPrim, units, and upAxis."""
    with tempfile.TemporaryDirectory() as tmp:
        _, _, project = _setup(tmp)
        assert project.scene_path.exists()

        stage = Usd.Stage.Open(str(project.scene_path))
        assert stage.GetDefaultPrim().IsValid()
        assert UsdGeom.GetStageMetersPerUnit(stage) == 1.0
        assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y


def test_create_stage_idempotent():
    """Calling create_stage twice does not error."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "create_stage", {"filename": "test"}))
        assert r.success, r.error


# ── list_scene ──


def test_list_scene_empty():
    """Empty scene returns an empty list."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_scene"))
        assert r.success, r.error
        assert r.data["objects"] == []


def test_list_scene_with_assets():
    """Returns placed assets with prim_path and position."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state)

        r = asyncio.run(exec_tool(state, "list_scene"))
        assert r.success, r.error
        assert len(r.data["objects"]) >= 1
        obj = r.data["objects"][0]
        assert "prim_path" in obj
        assert "position" in obj


# ── rename_prim ──


def test_rename_prim():
    """Renames a placed asset; old path gone, new path exists."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        old_path = placed.data["prim_path"]
        new_name = "CoffeeTable"

        parent = str(Sdf.Path(old_path).GetParentPath())
        new_path = f"{parent}/{new_name}"
        r = asyncio.run(exec_tool(state, "rename_prim", {
            "old_path": old_path, "new_path": new_path,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        assert not stage.GetPrimAtPath(old_path).IsValid()
        assert stage.GetPrimAtPath(new_path).IsValid()


def test_rename_prim_invalid_path():
    """Fails for a nonexistent prim."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "rename_prim", {
            "old_path": "/Scene/Nope", "new_path": "/Scene/X",
        }))
        assert not r.success


# ── remove_prim ──


def test_remove_prim():
    """Removes a placed asset from the scene."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        prim_path = placed.data["prim_path"]

        r = asyncio.run(exec_tool(state, "remove_prim", {"prim_path": prim_path}))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        assert not stage.GetPrimAtPath(prim_path).IsValid()


def test_remove_prim_invalid_path():
    """Fails for a nonexistent prim."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "remove_prim", {
            "prim_path": "/Scene/Ghost",
        }))
        assert not r.success


# ── move_asset ──


def test_move_asset():
    """Repositions an asset without creating a duplicate."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        prim_path = placed.data["prim_path"]

        r = asyncio.run(exec_tool(state, "move_asset", {
            "prim_path": prim_path,
            "translate_x": 10.0, "translate_y": 0.0, "translate_z": 8.0,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        xf = UsdGeom.Xformable(stage.GetPrimAtPath(prim_path))
        t = xf.GetLocalTransformation().ExtractTranslation()
        assert abs(t[0] - 10.0) < 0.01
        assert abs(t[2] - 8.0) < 0.01


# ── list_prim_attributes ──


def test_list_prim_attributes():
    """Returns attributes of a placed asset's mesh."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        r = asyncio.run(exec_tool(state, "list_prim_attributes", {
            "prim_path": mesh_path,
        }))
        assert r.success, r.error
        names = {a["name"] for a in r.data["attributes"]}
        assert "size" in names


def test_list_prim_attributes_invalid_path():
    """Fails for a nonexistent prim."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_prim_attributes", {
            "prim_path": "/Scene/Nope",
        }))
        assert not r.success


# ── set_prim_attribute ──


def test_set_prim_attribute():
    """Sets an attribute value on a prim."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": mesh_path,
            "attribute_name": "size",
            "value": 2.5,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(mesh_path)
        assert abs(prim.GetAttribute("size").Get() - 2.5) < 1e-6


def test_set_prim_attribute_null_clears():
    """Setting value=null clears the authored opinion."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": mesh_path,
            "attribute_name": "size",
            "value": 5.0,
        }))

        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": mesh_path,
            "attribute_name": "size",
            "value": None,
        }))
        assert r.success, r.error

        scene_layer = Sdf.Layer.FindOrOpen(str(project.scene_path))
        spec = scene_layer.GetPrimAtPath(mesh_path)
        assert spec is None or "size" not in spec.attributes


# ── save/list/delete scene snapshots ──


def test_snapshot_lifecycle():
    """Save, list, and delete a snapshot."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _place(tmp_path, state)

        r = asyncio.run(exec_tool(state, "save_scene_snapshot", {"name": "v1"}))
        assert r.success, r.error
        assert (project.path / "v1.usda").exists()

        r = asyncio.run(exec_tool(state, "list_scene_snapshots"))
        assert r.success, r.error
        names = [s["name"] for s in r.data["snapshots"]]
        assert "v1" in names

        r = asyncio.run(exec_tool(state, "delete_scene_snapshot", {"name": "v1"}))
        assert r.success, r.error
        assert not (project.path / "v1.usda").exists()


def test_delete_snapshot_nonexistent():
    """Fails when deleting a snapshot that does not exist."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "delete_scene_snapshot", {"name": "nope"}))
        assert not r.success


# ── list_prim_children ──


def test_list_prim_children():
    """Returns mesh children with bounds and bindable flag."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        prim_path = placed.data["prim_path"]

        r = asyncio.run(exec_tool(state, "list_prim_children", {
            "prim_path": prim_path,
        }))
        assert r.success, r.error
        assert len(r.data["parts"]) >= 1
        part = r.data["parts"][0]
        assert part["is_bindable"] is True
        assert "bounds" in part


def test_list_prim_children_invalid_path():
    """Returns empty for a nonexistent prim."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_prim_children", {
            "prim_path": "/Scene/Nope",
        }))
        assert r.success
        assert r.data["parts"] == []


# ── compute_grid_layout ──


def test_compute_grid_layout():
    """Returns the correct number of positions with spacing."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp))
        r = asyncio.run(exec_tool(state, "compute_grid_layout", {
            "count": 6, "spacing": 2.5,
        }))
        assert r.success, r.error
        assert len(r.data["positions"]) == 6


def test_compute_grid_layout_single():
    """Single position returns one entry at origin."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp))
        r = asyncio.run(exec_tool(state, "compute_grid_layout", {
            "count": 1, "spacing": 1.0,
        }))
        assert r.success, r.error
        assert len(r.data["positions"]) == 1


# ── move_asset with rotation ──


def test_move_asset_with_rotation():
    """Repositions and rotates an asset."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        prim_path = placed.data["prim_path"]

        r = asyncio.run(exec_tool(state, "move_asset", {
            "prim_path": prim_path,
            "translate_x": 5.0, "translate_y": 0.0, "translate_z": 3.0,
            "rotate_y": 90.0,
        }))
        assert r.success, r.error
        assert r.data["position"]["x"] == 5.0


# ── set_prim_attribute: color3f vector ──


def test_set_prim_attribute_color_vec3():
    """Sets a Color3f attribute via a 3-list."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state)

        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "L",
            "attributes": {"inputs:intensity": 100.0},
        }))
        assert created.success, created.error

        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": created.data["prim_path"],
            "attribute_name": "inputs:color",
            "value": [0.1, 0.2, 0.9],
        }))
        assert r.success, r.error


# ── list_scene with mixed content ──


def test_list_scene_with_lights_and_assets():
    """Returns both assets and lights."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state)
        asyncio.run(exec_tool(state, "create_light", {
            "light_type": "DistantLight", "light_name": "Sun",
        }))

        r = asyncio.run(exec_tool(state, "list_scene"))
        assert r.success, r.error
        kinds = {obj.get("kind") for obj in r.data["objects"]}
        assert "asset" in kinds or "geometry" in kinds
        assert "light" in kinds


# ── remove_prim verifies cascade ──


def test_remove_prim_updates_object_count():
    """After removing an asset, list_scene reflects the change."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        p1 = _place(tmp_path, state, "a")
        _place(tmp_path, state, "b")

        before = asyncio.run(exec_tool(state, "list_scene"))
        count_before = before.data["object_count"]

        asyncio.run(exec_tool(state, "remove_prim", {
            "prim_path": p1.data["prim_path"],
        }))
        after = asyncio.run(exec_tool(state, "list_scene"))
        assert after.data["object_count"] == count_before - 1


# ── compute_grid_layout spacing ──


def test_compute_grid_layout_large():
    """Large grid (16 items) returns correct count."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp))
        r = asyncio.run(exec_tool(state, "compute_grid_layout", {
            "count": 16, "spacing": 2.0,
        }))
        assert r.success, r.error
        assert len(r.data["positions"]) == 16


# ── multiple snapshots ──


def test_multiple_snapshots():
    """Can save and list multiple snapshots."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state)

        for name in ("alpha", "beta", "gamma"):
            r = asyncio.run(exec_tool(
                state, "save_scene_snapshot", {"name": name},
            ))
            assert r.success, r.error

        r = asyncio.run(exec_tool(state, "list_scene_snapshots"))
        assert r.success, r.error
        names = {s["name"] for s in r.data["snapshots"]}
        assert names == {"alpha", "beta", "gamma"}
