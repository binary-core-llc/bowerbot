# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for asset tools."""

import asyncio
import shutil
import tempfile
from pathlib import Path

from pxr import Gf
from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade

from tests import _helpers


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
    state, project = _helpers.make_state(tmp_path)
    asyncio.run(_helpers.exec_tool(state, "create_stage", {"filename": "test"}))
    return tmp_path, state, project


def _place(tmp_path, state, name="table", group="Furniture"):
    asset = _asset(tmp_path, name)
    r = asyncio.run(_helpers.exec_tool(state, "place_asset", {
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


def test_place_asset_relative_path_from_project():
    """Resolves a relative path against the project directory."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "cup")

        project_sub = project.path / "my_assets"
        project_sub.mkdir()
        shutil.copy2(asset, project_sub / "cup.usda")

        r = asyncio.run(_helpers.exec_tool(state, "place_asset", {
            "asset_file_path": "my_assets/cup.usda",
            "asset_name": "Cup", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert r.success, r.error


def test_place_asset_relative_path_from_library():
    """Resolves a relative path against the library directory."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "mug")

        lib_dir = tmp_path / "library"
        lib_dir.mkdir()
        shutil.copy2(asset, lib_dir / "mug.usda")
        state.library_dir = lib_dir

        r = asyncio.run(_helpers.exec_tool(state, "place_asset", {
            "asset_file_path": "mug.usda",
            "asset_name": "Mug", "group": "Products",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert r.success, r.error


def test_place_asset_relative_path_not_found():
    """Fails when relative path doesn't exist in project or library."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "place_asset", {
            "asset_file_path": "nonexistent/ghost.usda",
            "asset_name": "Ghost", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert not r.success


def test_add_asset_to_asset_relative_path():
    """add_asset_to_asset resolves relative paths too."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        parent = _place(tmp_path, state, "shelf", "Furniture")

        added = _asset(tmp_path, "book")
        project_sub = project.path / "imports"
        project_sub.mkdir()
        shutil.copy2(added, project_sub / "book.usda")

        r = asyncio.run(_helpers.exec_tool(state, "add_asset_to_asset", {
            "asset_file_path": "imports/book.usda",
            "asset_name": "Book",
            "parent_prim_path": parent.data["prim_path"],
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.3, "translate_z": 0.0,
        }))
        assert r.success, r.error


def test_place_asset_missing_stage():
    """Fails when no stage is open."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = _helpers.make_state(Path(tmp))
        asset = _asset(Path(tmp), "x")
        r = asyncio.run(_helpers.exec_tool(state, "place_asset", {
            "asset_file_path": str(asset), "asset_name": "X",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert not r.success


# ── add_asset_to_asset ──


def test_add_asset_to_asset():
    """Adds an asset to another asset; contents.usda is created."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        parent = _place(tmp_path, state, "building", "Architecture")

        added_src = _asset(tmp_path, "counter")
        r = asyncio.run(_helpers.exec_tool(state, "add_asset_to_asset", {
            "asset_file_path": str(added_src),
            "asset_name": "Counter",
            "parent_prim_path": parent.data["prim_path"],
            "group": "Furniture",
            "translate_x": 1.0, "translate_y": 0.0, "translate_z": 2.0,
        }))
        assert r.success, r.error

        parent_asset_dir = project.assets_dir / "building"
        assert (parent_asset_dir / "contents.usda").exists()


# ── place_layout ──


def test_place_layout_grid_pattern():
    """A grid pattern places nx*ny prims with the expected corner transforms."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "placements": [{
                "asset": str(asset),
                "group": "Building/Floor",
                "pattern": {
                    "type": "grid", "origin": [0, 0, 0],
                    "count": [3, 2], "spacing": [6, 6],
                },
            }],
        }))
        assert r.success, r.error
        assert r.data["placed"] == 6

        stage = Usd.Stage.Open(str(project.scene_path))
        floor = stage.GetPrimAtPath("/Scene/Building/Floor")
        assert floor.IsValid()
        children = list(floor.GetChildren())
        assert len(children) == 6
        corners = set()
        for child in children:
            t = UsdGeom.Xformable(child).GetLocalTransformation().ExtractTranslation()
            corners.add((round(t[0], 1), round(t[1], 1)))
        assert (0.0, 0.0) in corners
        assert (12.0, 6.0) in corners


def test_place_layout_linear_pattern_intakes_once():
    """A linear pattern places count prims and stages the asset folder once."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "barrel")
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "placements": [{
                "asset": str(asset),
                "group": "Props",
                "pattern": {
                    "type": "linear", "origin": [0, 0, 0],
                    "count": 4, "spacing": [2, 0, 0],
                },
            }],
        }))
        assert r.success, r.error
        assert r.data["placed"] == 4
        assert r.data["by_asset"] == {"barrel": 4}
        assert (project.assets_dir / "barrel").is_dir()


def test_place_layout_enumerated_transforms():
    """Enumerated transforms place one prim per listed transform."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "crate")
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "placements": [{
                "asset": str(asset),
                "group": "Props",
                "transforms": [
                    {"translate": [1, 0, 2]},
                    {"translate": [3, 0, 4], "rotate": [0, 90, 0]},
                ],
            }],
        }))
        assert r.success, r.error
        assert r.data["placed"] == 2
        stage = Usd.Stage.Open(str(project.scene_path))
        props = stage.GetPrimAtPath("/Scene/Props")
        assert len(list(props.GetChildren())) == 2


def test_place_layout_rejects_both_modes():
    """An entry with both 'transforms' and 'pattern' is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "thing")
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "placements": [{
                "asset": str(asset),
                "group": "Props",
                "transforms": [{"translate": [0, 0, 0]}],
                "pattern": {
                    "type": "grid", "origin": [0, 0, 0],
                    "count": [2, 2], "spacing": [1, 1],
                },
            }],
        }))
        assert not r.success
        assert "exactly one" in r.error


