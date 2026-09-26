# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for materials: create, bind, remove, list, cleanup."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdShade

from tests._helpers import exec_tool, library_state, make_state


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
        "asset": asset.stem, "asset_name": name.title(),
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


def test_create_material_cleans_the_name():
    """A material name with spaces becomes a valid prim name."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        r = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": f"{placed.data['prim_path']}/asset/Mesh",
            "material_name": "Red Paint",
        }))
        assert r.success, r.error
        assert r.data["material"].endswith("/Red_Paint")


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


# ── clean authoring: no residue, no writes on refusal, textures travel ──


def _two_part_asset(directory: Path, name: str) -> Path:
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    stage.SetDefaultPrim(stage.DefinePrim(f"/{name}", "Xform"))
    for part in ("Top", "Leg"):
        UsdGeom.Cube.Define(stage, f"/{name}/{part}")
    stage.Save()
    return path


def _textured_material(library: Path, name: str, texture: str | None) -> None:
    """A library material folder whose texture input names ./maps/<texture>."""
    folder = library / name
    (folder / "maps").mkdir(parents=True)
    if texture:
        (folder / "maps" / texture).write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode() * 8)
    stage = Usd.Stage.CreateNew(str(folder / f"{name}.usda"))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    stage.SetDefaultPrim(stage.DefinePrim("/Materials", "Scope"))
    material = UsdShade.Material.Define(stage, f"/Materials/{name}")
    tex = UsdShade.Shader.Define(stage, f"/Materials/{name}/tex")
    tex.CreateIdAttr("UsdUVTexture")
    tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set("./maps/wood.png")
    surface = UsdShade.Shader.Define(stage, f"/Materials/{name}/surface")
    surface.CreateIdAttr("UsdPreviewSurface")
    material.CreateSurfaceOutput().ConnectToSource(surface.ConnectableAPI(), "surface")
    stage.Save()


def test_remove_material_leaves_no_binding_behind():
    """Removing one part's material drops its binding and API; the other stays, and it validates."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _two_part_asset(tmp_path, "desk")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": "desk", "asset_name": "Desk", "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        })).data["prim_path"]
        for part, material in (("Top", "oak"), ("Leg", "steel")):
            r = asyncio.run(exec_tool(state, "create_material", {
                "prim_path": f"{placed}/asset/{part}", "material_name": material,
            }))
            assert r.success, r.error

        r = asyncio.run(exec_tool(state, "remove_material", {"prim_path": f"{placed}/asset/Top"}))
        assert r.success, r.error
        mtl = Sdf.Layer.FindOrOpen(str(project.assets_dir / "desk" / "mtl.usda"))
        mtl.Reload()
        assert mtl.GetPrimAtPath("/desk/Top") is None
        assert mtl.GetPrimAtPath("/desk/mtl/steel") is not None
        validation = asyncio.run(exec_tool(state, "validate_scene"))
        assert validation.data["error_count"] == 0, validation.data["issues"]

        r = asyncio.run(exec_tool(state, "remove_material", {"prim_path": f"{placed}/asset/Top"}))
        assert not r.success


def test_material_tools_refuse_a_missing_prim_and_write_nothing():
    """A part that does not exist is refused before mtl.usda is created."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state).data["prim_path"]
        _textured_material(tmp_path, "woodmat", "wood.png")
        for tool, params in (
            ("create_material", {"prim_path": f"{placed}/asset/Nope", "material_name": "x"}),
            ("bind_material", {"prim_path": f"{placed}/asset/Nope", "material_asset": "woodmat"}),
            ("remove_material", {"prim_path": f"{placed}/asset/Nope"}),
        ):
            r = asyncio.run(exec_tool(state, tool, params))
            assert not r.success, tool
            assert "Prim not found" in r.error
        assert not (project.assets_dir / "chair" / "mtl.usda").exists()


def test_bind_material_brings_the_material_textures_into_the_asset():
    """A library material's textures are copied into the asset's maps/ and resolve;
    a material whose texture is missing is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state).data["prim_path"]
        _textured_material(tmp_path, "woodmat", "wood.png")
        _textured_material(tmp_path, "brokenmat", None)

        r = asyncio.run(exec_tool(state, "bind_material", {
            "prim_path": f"{placed}/asset/Mesh", "material_asset": "brokenmat",
        }))
        assert not r.success
        assert not (project.assets_dir / "chair" / "mtl.usda").exists()

        r = asyncio.run(exec_tool(state, "bind_material", {
            "prim_path": f"{placed}/asset/Mesh", "material_asset": "woodmat",
        }))
        assert r.success, r.error
        mtl = project.assets_dir / "chair" / "mtl.usda"
        layer = Sdf.Layer.FindOrOpen(str(mtl))
        value = layer.GetAttributeAtPath("/chair/mtl/woodmat/tex.inputs:file").default
        assert value.path == "./maps/wood.png"
        assert Path(layer.ComputeAbsolutePath(value.path)).is_file()


def test_removing_a_textured_material_lists_its_texture():
    """The copied texture is reported, then deleted on request; the asset folder stays."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        assets_dir = state.require_project().assets_dir
        table = asyncio.run(exec_tool(state, "place_asset", {
            "asset": "table", "asset_name": "Table", "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        })).data["prim_path"]
        bound = asyncio.run(exec_tool(state, "bind_material", {
            "prim_path": f"{table}/asset/Top", "material_asset": "woodmat",
            "material_prim_path": "/Materials/wood",
        }))
        assert bound.success, bound.error

        removed = asyncio.run(exec_tool(state, "remove_material", {
            "prim_path": f"{table}/asset/Top",
        }))
        assert removed.success, removed.error
        assert removed.data["unused_files"] == ["assets/table/maps/wood.png"]

        deleted = asyncio.run(exec_tool(state, "delete_project_texture", {
            "file_name": "assets/table/maps/wood.png",
        }))
        assert deleted.success, deleted.error
        assert not (assets_dir / "table" / "maps").exists()
        assert (assets_dir / "table" / "table.usda").exists()
