# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for asset tools."""

import asyncio
import json
import shutil
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


def test_place_asset_relative_path_from_project():
    """Resolves a relative path against the project directory."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "cup")

        project_sub = project.path / "my_assets"
        project_sub.mkdir()
        shutil.copy2(asset, project_sub / "cup.usda")

        r = asyncio.run(exec_tool(state, "place_asset", {
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

        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": "mug.usda",
            "asset_name": "Mug", "group": "Products",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert r.success, r.error


def test_place_asset_relative_path_not_found():
    """Fails when relative path doesn't exist in project or library."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": "nonexistent/ghost.usda",
            "asset_name": "Ghost", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert not r.success


def test_place_asset_inside_relative_path():
    """place_asset_inside resolves relative paths too."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        container = _place(tmp_path, state, "shelf", "Furniture")

        nested = _asset(tmp_path, "book")
        project_sub = project.path / "imports"
        project_sub.mkdir()
        shutil.copy2(nested, project_sub / "book.usda")

        r = asyncio.run(exec_tool(state, "place_asset_inside", {
            "asset_file_path": "imports/book.usda",
            "asset_name": "Book",
            "container_prim_path": container.data["prim_path"],
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.3, "translate_z": 0.0,
        }))
        assert r.success, r.error


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


# ── place_layout ──


def test_place_layout_grid_pattern():
    """A grid pattern places nx*ny prims with the expected corner transforms."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(exec_tool(state, "place_layout", {
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
        r = asyncio.run(exec_tool(state, "place_layout", {
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
        r = asyncio.run(exec_tool(state, "place_layout", {
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
        r = asyncio.run(exec_tool(state, "place_layout", {
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
        state, _ = make_state(Path(tmp))
        asset = _asset(Path(tmp), "x")
        r = asyncio.run(exec_tool(state, "place_layout", {
            "placements": [{
                "asset": str(asset), "group": "Props",
                "transforms": [{"translate": [0, 0, 0]}],
            }],
        }))
        assert not r.success


def test_place_layout_from_layout_file():
    """A BOM'd layout file places its entries, resolving assets against its own dir."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _asset(tmp_path, "tile")
        layout = tmp_path / "layout.json"
        layout.write_text(json.dumps({
            "version": 1,
            "placements": [
                {"asset": "tile.usda", "group": "Building/Floor",
                 "pattern": {"type": "grid", "origin": [0, 0, 0],
                             "count": [2, 2], "spacing": [6, 6]}},
                {"asset": "tile.usda", "group": "Props", "name": "Spare",
                 "transforms": [{"translate": [1, 0, 1]}]},
            ],
        }), encoding="utf-8-sig")

        r = asyncio.run(exec_tool(state, "place_layout", {
            "layout_file": str(layout),
        }))
        assert r.success, r.error
        assert r.data["placed"] == 5
        assert r.data["sources"]["tile"] == str(tmp_path / "tile.usda")


def test_place_layout_file_version_rejected():
    """A layout file with an unsupported version is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _asset(tmp_path, "tile")
        layout = tmp_path / "layout.json"
        layout.write_text(json.dumps({
            "version": 2,
            "placements": [{"asset": "tile.usda", "group": "Props",
                            "transforms": [{"translate": [0, 0, 0]}]}],
        }), encoding="utf-8")

        r = asyncio.run(exec_tool(state, "place_layout", {
            "layout_file": str(layout),
        }))
        assert not r.success
        assert "version" in r.error


def test_place_layout_aggregates_all_problems():
    """Every invalid entry and unresolvable asset is reported in one error."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(exec_tool(state, "place_layout", {
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
        r = asyncio.run(exec_tool(state, "place_layout", {
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
            "bowerbot.services.asset_service.stage_utils.save_stage", boom,
        )
        r = asyncio.run(exec_tool(state, "place_layout", {
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
        r = asyncio.run(exec_tool(state, "place_layout", {
            "placements": [{
                "asset": str(folder), "group": "Props",
                "transforms": [{"translate": [0, 0, 0]}],
            }],
        }))
        assert not r.success
        assert "root file" in r.error


def test_place_layout_rejects_non_usd_asset_at_lint():
    """A non-USD file fails layout validation instead of failing at intake."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        notes = tmp_path / "notes.txt"
        notes.write_text("not usd")
        r = asyncio.run(exec_tool(state, "place_layout", {
            "placements": [{
                "asset": str(notes), "group": "Props",
                "transforms": [{"translate": [0, 0, 0]}],
            }],
            "validate_only": True,
        }))
        assert not r.success
        assert "not a USD file" in r.error


def _place_path(state, path):
    return asyncio.run(exec_tool(state, "place_asset", {
        "asset_file_path": str(path), "asset_name": "Lamp", "group": "Props",
        "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
    }))


def test_place_asset_folder_names_its_root_file():
    """A folder is refused naming its root file, leaves nothing behind, and the retry works."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        folder = tmp_path / "lamp"
        folder.mkdir()
        root = _asset(folder, "lamp")

        r = _place_path(state, folder)
        assert not r.success
        assert str(root) in r.error
        assert not (project.assets_dir / "lamp").exists()

        r = _place_path(state, root)
        assert r.success, r.error


def test_place_asset_refuses_non_usd_and_missing_files():
    """Inputs that are not an existing USD file are refused before intake creates anything."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        notes = tmp_path / "notes.txt"
        notes.write_text("not usd")

        r = _place_path(state, notes)
        assert not r.success
        assert "not a USD file" in r.error

        r = _place_path(state, tmp_path / "missing.usda")
        assert not r.success
        assert "not found" in r.error

        assert not (project.assets_dir / "notes").exists()
        assert not (project.assets_dir / "missing").exists()


def test_place_asset_corrupt_usda_leaves_nothing():
    """A file USD cannot parse gets USD's own message and no assets/ entry."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        broken = tmp_path / "broken.usda"
        broken.write_text("#usda 1.0\nthis is not valid usd (\n")

        r = _place_path(state, broken)
        assert not r.success
        assert "Could not import broken.usda" in r.error
        assert "parse error" in r.error
        assert not (project.assets_dir / "broken").exists()


def test_place_asset_corrupt_usdz_leaves_nothing():
    """A .usdz USD cannot read is refused before it is copied into assets/."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        junk = tmp_path / "junk.usdz"
        junk.write_bytes(b"not a zip")

        r = _place_path(state, junk)
        assert not r.success
        assert "Could not import junk.usdz" in r.error
        assert not (project.assets_dir / "junk.usdz").exists()


def test_failed_placement_keeps_an_existing_asset():
    """A failed re-placement never deletes the asset folder the scene already uses."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        source = _asset(tmp_path, "chair")
        assert _place_path(state, source).success

        geo = project.assets_dir / "chair" / "geo.usda"
        layer = Sdf.Layer.FindOrOpen(str(geo))
        layer.GetPrimAtPath("/chair").typeName = "Scope"
        layer.Save()

        r = _place_path(state, source)
        assert not r.success
        assert (project.assets_dir / "chair" / "chair.usda").exists()
        assert geo.exists()


def test_failed_compliance_on_a_new_asset_leaves_nothing():
    """A new asset that fails the ASWF check is removed again, as before."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        path = tmp_path / "multi.usda"
        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.Xform.Define(stage, "/a")
        UsdGeom.Xform.Define(stage, "/b")
        stage.Save()

        r = _place_path(state, path)
        assert not r.success
        assert "multiple root prims" in r.error
        assert not (project.assets_dir / "multi").exists()


def test_place_layout_rejects_3d_count_with_2d_spacing():
    """A grid with a 3-axis count and a 2-axis spacing is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(exec_tool(state, "place_layout", {
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
        r = asyncio.run(exec_tool(state, "place_layout", {
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
        r = asyncio.run(exec_tool(state, "place_layout", {
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
    """The same asset via absolute and layout-relative paths is one source."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        layout = tmp_path / "layout.json"
        layout.write_text(json.dumps({
            "version": 1,
            "placements": [
                {"asset": str(asset), "group": "Props",
                 "transforms": [{"translate": [0, 0, 0]}]},
                {"asset": "tile.usda", "group": "Props",
                 "transforms": [{"translate": [2, 0, 0]}]},
            ],
        }), encoding="utf-8")
        r = asyncio.run(exec_tool(state, "place_layout", {
            "layout_file": str(layout),
        }))
        assert r.success, r.error
        assert r.data["placed"] == 2
        assert r.data["by_asset"] == {"tile": 2}


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


def _listed_assets(state):
    r = asyncio.run(exec_tool(state, "list_project_assets"))
    assert r.success, r.error
    return r.data, {a["name"]: a for a in r.data["assets"]}


def test_unselected_scene_variants_count_as_used():
    """Every model in a scene variant set is in the scene, not only the selected one."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        slot = _place(tmp_path, state, "crate").data["prim_path"]
        added = asyncio.run(exec_tool(state, "add_scene_model_selection_variant", {
            "prim_path": slot, "variant_set": "model", "variant_name": "chest",
            "asset_file_path": str(_asset(tmp_path, "chest")),
        }))
        assert added.success, added.error
        selected = asyncio.run(exec_tool(state, "select_scene_variant", {
            "prim_path": slot, "variant_set": "model", "variant_name": "chest",
        }))
        assert selected.success, selected.error

        data, assets = _listed_assets(state)
        assert assets["crate"]["in_scene"]
        assert assets["chest"]["in_scene"]
        assert data["unused_count"] == 0


def test_name_prefixes_do_not_count_as_references():
    """An unused 'rock' is not kept alive by a referenced 'rock_big'."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state, "rock_big", "Props")
        rock = _place(tmp_path, state, "rock", "Props").data["prim_path"]
        asyncio.run(exec_tool(state, "remove_prim", {"prim_path": rock}))

        data, assets = _listed_assets(state)
        assert not assets["rock"]["in_scene"]
        assert assets["rock"]["referenced_by"] == []
        assert assets["rock_big"]["in_scene"]
        assert data["unused_count"] == 1

        r = asyncio.run(exec_tool(state, "delete_project_asset", {"name": "rock"}))
        assert r.success, r.error


def test_asset_kept_only_by_a_snapshot():
    """A snapshot keeps an asset referenced: not in the scene, but not deletable either."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        ghost = _place(tmp_path, state, "ghost", "Props").data["prim_path"]
        asyncio.run(exec_tool(state, "save_scene_snapshot", {"name": "keep"}))
        asyncio.run(exec_tool(state, "remove_prim", {"prim_path": ghost}))

        data, assets = _listed_assets(state)
        assert not assets["ghost"]["in_scene"]
        assert assets["ghost"]["referenced_by"] == ["keep.usda"]
        assert data["unused_count"] == 0

        r = asyncio.run(exec_tool(state, "delete_project_asset", {"name": "ghost"}))
        assert not r.success
        assert "keep.usda" in r.error


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


def test_delete_project_asset_never_leaves_the_assets_folder():
    """'..', a nested path or an absolute path is refused and nothing is deleted."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep")

        for name in ("..", "sub/../..", str(outside)):
            r = asyncio.run(exec_tool(state, "delete_project_asset", {"name": name}))
            assert not r.success, name
            assert "is not an entry of" in r.error
        assert project.scene_path.exists()
        assert (outside / "keep.txt").exists()


def test_delete_project_texture_never_leaves_the_textures_folder():
    """A texture name that points outside textures/ is refused and nothing is deleted."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        (project.path / "textures").mkdir(exist_ok=True)
        outside = tmp_path / "keep.txt"
        outside.write_text("keep")

        for name in ("../scene.usda", str(outside)):
            r = asyncio.run(exec_tool(state, "delete_project_texture", {"file_name": name}))
            assert not r.success, name
        assert project.scene_path.exists()
        assert outside.exists()


def test_freeze_asset_refuses_a_folder_outside_the_project():
    """freeze_asset never rewrites geo.usda outside the project's assets folder."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        library_asset = tmp_path / "library_chair"
        library_asset.mkdir()
        geo = _asset(library_asset, "geo")
        before = geo.read_bytes()

        r = asyncio.run(exec_tool(state, "freeze_asset", {"name": str(library_asset)}))
        assert not r.success
        assert geo.read_bytes() == before


def test_delete_project_asset_removes_a_link_not_its_target():
    """A symlinked entry is unlinked; the folder it points to is left alone."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        target = tmp_path / "library_chair"
        target.mkdir()
        (target / "keep.txt").write_text("keep")
        project.assets_dir.mkdir(exist_ok=True)
        (project.assets_dir / "linked").symlink_to(target, target_is_directory=True)

        r = asyncio.run(exec_tool(state, "delete_project_asset", {"name": "linked"}))
        assert r.success, r.error
        assert not (project.assets_dir / "linked").exists()
        assert (target / "keep.txt").exists()


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


# ── intake keeps everything the source composes ──


def _gprims(project, prim_path):
    stage = Usd.Stage.Open(str(project.scene_path))
    return sorted(
        p.GetName() for p in Usd.PrimRange(stage.GetPrimAtPath(prim_path))
        if p.IsA(UsdGeom.Gprim)
    )


def _library_folder(lib: Path, name: str, arcs, *, geo_ext="usda") -> Path:
    """A library folder <name>/<name>.usda whose root composes geo.<ext> through *arcs*."""
    folder = lib / name
    folder.mkdir(parents=True)
    geo = _asset(folder, "geo_source")
    Sdf.Layer.FindOrOpen(str(geo)).Export(str(folder / f"geo.{geo_ext}"))
    geo.unlink()
    rig = Usd.Stage.CreateNew(str(folder / "rig.usda"))
    rig.SetDefaultPrim(rig.DefinePrim("/geo_source", "Xform"))
    UsdGeom.Cube.Define(rig, "/geo_source/Handle")
    rig.Save()
    root = Usd.Stage.CreateNew(str(folder / f"{name}.usda"))
    UsdGeom.SetStageMetersPerUnit(root, 1.0)
    UsdGeom.SetStageUpAxis(root, UsdGeom.Tokens.y)
    prim = root.DefinePrim("/geo_source", "Xform")
    root.SetDefaultPrim(prim)
    arcs(prim)
    root.Save()
    return folder / f"{name}.usda"


def _place_from(state, path, name, x=0.0):
    return asyncio.run(exec_tool(state, "place_asset", {
        "asset_file_path": str(path), "asset_name": name, "group": "Props",
        "translate_x": x, "translate_y": 0.0, "translate_z": 0.0,
    }))


def test_folder_with_usdc_geometry_keeps_its_geometry():
    """A root that payloads geo.usdc is placed with its geometry, not hollow."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        state.library_dir = tmp_path / "lib"
        root = _library_folder(
            state.library_dir, "vase", lambda p: p.GetPayloads().AddPayload("./geo.usdc"),
            geo_ext="usdc",
        )
        r = _place_from(state, root, "Vase")
        assert r.success, r.error
        assert _gprims(project, r.data["prim_path"]) == ["Mesh"]


def test_folder_root_arcs_survive_intake_and_side_layers():
    """An extra reference on the root survives intake, BowerBot side layers, and their removal."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        state.library_dir = tmp_path / "lib"
        root = _library_folder(state.library_dir, "vase", lambda p: (
            p.GetPayloads().AddPayload("./geo.usda"),
            p.GetReferences().AddReference("./rig.usda"),
        ))
        r = _place_from(state, root, "Vase")
        assert r.success, r.error
        vase = r.data["prim_path"]
        assert _gprims(project, vase) == ["Handle", "Mesh"]

        for tool, params in (
            ("create_material", {"prim_path": f"{vase}/asset/Mesh", "material_name": "red"}),
            ("create_light", {"light_type": "SphereLight", "light_name": "Bulb",
                              "asset_prim_path": vase}),
            ("remove_light", {"prim_path": f"{vase}/asset/lgt/Bulb"}),
            ("remove_material", {"prim_path": f"{vase}/asset/Mesh"}),
            ("cleanup_unused_materials", {"asset_prim_path": vase}),
        ):
            done = asyncio.run(exec_tool(state, tool, params))
            assert done.success, (tool, done.error)
            assert _gprims(project, vase) == ["Handle", "Mesh"], tool


def test_non_canonical_and_binary_roots_intake_whole():
    """root.usd (text or binary) next to geo.usd is placed with its geometry."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        lib = state.library_dir = tmp_path / "lib"
        for fmt in ("usda", "usdc"):
            folder = lib / f"pack_{fmt}"
            folder.mkdir(parents=True)
            geo = _asset(folder, "shelf")
            geo.rename(folder / "geo.usd")
            layer = Sdf.Layer.CreateAnonymous(".usda")
            layer.ImportFromString(
                '#usda 1.0\n(\n defaultPrim = "shelf"\n metersPerUnit = 1\n upAxis = "Y"\n)\n'
                'def Xform "shelf" (\n prepend references = @./geo.usd@\n)\n{\n}\n',
            )
            layer.Export(str(folder / "root.usd"), args={"format": fmt})
            r = _place_from(state, folder / "root.usd", f"Shelf_{fmt}")
            assert r.success, (fmt, r.error)
            assert _gprims(project, r.data["prim_path"]) == ["Mesh"], fmt


def test_dependencies_are_localized():
    """A library folder's texture outside it, and a loose file's sibling layer, are copied in."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        lib = state.library_dir = tmp_path / "lib"
        (lib / "shared").mkdir(parents=True)
        (lib / "shared" / "grain.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        _asset(lib, "part")
        package = lib / "crate"
        package.mkdir()
        stage = Usd.Stage.CreateNew(str(package / "crate.usda"))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        stage.SetDefaultPrim(stage.DefinePrim("/crate", "Xform"))
        UsdGeom.Cube.Define(stage, "/crate/Body")
        shader = UsdShade.Shader.Define(stage, "/crate/Looks/tex")
        shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set("../shared/grain.png")
        stage.Save()
        stage = Usd.Stage.CreateNew(str(lib / "assembly.usda"))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        stage.SetDefaultPrim(stage.DefinePrim("/assembly", "Xform"))
        UsdGeom.Cube.Define(stage, "/assembly/Body")
        stage.DefinePrim("/assembly/Knob").GetReferences().AddReference("./part.usda")
        stage.Save()

        crate = _place_from(state, package / "crate.usda", "Crate")
        assert crate.success, crate.error
        assembly = _place_from(state, lib / "assembly.usda", "Assembly", x=2.0)
        assert assembly.success, assembly.error
        assert _gprims(project, assembly.data["prim_path"]) == ["Body", "Mesh"]
        assets_dir = project.path / "assets"
        assert (assets_dir / "crate" / "textures" / "grain.png").exists()
        assert (assets_dir / "assembly" / "part.usda").exists()
        from pxr import UsdUtils
        _, _, unresolved = UsdUtils.ComputeAllDependencies(str(project.scene_path))
        assert unresolved == []


def test_loose_file_keeps_units_in_geo_layer():
    """geo.usda carries the source's metersPerUnit and upAxis."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        stage = Usd.Stage.CreateNew(str(tmp_path / "lamp.usda"))
        UsdGeom.SetStageMetersPerUnit(stage, 0.01)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        stage.SetDefaultPrim(stage.DefinePrim("/lamp", "Xform"))
        UsdGeom.Cube.Define(stage, "/lamp/Mesh")
        stage.Save()
        assert _place_from(state, tmp_path / "lamp.usda", "Lamp").success

        geo = Usd.Stage.Open(str(project.path / "assets" / "lamp" / "geo.usda"))
        assert UsdGeom.GetStageMetersPerUnit(geo) == 0.01
        assert UsdGeom.GetStageUpAxis(geo) == UsdGeom.Tokens.z


def test_loose_file_refusals_leave_nothing_behind():
    """Geometry outside the defaultPrim, or a missing dependency, is refused cleanly."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        outside = Usd.Stage.CreateNew(str(tmp_path / "outside.usda"))
        outside.SetDefaultPrim(outside.DefinePrim("/outside", "Xform"))
        UsdGeom.Cube.Define(outside, "/Geometry/Box")
        outside.Save()
        missing = Usd.Stage.CreateNew(str(tmp_path / "missing.usda"))
        missing.SetDefaultPrim(missing.DefinePrim("/missing", "Xform"))
        UsdGeom.Cube.Define(missing, "/missing/Body")
        missing.DefinePrim("/missing/Ghost").GetReferences().AddReference("./nowhere.usda")
        missing.Save()

        r = _place_from(state, tmp_path / "outside.usda", "Outside")
        assert not r.success
        assert "outside its defaultPrim" in r.error
        r = _place_from(state, tmp_path / "missing.usda", "Missing")
        assert not r.success
        assert "did not resolve" in r.error
        assert not any((project.path / "assets").iterdir())


def test_fix_root_prim_keeps_layer_units():
    """Wrapping a Mesh root in an Xform keeps the file's units."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        stage = Usd.Stage.CreateNew(str(tmp_path / "blob.usda"))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        mesh = UsdGeom.Mesh.Define(stage, "/blob")
        mesh.GetPointsAttr().Set([Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 0, 0), Gf.Vec3f(0, 1, 0)])
        mesh.GetFaceVertexCountsAttr().Set([3])
        mesh.GetFaceVertexIndicesAttr().Set([0, 1, 2])
        stage.SetDefaultPrim(mesh.GetPrim())
        stage.Save()
        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(tmp_path / "blob.usda"), "asset_name": "Blob",
            "group": "Props", "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
            "fix_root_prim": True,
        }))
        assert r.success, r.error
        geo = Sdf.Layer.FindOrOpen(str(project.path / "assets" / "blob" / "geo.usda"))
        assert geo.pseudoRoot.GetInfo("metersPerUnit") == 1.0


# ── source files come only from the asset library ──


def test_file_inputs_outside_the_library_are_refused():
    """Assets, layouts, scatter assets, materials and textures outside the library are refused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        state.library_dir = tmp_path / "lib"
        state.library_dir.mkdir()
        outside = tmp_path / "downloads"
        outside.mkdir()
        chair = _asset(outside, "chair")
        (outside / "sky.exr").write_bytes(b"v/1\x01")
        materials = Usd.Stage.CreateNew(str(outside / "paint.usda"))
        UsdShade.Material.Define(materials, "/Materials/red")
        materials.Save()
        layout = outside / "layout.json"
        layout.write_text(json.dumps({"version": 1, "placements": [
            {"asset": str(chair), "group": "Props", "transforms": [{"translate": [0, 0, 0]}]},
        ]}))
        table = _asset(state.library_dir, "table")
        placed = _place_from(state, table, "Table")
        assert placed.success, placed.error

        calls = (
            ("place_asset", {"asset_file_path": str(chair), "asset_name": "Chair", "group": "Props",
                             "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0}),
            ("place_layout", {"placements": [{"asset": str(chair), "group": "Props",
                                              "transforms": [{"translate": [0, 0, 0]}]}]}),
            ("place_layout", {"layout_file": str(layout)}),
            ("scatter_on_surface", {"name": "pile", "assets": [{"asset": str(chair)}],
                                    "surfaces": [placed.data["prim_path"]], "count": 3}),
            ("bind_material", {"prim_path": f"{placed.data['prim_path']}/asset/Mesh",
                               "material_file": str(outside / "paint.usda")}),
            ("create_light", {"light_type": "DomeLight", "light_name": "Sky",
                              "texture": str(outside / "sky.exr")}),
            ("create_light", {"light_type": "DomeLight", "light_name": "Sky",
                              "texture": str(state.library_dir / "missing.exr")}),
        )
        for tool, params in calls:
            r = asyncio.run(exec_tool(state, tool, params))
            assert not r.success, tool
            assert "asset library" in r.error, (tool, r.error)
        assert sorted(p.name for p in (project.path / "assets").iterdir()) == ["table"]
        assert not (project.path / "textures").exists()


def test_library_and_project_files_are_accepted():
    """A library path (absolute or relative) and a file already in the project both place."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        state.library_dir = tmp_path / "lib"
        state.library_dir.mkdir()
        _asset(state.library_dir, "table")
        library_path = str(state.library_dir / "table.usda")
        for path in (library_path, "table.usda", "assets/table/table.usda"):
            r = asyncio.run(exec_tool(state, "place_asset", {
                "asset_file_path": path, "asset_name": "Table", "group": "Props",
                "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
            }))
            assert r.success, (path, r.error)