def test_place_layout_missing_stage():
    """Fails when no stage is open."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = _helpers.make_state(Path(tmp))
        asset = _asset(Path(tmp), "x")
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "placements": [{
                "asset": str(asset), "group": "Props",
                "transforms": [{"translate": [0, 0, 0]}],
            }],
        }))
        assert not r.success


def test_place_layout_aggregates_all_problems():
    """Every invalid entry and unresolvable asset is reported in one error."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "placements": [
                {"asset": str(asset), "group": "Props"},
                {"asset": "ghost.usda", "group": "Props",
                 "transforms": [{"translate": [0, 0, 0]}]},
            ],
        }))
        assert not r.success
        assert "placements[0]" in r.error
        assert "exactly one" in r.error
        assert "placements[1]" in r.error
        assert "not found" in r.error
        assert "searched" in r.error


def test_place_layout_validate_only():
    """validate_only reports the plan without staging or placing anything."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "validate_only": True,
            "placements": [{
                "asset": str(asset), "group": "Props",
                "pattern": {"type": "grid", "origin": [0, 0, 0],
                            "count": [2, 2], "spacing": [1, 1]},
            }],
        }))
        assert r.success, r.error
        assert r.data["valid"] is True
        assert r.data["placements"] == 4
        assert not state.stage.GetPrimAtPath("/Scene/Props").IsValid()
        assert not (project.assets_dir / "tile").exists()


def test_place_layout_rolls_back_on_failure(monkeypatch):
    """A failure during the batch write leaves the stage and counter untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        count_before = state.object_count

        def boom(stage):
            raise RuntimeError("disk full")

        monkeypatch.setattr(
            "bowerbot.utils.authoring.stage.save_stage", boom,
        )
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "placements": [{
                "asset": str(asset), "group": "Props",
                "pattern": {"type": "grid", "origin": [0, 0, 0],
                            "count": [2, 2], "spacing": [1, 1]},
            }],
        }))
        assert not r.success
        assert state.object_count == count_before
        assert not state.stage.GetPrimAtPath("/Scene/Props").IsValid()
        stage = Usd.Stage.Open(str(project.scene_path))
        assert not stage.GetPrimAtPath("/Scene/Props").IsValid()


