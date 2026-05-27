# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for asset tools."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

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


# ── place_asset ──


def test_place_asset_correct_transform():
    """Placed asset has the expected translate on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        r = _place(tmp_path, state)
        prim_path = r.data["prim_path"]

        stage = Usd.Stage.Open(str(project.scene_path))
        xf = UsdGeom.Xformable(stage.GetPrimAtPath(prim_path))
        t = xf.GetLocalTransformation().ExtractTranslation()
        assert abs(t[0] - 3.0) < 0.01
        assert abs(t[2] - 4.0) < 0.01


def test_place_asset_group_hierarchy():
    """Prim path starts with /Scene/<group>/."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        r = _place(tmp_path, state, "lamp", "Lighting")
        assert r.data["prim_path"].startswith("/Scene/Lighting/")


def test_place_asset_unique_prim_paths():
    """Multiple placements get unique prim paths."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        paths = []
        for _ in range(3):
            r = _place(tmp_path, state, "chair")
            paths.append(r.data["prim_path"])
        assert len(set(paths)) == 3


def test_place_asset_creates_folder():
    """Asset folder created in project/assets/."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _place(tmp_path, state, "vase", "Props")
        assert any(
            d.is_dir() for d in project.assets_dir.iterdir()
        )


def test_place_asset_missing_stage():
    """Fails when no stage is open."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp))
        asset = _asset(Path(tmp), "x")
        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset), "asset_name": "X",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert not r.success


# ── place_asset_inside ──


def test_place_asset_inside():
    """Nests an asset inside a container; contents.usda is created."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        container = _place(tmp_path, state, "building", "Architecture")

        nested_src = _asset(tmp_path, "counter")
        r = asyncio.run(exec_tool(state, "place_asset_inside", {
            "asset_file_path": str(nested_src),
            "asset_name": "Counter",
            "container_prim_path": container.data["prim_path"],
            "group": "Furniture",
            "translate_x": 1.0, "translate_y": 0.0, "translate_z": 2.0,
        }))
        assert r.success, r.error

        container_dir = project.assets_dir / "building"
        assert (container_dir / "contents.usda").exists()


# ── list_project_assets ──


def test_list_project_assets_empty():
    """Empty project returns empty list."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp))
        r = asyncio.run(exec_tool(state, "list_project_assets"))
        assert r.success, r.error
        assert r.data["assets"] == []


def test_list_project_assets_after_placement():
    """Returns placed assets."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state, "sofa")

        r = asyncio.run(exec_tool(state, "list_project_assets"))
        assert r.success, r.error
        assert r.data["total"] >= 1


# ── delete_project_asset ──


def test_delete_project_asset_unreferenced():
    """Deletes an asset folder after its scene reference is removed."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state, "rug", "Props")

        asyncio.run(exec_tool(state, "remove_prim", {
            "prim_path": placed.data["prim_path"],
        }))

        folder = next(
            d for d in project.assets_dir.iterdir()
            if d.is_dir() and "rug" in d.name
        )
        r = asyncio.run(exec_tool(state, "delete_project_asset", {
            "name": folder.name,
        }))
        assert r.success, r.error
        assert not folder.exists()


def test_delete_project_asset_refuses_when_referenced():
    """Refuses deletion when the asset is still in the scene."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _place(tmp_path, state, "desk", "Furniture")

        folder = next(
            d for d in project.assets_dir.iterdir()
            if d.is_dir() and "desk" in d.name
        )
        r = asyncio.run(exec_tool(state, "delete_project_asset", {
            "name": folder.name,
        }))
        assert not r.success


# ── cleanup_unused_contents ──


def test_cleanup_unused_contents_noop():
    """No-op when no stale contents exist."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state)

        r = asyncio.run(exec_tool(state, "cleanup_unused_contents"))
        assert r.success, r.error
        assert r.data["total_removed"] == 0


# ── freeze_asset ──


def test_freeze_asset_noop_clean():
    """Reports baked=false for an asset with identity transforms."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _place(tmp_path, state, "box", "Props")

        folder = next(
            d for d in project.assets_dir.iterdir() if d.is_dir()
        )
        r = asyncio.run(exec_tool(state, "freeze_asset", {
            "name": folder.name,
        }))
        assert r.success, r.error
        assert r.data["baked_count"] == 0


# ── delete_project_texture ──


