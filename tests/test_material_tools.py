# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for materials: create, bind, remove, list, cleanup."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom, UsdShade

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


def _place(tmp_path, state, name="chair"):
    asset = _asset(tmp_path, name)
    r = asyncio.run(exec_tool(state, "place_asset", {
        "asset_file_path": str(asset), "asset_name": name.title(),
        "group": "Furniture",
        "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
    }))
    assert r.success, r.error
    return r


# ── create_material ──


def test_create_material():
    """Creates a procedural material and binds it to a mesh."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        r = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path,
            "material_name": "matte_black",
            "base_color_r": 0.05,
            "base_color_g": 0.05,
            "base_color_b": 0.05,
            "roughness": 0.9,
        }))
        assert r.success, r.error

        mtl_path = project.assets_dir / "chair" / "mtl.usda"
        assert mtl_path.exists()


def test_create_material_metallic():
    """Creates a metallic material with metalness=1."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        r = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path,
            "material_name": "gold",
            "base_color_r": 1.0, "base_color_g": 0.84, "base_color_b": 0.0,
            "metalness": 1.0, "roughness": 0.3,
        }))
        assert r.success, r.error


def test_create_material_missing_stage():
    """Fails when no stage is open."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp))
        r = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": "/Scene/Furniture/Chair/asset/Mesh",
            "material_name": "x",
        }))
        assert not r.success


def test_create_material_shared_refuses():
    """Refuses when asset is referenced by 2+ placements."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        p1 = _place(tmp_path, state, "stool")
        _place(tmp_path, state, "stool")

        mesh_path = f"{p1.data['prim_path']}/asset/Mesh"
        r = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path, "material_name": "red",
        }))
        assert not r.success


def test_create_material_shared_with_confirm():
    """Succeeds with confirm_shared_modification=true."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        p1 = _place(tmp_path, state, "stool")
        _place(tmp_path, state, "stool")

        mesh_path = f"{p1.data['prim_path']}/asset/Mesh"
        r = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path, "material_name": "red",
            "confirm_shared_modification": True,
        }))
        assert r.success, r.error


# ── remove_material ──


def test_remove_material():
    """Clears a material binding."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path, "material_name": "temp",
        }))
        r = asyncio.run(exec_tool(state, "remove_material", {
            "prim_path": mesh_path,
        }))
        assert r.success, r.error


# ── list_materials ──


def test_list_materials_empty():
    """Empty scene returns empty materials list."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_materials"))
        assert r.success, r.error


def test_list_materials_after_create():
    """Returns created material."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path, "material_name": "wood",
        }))
        r = asyncio.run(exec_tool(state, "list_materials"))
        assert r.success, r.error
        assert len(r.data["materials"]) >= 1


# ── cleanup_unused_materials ──


def test_cleanup_unused_materials_noop():
    """No-op when all materials are bound."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path, "material_name": "clean",
        }))
        r = asyncio.run(exec_tool(state, "cleanup_unused_materials"))
        assert r.success, r.error


def test_cleanup_removes_orphan_after_unbind():
    """Removes an orphan material after its binding is cleared."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path, "material_name": "orphan",
        }))
        asyncio.run(exec_tool(state, "remove_material", {
            "prim_path": mesh_path,
        }))

        r = asyncio.run(exec_tool(state, "cleanup_unused_materials"))
        assert r.success, r.error


# ── create_material: with opacity ──


def test_create_material_with_opacity():
    """Creates a translucent material."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        r = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path,
            "material_name": "glass",
            "base_color_r": 0.9, "base_color_g": 0.95,
            "base_color_b": 1.0,
            "opacity": 0.3, "roughness": 0.0,
        }))
        assert r.success, r.error


# ── create_material: two different materials on same asset ──


def test_create_two_materials_same_asset():
    """Two materials can coexist in mtl.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        r1 = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path, "material_name": "paint_a",
        }))
        r2 = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path, "material_name": "paint_b",
        }))
        assert r1.success, r1.error
        assert r2.success, r2.error


# ── remove_material: verify binding cleared on disk ──


def test_remove_material_clears_binding_on_disk():
    """After remove_material, the prim has no material binding."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path, "material_name": "temp",
        }))
        asyncio.run(exec_tool(state, "remove_material", {
            "prim_path": mesh_path,
        }))

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(mesh_path)
        mat, _ = UsdShade.MaterialBindingAPI(
            prim,
        ).ComputeBoundMaterial()
        assert not mat


# ── list_materials: verify structure ──


def test_list_materials_has_prim_path():
    """Each material entry has a prim_path and name."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path, "material_name": "walnut",
        }))
        r = asyncio.run(exec_tool(state, "list_materials"))
        assert r.success, r.error
        mat = r.data["materials"][0]
        assert "material_path" in mat
        assert "material_name" in mat