def test_place_layout_rejects_folder_asset():
    """An entry pointing at a folder is refused with root-file guidance."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        folder = tmp_path / "tile"
        folder.mkdir()
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "placements": [{
                "asset": str(folder), "group": "Props",
                "transforms": [{"translate": [0, 0, 0]}],
            }],
        }))
        assert not r.success
        assert "root file" in r.error


def test_place_layout_rejects_3d_count_with_2d_spacing():
    """A grid with a 3-axis count and a 2-axis spacing is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "placements": [{
                "asset": str(asset), "group": "Props",
                "pattern": {"type": "grid", "origin": [0, 0, 0],
                            "count": [2, 2, 3], "spacing": [6, 6]},
            }],
        }))
        assert not r.success
        assert "3-axis 'spacing'" in r.error


def test_place_layout_rejects_invalid_prim_names():
    """Digit-leading group segments and names fail validation, not authoring."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "validate_only": True,
            "placements": [{
                "asset": str(asset), "group": "2ndFloor",
                "transforms": [{"translate": [0, 0, 0]}],
            }],
        }))
        assert not r.success
        assert "valid USD prim name" in r.error


def test_place_layout_rejects_oversized_layout():
    """A layout beyond the placement ceiling is refused without expansion."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "validate_only": True,
            "placements": [{
                "asset": str(asset), "group": "Props",
                "pattern": {"type": "grid", "origin": [0, 0, 0],
                            "count": [400, 400], "spacing": [1, 1]},
            }],
        }))
        assert not r.success
        assert "maximum per call" in r.error


def test_place_layout_same_file_two_spellings_no_collision():
    """The same asset via absolute and library-relative paths is one source."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        state.library_dir = tmp_path
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(_helpers.exec_tool(state, "place_layout", {
            "placements": [
                {"asset": str(asset), "group": "Props",
                 "transforms": [{"translate": [0, 0, 0]}]},
                {"asset": "tile.usda", "group": "Props",
                 "transforms": [{"translate": [2, 0, 0]}]},
            ],
        }))
        assert r.success, r.error
        assert r.data["placed"] == 2
        assert r.data["by_asset"] == {"tile": 2}


# ── list_project_assets ──


def test_list_project_assets_empty():
    """Empty project returns empty list."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = _helpers.make_state(Path(tmp))
        r = asyncio.run(_helpers.exec_tool(state, "list_project_assets"))
        assert r.success, r.error
        assert r.data["assets"] == []