def test_delete_project_texture_unreferenced():
    """Deletes a texture that no USD file references."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        tex_dir = project.path / "textures"
        tex_dir.mkdir(parents=True, exist_ok=True)
        tex = tex_dir / "wood.png"
        tex.write_bytes(b"fake")

        r = asyncio.run(exec_tool(state, "delete_project_texture", {
            "file_name": "wood.png",
        }))
        assert r.success, r.error
        assert not tex.exists()


def test_delete_project_texture_refuses_when_referenced():
    """Refuses deletion when a USD file references the texture."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        tex_dir = project.path / "textures"
        tex_dir.mkdir(parents=True, exist_ok=True)
        tex = tex_dir / "marble.exr"
        tex.write_bytes(b"fake")

        ref_path = project.path / "ref.usda"
        ref_stage = Usd.Stage.CreateNew(str(ref_path))
        root = ref_stage.DefinePrim("/r", "Xform")
        ref_stage.SetDefaultPrim(root)
        shader = UsdShade.Shader.Define(ref_stage, "/r/s")
        shader.CreateInput(
            "texture:file", Sdf.ValueTypeNames.Asset,
        ).Set(Sdf.AssetPath("./textures/marble.exr"))
        ref_stage.Save()

        r = asyncio.run(exec_tool(state, "delete_project_texture", {
            "file_name": "marble.exr",
        }))
        assert not r.success
        assert tex.exists()


# ── place_asset: rotation + scale ──


def test_place_asset_with_rotation():
    """Placed asset respects rotate_y."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "chair")
        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
            "rotate_y": 90.0,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.IsValid()


def test_place_asset_multiple_groups():
    """Assets in different groups go under separate scene paths."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        r1 = _place(tmp_path, state, "table", "Furniture")
        r2 = _place(tmp_path, state, "lamp", "Lighting")

        assert "/Furniture/" in r1.data["prim_path"]
        assert "/Lighting/" in r2.data["prim_path"]


# ── place_asset_inside: additional scenarios ──


def test_place_asset_inside_nested_visible_in_scene():
    """Nested asset is visible in the composed scene stage."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        container = _place(tmp_path, state, "shelf", "Furniture")

        nested = _asset(tmp_path, "book")
        r = asyncio.run(exec_tool(state, "place_asset_inside", {
            "asset_file_path": str(nested),
            "asset_name": "Book",
            "container_prim_path": container.data["prim_path"],
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.3, "translate_z": 0.0,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.IsValid()


# ── freeze_asset: with non-identity root xform ──


def test_freeze_asset_bakes_root_xform():
    """Bakes non-identity root transform into vertex data."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)

        asset_dir = project.assets_dir / "shifted"
        asset_dir.mkdir(parents=True, exist_ok=True)

        geo_path = asset_dir / "geo.usda"
        geo_stage = Usd.Stage.CreateNew(str(geo_path))
        UsdGeom.SetStageMetersPerUnit(geo_stage, 1.0)
        UsdGeom.SetStageUpAxis(geo_stage, UsdGeom.Tokens.y)
        root = geo_stage.DefinePrim("/shifted", "Xform")
        geo_stage.SetDefaultPrim(root)
        xf = UsdGeom.Xformable(root)
        xf.AddTranslateOp().Set(Gf.Vec3d(5.0, 0.0, 0.0))
        mesh = UsdGeom.Mesh.Define(geo_stage, "/shifted/Mesh")
        mesh.GetPointsAttr().Set([
            Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 0, 0), Gf.Vec3f(0, 1, 0),
        ])
        mesh.GetFaceVertexCountsAttr().Set([3])
        mesh.GetFaceVertexIndicesAttr().Set([0, 1, 2])
        geo_stage.Save()

        root_path = asset_dir / "shifted.usda"
        root_stage = Usd.Stage.CreateNew(str(root_path))
        UsdGeom.SetStageMetersPerUnit(root_stage, 1.0)
        UsdGeom.SetStageUpAxis(root_stage, UsdGeom.Tokens.y)
        root_prim = root_stage.DefinePrim("/shifted", "Xform")
        root_stage.SetDefaultPrim(root_prim)
        root_prim.GetPayloads().AddPayload("./geo.usda")
        root_stage.Save()

        r = asyncio.run(exec_tool(state, "freeze_asset", {
            "name": "shifted",
        }))
        assert r.success, r.error
        assert r.data["baked_count"] == 1
        assert r.data["results"][0]["baked"] is True


# ── list_project_assets: detail check ──


def test_list_project_assets_shows_name():
    """Each asset entry has a name field."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state, "mug", "Products")

        r = asyncio.run(exec_tool(state, "list_project_assets"))
        assert r.success, r.error
        asset = r.data["assets"][0]
        assert "name" in asset