def test_list_project_assets_after_placement():
    """Returns placed assets."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state, "sofa")

        r = asyncio.run(_helpers.exec_tool(state, "list_project_assets"))
        assert r.success, r.error
        assert r.data["total"] >= 1


# ── delete_project_asset ──


def test_delete_project_asset_unreferenced():
    """Deletes an asset folder after its scene reference is removed."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state, "rug", "Props")

        asyncio.run(_helpers.exec_tool(state, "remove_prim", {
            "prim_path": placed.data["prim_path"],
        }))

        folder = next(
            d for d in project.assets_dir.iterdir()
            if d.is_dir() and "rug" in d.name
        )
        r = asyncio.run(_helpers.exec_tool(state, "delete_project_asset", {
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
        r = asyncio.run(_helpers.exec_tool(state, "delete_project_asset", {
            "name": folder.name,
        }))
        assert not r.success


# ── cleanup_unused_contents ──


def test_cleanup_unused_contents_noop():
    """No-op when no stale contents exist."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state)

        r = asyncio.run(_helpers.exec_tool(state, "cleanup_unused_contents"))
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
        r = asyncio.run(_helpers.exec_tool(state, "freeze_asset", {
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

        r = asyncio.run(_helpers.exec_tool(state, "delete_project_texture", {
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

        r = asyncio.run(_helpers.exec_tool(state, "delete_project_texture", {
            "file_name": "marble.exr",
        }))
        assert not r.success
        assert tex.exists()


# ── place_asset: rotation + scale ──


def test_place_asset_with_rotation():
    """Placed asset respects rotate_up."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "chair")
        r = asyncio.run(_helpers.exec_tool(state, "place_asset", {
            "asset_file_path": str(asset), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
            "rotate_up": 90.0,
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


# ── add_asset_to_asset: additional scenarios ──


def test_add_asset_to_asset_visible_in_scene():
    """The added asset is visible in the composed scene stage."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        parent = _place(tmp_path, state, "shelf", "Furniture")

        added = _asset(tmp_path, "book")
        r = asyncio.run(_helpers.exec_tool(state, "add_asset_to_asset", {
            "asset_file_path": str(added),
            "asset_name": "Book",
            "parent_prim_path": parent.data["prim_path"],
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.3, "translate_z": 0.0,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.IsValid()


# ── assets added to another asset: units, up axis, moves ──


def _box_asset(directory: Path, name: str, *, mpu: float = 1.0, up: str = "Y") -> Path:
    """A cube one meter wide, authored in the given units and up axis."""
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, mpu)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z if up == "Z" else UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, f"/{name}/Mesh").GetSizeAttr().Set(1.0 / mpu)
    stage.Save()
    return path


def _add_to_parent(tmp_path, state, *, parent_mpu: float = 1.0, parent_up: str = "Y"):
    """Place a parent asset at (3, 0, 4) and add a Y-up meter box to it at (3.2, 0.5, 4.1)."""
    parent = asyncio.run(_helpers.exec_tool(state, "place_asset", {
        "asset_file_path": str(
            _box_asset(tmp_path, "shelf", mpu=parent_mpu, up=parent_up),
        ),
        "asset_name": "Shelf", "group": "Furniture",
        "translate_x": 3.0, "translate_y": 0.0, "translate_z": 4.0,
    }))
    assert parent.success, parent.error
    added = asyncio.run(_helpers.exec_tool(state, "add_asset_to_asset", {
        "asset_file_path": str(_box_asset(tmp_path, "book")),
        "asset_name": "Book",
        "parent_prim_path": parent.data["prim_path"],
        "group": "Props",
        "translate_x": 3.2, "translate_y": 0.5, "translate_z": 4.1,
    }))
    assert added.success, added.error
    return added


def _world_position(project, prim_path: str) -> tuple[float, float, float]:
    stage = Usd.Stage.Open(str(project.scene_path))
    matrix = UsdGeom.Xformable(stage.GetPrimAtPath(prim_path)).ComputeLocalToWorldTransform(
        Usd.TimeCode.Default(),
    )
    x, y, z = matrix.ExtractTranslation()
    return (round(x, 4), round(y, 4), round(z, 4))


def test_asset_added_to_a_centimeter_asset_lands_on_the_world_point():
    """A meter box added to a centimeter asset is where it was asked, at its real size."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        added = _add_to_parent(tmp_path, state, parent_mpu=0.01)

        assert _world_position(project, added.data["prim_path"]) == (3.2, 0.5, 4.1)
        assert added.data["position"] == {"x": 3.2, "y": 0.5, "z": 4.1}
        stage = Usd.Stage.Open(str(project.scene_path))
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
        box = cache.ComputeWorldBound(
            stage.GetPrimAtPath(added.data["prim_path"]),
        ).ComputeAlignedRange()
        assert all(abs(side - 1.0) < 1e-4 for side in box.GetSize())


def test_asset_added_to_a_z_up_asset_stands_upright():
    """A Y-up box added to a Z-up asset is turned to its parent's up axis."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        added = _add_to_parent(tmp_path, state, parent_up="Z")

        assert _world_position(project, added.data["prim_path"]) == (3.2, 0.5, 4.1)
        stage = Usd.Stage.Open(str(project.scene_path))
        asset = UsdGeom.Xformable(stage.GetPrimAtPath(added.data["prim_path"] + "/asset"))
        assert [(op.GetOpName(), op.Get()) for op in asset.GetOrderedXformOps()] == [
            ("xformOp:rotateX", 90.0),
        ]
        up = asset.ComputeLocalToWorldTransform(Usd.TimeCode.Default()).TransformDir(
            Gf.Vec3d(0, 1, 0),
        )
        assert Gf.IsClose(up, Gf.Vec3d(0, 1, 0), 1e-6)


def test_moving_an_added_asset_keeps_the_axes_left_out():
    """Moving an added asset goes to the world point given; axes left out keep their value."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        prim_path = _add_to_parent(tmp_path, state, parent_mpu=0.01).data["prim_path"]

        moved = asyncio.run(_helpers.exec_tool(state, "move_asset", {
            "prim_path": prim_path, "translate_x": 3.4,
        }))
        assert moved.success, moved.error
        assert _world_position(project, prim_path) == (3.4, 0.5, 4.1)
        assert moved.data["position"] == {"x": 3.4, "y": 0.5, "z": 4.1}

        turned = asyncio.run(_helpers.exec_tool(state, "move_asset", {
            "prim_path": prim_path, "rotate_up": 30.0,
        }))
        assert turned.success, turned.error
        assert _world_position(project, prim_path) == (3.4, 0.5, 4.1)


# ── packages whose root points to files of their own ──


def _model_file(path: Path, root: str, name: str, center, size) -> None:
    """A model file with one box *name* under */root*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, f"/{root}").GetPrim())
    cube = UsdGeom.Cube.Define(stage, f"/{root}/{name}")
    cube.GetSizeAttr().Set(1.0)
    cube.AddTranslateOp().Set(Gf.Vec3d(*center))
    cube.AddScaleOp().Set(Gf.Vec3f(*size))
    stage.Save()


def _package_root(path: Path, name: str, *, payloads=(), references=()) -> Path:
    """A package root whose prim composes *payloads* and *references* (path or (path, prim))."""
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    prim = UsdGeom.Xform.Define(stage, f"/{name}").GetPrim()
    stage.SetDefaultPrim(prim)
    for arc in payloads:
        prim.GetPayloads().AddPayload(*(arc if isinstance(arc, tuple) else (arc,)))
    for arc in references:
        prim.GetReferences().AddReference(*(arc if isinstance(arc, tuple) else (arc,)))
    stage.Save()
    return path


def _geometry(root_file: Path) -> dict[str, tuple]:
    """Each gprim of an asset, by its path under the root, with its bounds and bound material."""
    stage = Usd.Stage.Open(str(root_file))
    root = stage.GetDefaultPrim()
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    found = {}
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdGeom.Gprim):
            continue
        box = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        material = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]
        found[str(prim.GetPath().MakeRelativePath(root.GetPath()))] = (
            tuple(round(v, 4) for v in box.GetMin()),
            tuple(round(v, 4) for v in box.GetMax()),
            material.GetPrim().GetName() if material else None,
        )
    return found


def _packages(lib: Path) -> dict[str, Path]:
    """Four packages whose roots compose files BowerBot does not name itself."""
    box = ((0.0, 0.5, 0.0), (1.0, 1.0, 1.0))
    small = ((0.0, 0.25, 1.0), (0.5, 0.5, 0.5))

    _model_file(lib / "shelf" / "shelf_model.usda", "shelf", "Body", *box)
    look = Usd.Stage.CreateNew(str(lib / "shelf" / "look.usda"))
    look.SetDefaultPrim(look.OverridePrim("/shelf"))
    red = UsdShade.Material.Define(look, "/shelf/mtl/red")
    UsdShade.MaterialBindingAPI.Apply(look.OverridePrim("/shelf/Body")).Bind(red)
    look.Save()
    _model_file(lib / "desk" / "geo.usda", "desk", "Body", *box)
    _model_file(lib / "desk" / "drawers.usda", "desk", "Drawer", *small)
    _model_file(lib / "lamp" / "parts" / "body.usda", "lamp", "Body", *box)
    _model_file(lib / "stool" / "stool_model.usda", "Model", "Seat", *box)
    return {
        "shelf": _package_root(
            lib / "shelf" / "shelf.usda", "shelf",
            payloads=["./shelf_model.usda"], references=["./look.usda"],
        ),
        "desk": _package_root(
            lib / "desk" / "desk.usda", "desk",
            payloads=["./geo.usda"], references=["./drawers.usda"],
        ),
        "lamp": _package_root(
            lib / "lamp" / "lamp.usda", "lamp", references=["./parts/body.usda"],
        ),
        "stool": _package_root(
            lib / "stool" / "stool.usda", "stool",
            payloads=[("./stool_model.usda", "/Model")],
        ),
    }


def _refused(state, project, source: Path, folder_name: str) -> str:
    """Place *source*, expect a refusal that copied nothing, and return its message."""
    placed = asyncio.run(_helpers.exec_tool(state, "place_asset", {
        "asset_file_path": str(source), "asset_name": folder_name, "group": "Props",
        "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
    }))
    assert not placed.success, f"{folder_name} was placed"
    assert "cannot be used as it is" in placed.error
    assert not (project.assets_dir / folder_name).exists(), f"{folder_name} was copied"
    return placed.error


def test_a_folder_in_another_layout_is_refused():
    """A folder whose root points to files of its own is refused, and nothing is copied."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        lib = tmp_path / "lib"
        state.library_dir = lib
        expected = {
            "shelf": "it has no geo.usda",
            "desk": "desk.usda points to ./drawers.usda",
            "lamp": "it has USD files in sub-folders (parts/body.usda)",
            "stool": "it has no geo.usda",
        }
        for name, source in _packages(lib).items():
            assert expected[name] in _refused(state, project, source, name)


# ── the asset's box: its real geometry ──


def _exec(state, tool: str, params: dict):
    result = asyncio.run(_helpers.exec_tool(state, tool, params))
    assert result.success, result.error
    return result.data


def test_the_asset_box_ignores_its_lights_and_added_assets():
    """A light or an added asset high above an asset does not raise that asset's 'top'."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        parent = _exec(state, "place_asset", {
            "asset_file_path": str(_asset(tmp_path, "block")),  # a cube from -0.5 to 0.5
            "asset_name": "Block", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        })["prim_path"]
        _exec(state, "create_light", {
            "asset_prim_path": parent, "light_type": "SphereLight", "light_name": "High",
            "translate_y": 5.0,
        })
        _exec(state, "add_asset_to_asset", {
            "asset_file_path": str(_asset(tmp_path, "book")), "asset_name": "Book",
            "parent_prim_path": parent, "group": "Props", "position_mode": "bounds_offset",
            "translate_x": 0.0, "translate_y": 3.0, "translate_z": 0.0,
        })

        light = _exec(state, "create_light", {
            "asset_prim_path": parent, "light_type": "SphereLight", "light_name": "Bulb",
        })
        assert _world_position(project, light["prim_path"]) == (0.0, 1.0, 0.0)


def test_the_asset_box_follows_the_selected_geometry_variant():
    """A package that selects its short model is measured as that model, not as geo.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        lib = tmp_path / "lib"
        state.library_dir = lib
        _model_file(lib / "post" / "geo.usda", "post", "Pole", (0.0, 1.0, 0.0), (0.2, 2.0, 0.2))
        _model_file(lib / "post" / "geo_low.usda", "post", "Pole", (0.0, 0.5, 0.0), (0.2, 1.0, 0.2))
        root = Usd.Stage.CreateNew(str(lib / "post" / "post.usda"))
        UsdGeom.SetStageMetersPerUnit(root, 1.0)
        UsdGeom.SetStageUpAxis(root, UsdGeom.Tokens.y)
        prim = UsdGeom.Xform.Define(root, "/post").GetPrim()
        root.SetDefaultPrim(prim)
        lod = prim.GetVariantSets().AddVariantSet("lod")
        for variant, file_name in (("high", "./geo.usda"), ("low", "./geo_low.usda")):
            lod.AddVariant(variant)
            lod.SetVariantSelection(variant)
            with lod.GetVariantEditContext():
                prim.GetPayloads().AddPayload(file_name)
        lod.SetVariantSelection("low")
        root.Save()

        parent = _exec(state, "place_asset", {
            "asset_file_path": str(lib / "post" / "post.usda"), "asset_name": "Post",
            "group": "Props", "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        })["prim_path"]
        light = _exec(state, "create_light", {
            "asset_prim_path": parent, "light_type": "SphereLight", "light_name": "Bulb",
        })
        assert _world_position(project, light["prim_path"]) == (0.0, 1.5, 0.0)


# ── assets that need other files ──

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63f8cfc0f01f0005000201a5e0e4ec"
    "0000000049454e44ae426082",
)


def _add_texture(file: Path, prim_path: str, texture: str) -> None:
    """Bind a material that reads *texture* to *prim_path* in *file*."""
    stage = Usd.Stage.Open(str(file))
    root = stage.GetDefaultPrim().GetPath()
    material = UsdShade.Material.Define(stage, root.AppendPath("mtl/wood"))
    reader = UsdShade.Shader.Define(stage, material.GetPath().AppendChild("Diffuse"))
    reader.CreateIdAttr("UsdUVTexture")
    reader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture)
    UsdShade.MaterialBindingAPI.Apply(stage.OverridePrim(prim_path)).Bind(material)
    stage.Save()


def test_a_file_that_needs_other_files_is_refused():
    """A single file with a material, a texture, a reference or a sublayer is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        lib = tmp_path / "lib"
        state.library_dir = lib
        box = ((0.0, 0.5, 0.0), (1.0, 1.0, 1.0))
        (lib / "textures").mkdir(parents=True)
        (lib / "textures" / "wood.png").write_bytes(_PNG)

        _model_file(lib / "plank.usda", "plank", "Board", *box)
        _add_texture(lib / "plank.usda", "/plank/Board", "./textures/wood.png")

        _model_file(lib / "bin_model.usda", "bin", "Body", *box)
        _package_root(lib / "bin.usda", "bin", references=["./bin_model.usda"])

        _model_file(lib / "deck_geo.usda", "deck", "Board", *box)
        deck = Usd.Stage.CreateNew(str(lib / "deck.usda"))
        deck.SetDefaultPrim(deck.DefinePrim("/deck", "Xform"))
        deck.GetRootLayer().subLayerPaths.append("./deck_geo.usda")
        deck.Save()

        lit = Usd.Stage.Open(str(_asset(lib, "lit")))
        lit.DefinePrim(lit.GetDefaultPrim().GetPath().AppendChild("Bulb"), "SphereLight")
        lit.Save()

        expected = {
            "plank": "it holds materials",
            "bin": "it points to other files (./bin_model.usda)",
            "deck": "it uses sublayers",
            "lit": "it holds lights",
        }
        for name, reason in expected.items():
            assert reason in _refused(state, project, lib / f"{name}.usda", name)
        assert "it has file paths such as textures" in _refused(
            state, project, lib / "plank.usda", "plank",
        )


def test_a_folder_that_points_outside_itself_is_refused():
    """A folder that reads ``../shared/...`` is refused: everything it needs must be inside."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        lib = tmp_path / "lib"
        state.library_dir = lib
        (lib / "shared").mkdir(parents=True)
        (lib / "shared" / "wood.png").write_bytes(_PNG)
        _model_file(lib / "table" / "geo.usda", "table", "Top", (0.0, 0.75, 0.0), (0.6, 0.1, 0.6))
        mtl = Usd.Stage.CreateNew(str(lib / "table" / "mtl.usda"))
        mtl.SetDefaultPrim(mtl.OverridePrim("/table"))
        mtl.Save()
        _add_texture(lib / "table" / "mtl.usda", "/table/Top", "../shared/wood.png")
        source = _package_root(
            lib / "table" / "table.usda", "table",
            payloads=["./geo.usda"], references=["./mtl.usda"],
        )
        message = _refused(state, project, source, "table")
        assert "mtl.usda points outside the folder (../shared/wood.png)" in message


def test_an_accepted_folder_is_placed_with_its_own_materials():
    """A root, geo.usda and mtl.usda with a texture inside the folder: placed as it is."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        lib = tmp_path / "lib"
        state.library_dir = lib
        _model_file(lib / "table" / "geo.usda", "table", "Top", (0.0, 0.75, 0.0), (0.6, 0.1, 0.6))
        (lib / "table" / "textures").mkdir()
        (lib / "table" / "textures" / "wood.png").write_bytes(_PNG)
        mtl = Usd.Stage.CreateNew(str(lib / "table" / "mtl.usda"))
        mtl.SetDefaultPrim(mtl.OverridePrim("/table"))
        mtl.Save()
        _add_texture(lib / "table" / "mtl.usda", "/table/Top", "./textures/wood.png")
        source = _package_root(
            lib / "table" / "table.usda", "table",
            payloads=["./geo.usda"], references=["./mtl.usda"],
        )
        expected = _geometry(source)
        assert expected["Top"][2] == "wood"

        placed = asyncio.run(_helpers.exec_tool(state, "place_asset", {
            "asset_file_path": str(source), "asset_name": "Table", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert placed.success, placed.error
        asset_dir = project.assets_dir / "table"
        assert _geometry(asset_dir / "table.usda") == expected
        assert (asset_dir / "textures" / "wood.png").is_file()


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

        r = asyncio.run(_helpers.exec_tool(state, "freeze_asset", {
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

        r = asyncio.run(_helpers.exec_tool(state, "list_project_assets"))
        assert r.success, r.error
        asset = r.data["assets"][0]
        assert "name" in asset
