# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for asset tools."""

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from pxr import Gf, Kind, Sdf, Usd, UsdGeom, UsdShade, UsdUtils

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


def _place(tmp_path, state, name="table", group="Furniture"):
    asset = _asset(tmp_path, name)
    r = asyncio.run(exec_tool(state, "place_asset", {
        "asset": asset.stem, "asset_name": name.title(),
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


def test_place_asset_by_project_asset_name():
    """A name already in the project's assets/ places that copy, even once the library lacks it."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "cup")
        first = _place_from(state, "cup", "Cup")
        assert first.success, first.error
        asset.unlink()

        again = _place_from(state, "cup", "Cup", x=2.0)
        assert again.success, again.error
        assert (project.assets_dir / "cup" / "cup.usda").exists()


def test_place_asset_by_library_name():
    """A library asset is placed by the name search_assets reports."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        lib_dir = state.library_dir = tmp_path / "library"
        lib_dir.mkdir()
        _asset(lib_dir, "mug")
        found = asyncio.run(exec_tool(state, "search_assets", {"query": "mug"}))
        name = found.data["results"][0]["name"]
        assert found.data["results"][0]["location"] == "mug.usda"

        r = _place_from(state, name, "Mug")
        assert r.success, r.error


def test_place_asset_unknown_name_is_refused():
    """An unknown name is refused and points at search_assets (with a close match)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _asset(tmp_path, "ghost")
        r = _place_from(state, "ghots", "Ghost")
        assert not r.success
        assert "search_assets" in r.error
        assert "ghost" in r.error


def test_place_asset_inside_by_name():
    """place_asset_inside takes the nested asset's name too."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        container = _place(tmp_path, state, "shelf", "Furniture")
        _asset(tmp_path, "book")

        r = asyncio.run(exec_tool(state, "place_asset_inside", {
            "asset": "book",
            "asset_name": "Book",
            "container_prim_path": container.data["prim_path"],
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.3, "translate_z": 0.0,
        }))
        assert r.success, r.error


def test_place_asset_cleans_the_name():
    """Names with spaces or a leading digit are cleaned, top level and inside a
    container, instead of failing in USD."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _asset(tmp_path, "shelf")
        _asset(tmp_path, "book")
        container = asyncio.run(exec_tool(state, "place_asset", {
            "asset": "shelf", "asset_name": "2nd Shelf", "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert container.success, container.error
        assert container.data["prim_path"].startswith("/Scene/Furniture/_2nd_Shelf_")

        nested = asyncio.run(exec_tool(state, "place_asset_inside", {
            "asset": "book", "asset_name": "Red Book",
            "container_prim_path": container.data["prim_path"],
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.3, "translate_z": 0.0,
        }))
        assert nested.success, nested.error
        assert "/asset/contents/Props/Red_Book_" in nested.data["prim_path"]
        stage = Usd.Stage.Open(str(project.scene_path))
        assert stage.GetPrimAtPath(nested.data["prim_path"]).IsValid()


def test_place_asset_missing_stage():
    """Fails when no stage is open."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp))
        asset = _asset(Path(tmp), "x")
        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "X",
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
            "asset": nested_src.stem,
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
                "asset": asset.stem,
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
                "asset": asset.stem,
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
                "asset": asset.stem,
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
                "asset": asset.stem,
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
                "asset": asset.stem, "group": "Props",
                "transforms": [{"translate": [0, 0, 0]}],
            }],
        }))
        assert not r.success


def test_place_layout_from_layout_file():
    """A BOM'd layout file saved in the project places its entries by name or location."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _asset(tmp_path, "tile")
        layout = project.path / "layouts" / "floor.json"
        layout.parent.mkdir()
        layout.write_text(json.dumps({
            "version": 1,
            "placements": [
                {"asset": "tile", "group": "Building/Floor",
                 "pattern": {"type": "grid", "origin": [0, 0, 0],
                             "count": [2, 2], "spacing": [6, 6]}},
                {"asset": "tile.usda", "group": "Props", "name": "Spare",
                 "transforms": [{"translate": [1, 0, 1]}]},
            ],
        }), encoding="utf-8-sig")

        r = asyncio.run(exec_tool(state, "place_layout", {
            "layout_file": "layouts/floor.json",
        }))
        assert r.success, r.error
        assert r.data["placed"] == 5
        assert r.data["sources"]["tile"] == "tile.usda"


def test_place_layout_file_version_rejected():
    """A layout file with an unsupported version is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _asset(tmp_path, "tile")
        layout = project.path / "layout.json"
        layout.write_text(json.dumps({
            "version": 2,
            "placements": [{"asset": "tile.usda", "group": "Props",
                            "transforms": [{"translate": [0, 0, 0]}]}],
        }), encoding="utf-8")

        r = asyncio.run(exec_tool(state, "place_layout", {
            "layout_file": "layout.json",
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
                {"asset": asset.stem, "group": "Props"},
                {"asset": "ghost.usda", "group": "Props",
                 "transforms": [{"translate": [0, 0, 0]}]},
            ],
        }))
        assert not r.success
        assert "placements[0]" in r.error
        assert "exactly one" in r.error
        assert "placements[1]" in r.error
        assert "No asset named 'ghost.usda'" in r.error
        assert "search_assets" in r.error


def test_place_layout_validate_only():
    """validate_only reports the plan without staging or placing anything."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(exec_tool(state, "place_layout", {
            "validate_only": True,
            "placements": [{
                "asset": asset.stem, "group": "Props",
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
                "asset": asset.stem, "group": "Props",
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
    """An entry naming a folder with no USD asset in it is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        folder = tmp_path / "tile"
        folder.mkdir()
        r = asyncio.run(exec_tool(state, "place_layout", {
            "placements": [{
                "asset": folder.name, "group": "Props",
                "transforms": [{"translate": [0, 0, 0]}],
            }],
        }))
        assert not r.success
        assert "No asset named 'tile'" in r.error


def test_place_layout_rejects_non_usd_asset_at_lint():
    """A non-USD file is not an asset: layout validation refuses it before intake."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        notes = tmp_path / "notes.txt"
        notes.write_text("not usd")
        r = asyncio.run(exec_tool(state, "place_layout", {
            "placements": [{
                "asset": notes.name, "group": "Props",
                "transforms": [{"translate": [0, 0, 0]}],
            }],
            "validate_only": True,
        }))
        assert not r.success
        assert "No asset named 'notes.txt'" in r.error


def _place_named(state, name):
    return asyncio.run(exec_tool(state, "place_asset", {
        "asset": name, "asset_name": "Lamp", "group": "Props",
        "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
    }))


def test_place_asset_library_folder_by_name():
    """A library folder asset is placed by its folder name; a file path is refused, naming it."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        folder = tmp_path / "lamp"
        folder.mkdir()
        root = _asset(folder, "lamp")

        r = _place_named(state, str(root))
        assert not r.success
        assert "Use 'lamp'" in r.error
        assert not (project.assets_dir / "lamp").exists()

        r = _place_named(state, "lamp")
        assert r.success, r.error
        assert (project.assets_dir / "lamp" / "lamp.usda").exists()


def test_place_asset_refuses_non_usd_and_missing_files():
    """Inputs that are not an existing USD file are refused before intake creates anything."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        notes = tmp_path / "notes.txt"
        notes.write_text("not usd")

        r = _place_named(state, "notes")
        assert not r.success
        assert "No asset named 'notes'" in r.error

        r = _place_named(state, "missing")
        assert not r.success
        assert "No asset named 'missing'" in r.error

        assert not (project.assets_dir / "notes").exists()
        assert not (project.assets_dir / "missing").exists()


def test_place_asset_corrupt_usda_leaves_nothing():
    """A file USD cannot parse gets USD's own message and no assets/ entry."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        broken = tmp_path / "broken.usda"
        broken.write_text("#usda 1.0\nthis is not valid usd (\n")

        r = _place_named(state, "broken")
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

        r = _place_named(state, "junk")
        assert not r.success
        assert "Could not import junk.usdz" in r.error
        assert not (project.assets_dir / "junk.usdz").exists()


def test_failed_placement_keeps_an_existing_asset():
    """A failed re-placement never deletes the asset folder the scene already uses."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _asset(tmp_path, "chair")
        assert _place_named(state, "chair").success

        geo = project.assets_dir / "chair" / "geo.usda"
        layer = Sdf.Layer.FindOrOpen(str(geo))
        layer.GetPrimAtPath("/chair").typeName = "Scope"
        layer.Save()

        r = _place_named(state, "chair")
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

        r = _place_named(state, "multi")
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
                "asset": asset.stem, "group": "Props",
                "pattern": {"type": "grid", "origin": [0, 0, 0],
                            "count": [2, 2, 3], "spacing": [6, 6]},
            }],
        }))
        assert not r.success
        assert "3-axis 'spacing'" in r.error


def test_place_layout_cleans_invalid_prim_names():
    """Digit-leading or spaced group segments and names are cleaned, not refused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        placements = [{
            "asset": asset.stem, "group": "2ndFloor/Wet Area", "name": "Floor Tile",
            "transforms": [{"translate": [0, 0, 0]}],
        }]
        r = asyncio.run(exec_tool(state, "place_layout", {
            "validate_only": True, "placements": placements,
        }))
        assert r.success, r.error
        assert r.data["groups"] == ["/Scene/_2ndFloor/Wet_Area"]

        r = asyncio.run(exec_tool(state, "place_layout", {"placements": placements}))
        assert r.success, r.error
        stage = Usd.Stage.Open(str(project.scene_path))
        group = stage.GetPrimAtPath("/Scene/_2ndFloor/Wet_Area")
        placed = [child.GetName() for child in group.GetChildren()]
        assert len(placed) == 1
        assert placed[0].startswith("Floor_Tile_")


def test_place_layout_rejects_oversized_layout():
    """A layout beyond the placement ceiling is refused without expansion."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        r = asyncio.run(exec_tool(state, "place_layout", {
            "validate_only": True,
            "placements": [{
                "asset": asset.stem, "group": "Props",
                "pattern": {"type": "grid", "origin": [0, 0, 0],
                            "count": [400, 400], "spacing": [1, 1]},
            }],
        }))
        assert not r.success
        assert "maximum per call" in r.error


def test_place_layout_same_file_two_spellings_no_collision():
    """The same asset by name and by library location is one source."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "tile")
        layout = project.path / "layout.json"
        layout.write_text(json.dumps({
            "version": 1,
            "placements": [
                {"asset": asset.stem, "group": "Props",
                 "transforms": [{"translate": [0, 0, 0]}]},
                {"asset": "tile.usda", "group": "Props",
                 "transforms": [{"translate": [2, 0, 0]}]},
            ],
        }), encoding="utf-8")
        r = asyncio.run(exec_tool(state, "place_layout", {
            "layout_file": "layout.json",
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
            "asset": _asset(tmp_path, "chest").stem,
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


def test_delete_project_file_never_leaves_the_textures_folder():
    """A texture name that points outside textures/ is refused and nothing is deleted."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        (project.path / "textures").mkdir(exist_ok=True)
        outside = tmp_path / "keep.txt"
        outside.write_text("keep")

        for name in ("../scene.usda", str(outside)):
            r = asyncio.run(exec_tool(state, "delete_project_file", {"file_name": name}))
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


# ── delete_project_file ──


def test_delete_project_file_unreferenced():
    """Deletes a texture that no USD file references."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        tex_dir = project.path / "textures"
        tex_dir.mkdir(parents=True, exist_ok=True)
        tex = tex_dir / "wood.png"
        tex.write_bytes(b"fake")

        r = asyncio.run(exec_tool(state, "delete_project_file", {
            "file_name": "wood.png",
        }))
        assert r.success, r.error
        assert not tex.exists()


def test_delete_project_file_refuses_when_referenced():
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

        r = asyncio.run(exec_tool(state, "delete_project_file", {
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
            "asset": asset.stem, "asset_name": "Chair",
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
            "asset": nested.stem,
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
    """Moves a non-identity root transform onto the parts; the mesh stays where it was."""
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
        frozen = Usd.Stage.Open(str(root_path))
        assert not UsdGeom.Xformable(frozen.GetPrimAtPath("/shifted")).GetOrderedXformOps()
        box = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default"]).ComputeWorldBound(
            frozen.GetPrimAtPath("/shifted/Mesh"),
        ).ComputeAlignedRange()
        assert box.GetMin() == Gf.Vec3d(5, 0, 0)
        assert box.GetMax() == Gf.Vec3d(6, 1, 0)


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


def _place_from(state, asset, name, x=0.0):
    return asyncio.run(exec_tool(state, "place_asset", {
        "asset": asset, "asset_name": name, "group": "Props",
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
        r = _place_from(state, root.parent.name, "Vase")
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
        r = _place_from(state, root.parent.name, "Vase")
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
            r = _place_from(state, folder.name, f"Shelf_{fmt}")
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

        crate = _place_from(state, "crate", "Crate")
        assert crate.success, crate.error
        assembly = _place_from(state, "assembly", "Assembly", x=2.0)
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
        assert _place_from(state, "lamp", "Lamp").success

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

        r = _place_from(state, "outside", "Outside")
        assert not r.success
        assert "outside its defaultPrim" in r.error
        r = _place_from(state, "missing", "Missing")
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
            "asset": "blob", "asset_name": "Blob",
            "group": "Props", "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
            "fix_root_prim": True,
        }))
        assert r.success, r.error
        geo = Sdf.Layer.FindOrOpen(str(project.path / "assets" / "blob" / "geo.usda"))
        assert geo.pseudoRoot.GetInfo("metersPerUnit") == 1.0


# ── tools take names and library locations, never file paths ──


def test_file_paths_are_refused_everywhere():
    """Assets, layouts, scatter, materials and textures refuse file paths, even library ones."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        state.library_dir = tmp_path / "lib"
        state.library_dir.mkdir()
        outside = tmp_path / "downloads"
        outside.mkdir()
        chair = _asset(outside, "chair")
        inside = _asset(state.library_dir, "table")
        (state.library_dir / "sky.exr").write_bytes(b"v/1\x01")
        materials = Usd.Stage.CreateNew(str(state.library_dir / "paint.usda"))
        UsdShade.Material.Define(materials, "/Materials/red")
        materials.Save()
        placed = _place_from(state, "table", "Table")
        assert placed.success, placed.error
        layout = project.path / "layout.json"
        layout.write_text(json.dumps({"version": 1, "placements": [
            {"asset": "table", "group": "Props", "transforms": [{"translate": [0, 0, 0]}]},
        ]}))

        calls = (
            ("place_asset", {"asset": str(chair), "asset_name": "Chair", "group": "Props",
                             "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0},
             "copy them into it first"),
            ("place_asset", {"asset": str(inside), "asset_name": "Table", "group": "Props",
                             "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0},
             "Use 'table'"),
            ("place_layout", {"placements": [{"asset": str(inside), "group": "Props",
                                              "transforms": [{"translate": [0, 0, 0]}]}]},
             "Use 'table'"),
            ("place_layout", {"layout_file": str(layout)}, "layout JSON in the project"),
            ("place_layout", {"layout_file": "../layout.json"}, "layout JSON in the project"),
            ("scatter_on_surface", {"name": "pile", "assets": [{"asset": str(inside)}],
                                    "surfaces": [placed.data["prim_path"]], "count": 3},
             "Use 'table'"),
            ("bind_material", {"prim_path": f"{placed.data['prim_path']}/asset/Mesh",
                               "material_asset": str(state.library_dir / "paint.usda")},
             "Use 'paint'"),
            ("create_light", {"light_type": "DomeLight", "light_name": "Sky",
                              "texture": str(state.library_dir / "sky.exr")},
             "Use its library location 'sky.exr'"),
            ("create_light", {"light_type": "DomeLight", "light_name": "Sky",
                              "texture": "../downloads/sky.exr"},
             "leaves its folder"),
        )
        for tool, params, hint in calls:
            r = asyncio.run(exec_tool(state, tool, params))
            assert not r.success, tool
            assert hint in r.error, (tool, r.error)
        assert sorted(p.name for p in project.assets_dir.iterdir()) == ["table"]
        assert not (project.path / "textures").exists()


def test_names_and_locations_are_accepted():
    """A name, a library location, a layout file in the project and a texture location all work."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        state.library_dir = tmp_path / "lib"
        (state.library_dir / "hdrs").mkdir(parents=True)
        (state.library_dir / "hdrs" / "sky.exr").write_bytes(b"v/1\x01")
        _asset(state.library_dir, "table")
        for asset in ("table", "table.usda"):
            r = _place_from(state, asset, "Table")
            assert r.success, (asset, r.error)
        layout = project.path / "layout.json"
        layout.write_text(json.dumps({"version": 1, "placements": [
            {"asset": "table", "group": "Props", "transforms": [{"translate": [4, 0, 0]}]},
        ]}))
        r = asyncio.run(exec_tool(state, "place_layout", {"layout_file": "layout.json"}))
        assert r.success, r.error
        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "DomeLight", "light_name": "Sky", "texture": "hdrs/sky.exr",
        }))
        assert r.success, r.error
        assert (project.path / "textures" / "sky.exr").exists()


def test_shared_names_ask_for_a_location_and_downloads_place_by_name():
    """Two library assets sharing a name are refused naming both; a location picks one.

    A skill download in the library's cache (e.g. cache/sketchfab/Lamp.usdz) places by name.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        lib = state.library_dir = tmp_path / "lib"
        (lib / "chair").mkdir(parents=True)
        _asset(lib / "chair", "chair")
        _asset(lib, "chair")
        (lib / "cache" / "sketchfab").mkdir(parents=True)
        from pxr import UsdUtils
        download = lib / "cache" / "sketchfab" / "Lamp.usdz"
        UsdUtils.CreateNewUsdzPackage(str(_asset(tmp_path, "lamp")), str(download))

        r = _place_from(state, "chair", "Chair")
        assert not r.success
        assert "(chair.usda, chair/chair.usda)" in r.error
        found = asyncio.run(exec_tool(state, "search_assets", {"query": "chair"}))
        locations = sorted(e["location"] for e in found.data["results"])
        assert locations == ["chair.usda", "chair/chair.usda"]
        r = _place_from(state, "chair.usda", "Chair")
        assert r.success, r.error

        r = _place_from(state, "Lamp", "Lamp")
        assert r.success, r.error
        assert (project.assets_dir / "Lamp.usdz").exists()


# ── side layers are clean ASWF layers ──


def test_side_layers_state_units_and_keep_their_root_an_over():
    """lgt/mtl/phy/contents/variants.usda state the asset's units and only over its root,
    and an older side layer without units gets them on the next edit."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _asset(tmp_path, "cabinet")
        _asset(tmp_path, "cup")
        cabinet = asyncio.run(exec_tool(state, "place_asset", {
            "asset": "cabinet", "asset_name": "Cabinet", "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        })).data["prim_path"]
        mesh = f"{cabinet}/asset/Mesh"
        for tool, params in (
            ("create_light", {"asset_prim_path": cabinet, "light_type": "SphereLight",
                              "light_name": "Bulb"}),
            ("create_material", {"prim_path": mesh, "material_name": "oak"}),
            ("apply_physics_api", {"prim_path": mesh, "api_name": "PhysicsCollisionAPI"}),
            ("place_asset_inside", {"asset": "cup", "asset_name": "Cup",
                                    "container_prim_path": cabinet, "group": "Props",
                                    "translate_x": 0.0, "translate_y": 0.5, "translate_z": 0.0}),
            ("add_asset_attribute_variant", {"prim_path": cabinet, "variant_set": "size",
                                             "variant_name": "big",
                                             "overrides": {mesh: {"size": 2.0}}}),
        ):
            r = asyncio.run(exec_tool(state, tool, params))
            assert r.success, (tool, r.error)

        asset_dir = project.assets_dir / "cabinet"
        for name in ("lgt.usda", "mtl.usda", "phy.usda", "contents.usda", "variants.usda"):
            layer = Sdf.Layer.FindOrOpen(str(asset_dir / name))
            assert layer.pseudoRoot.GetInfo("metersPerUnit") == 1.0, name
            assert layer.pseudoRoot.GetInfo("upAxis") == "Y", name
            assert layer.GetPrimAtPath("/cabinet").specifier == Sdf.SpecifierOver, name

        lgt = Sdf.Layer.FindOrOpen(str(asset_dir / "lgt.usda"))
        lgt.pseudoRoot.ClearInfo("metersPerUnit")
        lgt.Save()
        r = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": cabinet, "light_type": "SphereLight", "light_name": "Fill",
        }))
        assert r.success, r.error
        lgt.Reload()
        assert lgt.pseudoRoot.GetInfo("metersPerUnit") == 1.0


# ── model hierarchy ──


def _not_models(stage: Usd.Stage) -> list[str]:
    """Prims whose kind is a model kind but that are not models (an ancestor breaks the chain)."""
    return [
        str(prim.GetPath()) for prim in stage.Traverse()
        if Kind.Registry.IsA(Usd.ModelAPI(prim).GetKind() or "", Kind.Tokens.model)
        and not prim.IsModel()
    ]


def test_placements_are_models_and_nested_assets_are_subcomponents():
    """Placed assets sit in an unbroken model hierarchy (groups and wrappers are groups);
    an asset nested in another becomes a subcomponent of its container."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _asset(tmp_path, "shelf")
        _asset(tmp_path, "book")
        shelf = asyncio.run(exec_tool(state, "place_asset", {
            "asset": "shelf", "asset_name": "Shelf", "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        })).data["prim_path"]
        r = asyncio.run(exec_tool(state, "place_layout", {"placements": [{
            "asset": "book", "group": "Building/Racks",
            "transforms": [{"translate": [2, 0, 0]}, {"translate": [3, 0, 0]}],
        }]}))
        assert r.success, r.error
        nested = asyncio.run(exec_tool(state, "place_asset_inside", {
            "asset": "book", "asset_name": "Book", "container_prim_path": shelf,
            "group": "Props", "translate_x": 0.0, "translate_y": 0.5, "translate_z": 0.0,
        })).data["prim_path"]

        stage = Usd.Stage.Open(str(project.scene_path))
        assert _not_models(stage) == []
        for path in ("/Scene/Furniture", shelf, "/Scene/Building", "/Scene/Building/Racks"):
            assert Usd.ModelAPI(stage.GetPrimAtPath(path)).GetKind() == "group", path
        assert stage.GetPrimAtPath(f"{shelf}/asset").IsModel()
        assert Usd.ModelAPI(stage.GetPrimAtPath(f"{nested}/asset")).GetKind() == "subcomponent"


# ── nesting paths and project textures ──


def _run(state, tool, **params):
    return asyncio.run(exec_tool(state, tool, params))


def test_nesting_takes_the_container_or_its_asset_child_and_writes_nothing_when_refused():
    """A part or a nested placement as the container is refused before any write or copy."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        assets_dir = state.require_project().assets_dir
        table = _run(state, "place_asset", asset="table", asset_name="Table", group="Furniture",
                     translate_x=0.0, translate_y=0.0, translate_z=0.0).data["prim_path"]
        nest = {"group": "Props", "translate_x": 0.0, "translate_y": 0.1, "translate_z": 0.0}

        crate = _run(state, "place_asset_inside", asset="crate", asset_name="Crate",
                     container_prim_path=f"{table}/asset", **nest)
        assert crate.success, crate.error
        assert crate.data["prim_path"].startswith(f"{table}/asset/contents/Props/")
        contents = (assets_dir / "table" / "contents.usda").read_text()

        for container in (f"{table}/asset/Top", crate.data["prim_path"]):
            refused = _run(state, "place_asset_inside", asset="stone", asset_name="Stone",
                           container_prim_path=container, **nest)
            assert not refused.success, container
            assert (assets_dir / "table" / "contents.usda").read_text() == contents
        assert not (assets_dir / "stone").exists()


def test_delete_project_file_counts_every_use_and_stays_in_the_project():
    """A texture only an unselected variant uses is in use; paths outside textures are refused."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        project = state.require_project()
        sky = _run(state, "create_light", light_type="DomeLight", light_name="Sky",
                   texture="hdri/sky.png").data["prim_path"]
        shutil.copy(state.library_dir / "textures" / "glow.png", project.path / "textures")
        stage = state.require_stage()
        moods = stage.GetPrimAtPath("/Scene/Lighting").GetVariantSets().AddVariantSet("mood")
        for mood, texture in (("day", "./textures/sky.png"), ("night", "./textures/glow.png")):
            moods.AddVariant(mood)
            moods.SetVariantSelection(mood)
            with moods.GetVariantEditContext():
                stage.GetPrimAtPath(sky).GetAttribute("inputs:texture:file").Set(texture)
        moods.SetVariantSelection("day")
        stage.Save()

        for location in ("glow.png", "textures/sky.png"):
            used = _run(state, "delete_project_file", file_name=location)
            assert not used.success, location
            assert "scene.usda" in used.error
        for location in ("../scene.usda", "scene.usda", str(project.path / "textures/glow.png")):
            assert not _run(state, "delete_project_file", file_name=location).success
        assert (project.path / "textures" / "glow.png").exists()


# ── freezing keeps every part where it was ──


def _unfrozen_rig(path: Path, *, animated: bool = False) -> None:
    """A rig whose root is moved, turned and unevenly scaled, with parts of every kind below it."""
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = UsdGeom.Xform.Define(stage, "/rig")
    stage.SetDefaultPrim(root.GetPrim())
    root.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.5, 0.0))
    turn = root.AddRotateYOp()
    turn.Set(90.0)
    if animated:
        turn.Set(0.0, 1.0)
        turn.Set(90.0, 24.0)
    root.AddScaleOp().Set(Gf.Vec3f(2.0, 1.0, 3.0))
    wheel = UsdGeom.Xform.Define(stage, "/rig/wheel")  # a part at its pivot
    wheel.AddTranslateOp().Set(Gf.Vec3d(1.0, 0.0, 0.0))
    wheel.AddRotateZOp().Set(30.0)
    tire = UsdGeom.Mesh.Define(stage, "/rig/wheel/Tire")
    tire.GetPointsAttr().Set([Gf.Vec3f(-0.3, -0.3, -0.1), Gf.Vec3f(0.3, 0.3, 0.1),
                              Gf.Vec3f(0.3, -0.3, 0.1)])
    tire.GetFaceVertexCountsAttr().Set([3])
    tire.GetFaceVertexIndicesAttr().Set([0, 1, 2])
    UsdGeom.Cube.Define(stage, "/rig/Body").GetSizeAttr().Set(0.5)  # no points
    stage.DefinePrim("/rig/geo", "Scope")
    UsdGeom.Sphere.Define(stage, "/rig/geo/Lamp").GetRadiusAttr().Set(0.1)  # behind a scope
    sticker = UsdGeom.Xform.Define(stage, "/rig/Sticker")  # ignores its parent's transform
    sticker.SetResetXformStack(True)
    sticker.AddTranslateOp().Set(Gf.Vec3d(0.0, 3.0, 0.0))
    UsdGeom.Cube.Define(stage, "/rig/Sticker/Mesh").GetSizeAttr().Set(0.2)
    spare = UsdGeom.Xform.Define(stage, "/rig/Spare")  # switched off, but still a part
    spare.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 1.0))
    spare.GetPrim().SetActive(False)
    UsdGeom.ModelAPI(root.GetPrim()).SetExtentsHint([Gf.Vec3f(-1.0), Gf.Vec3f(1.0)])
    bolt = stage.CreateClassPrim("/_bolt")  # an instanced grouping's source
    UsdGeom.Cube.Define(stage, "/_bolt/Head").AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.5))
    bolts = stage.DefinePrim("/rig/Bolts", "Scope")
    bolts.GetReferences().AddInternalReference(bolt.GetPath())
    bolts.SetInstanceable(True)
    stage.Save()


def _gprim_bounds(stage: Usd.Stage, root: str) -> dict[str, tuple[float, ...]]:
    """World bounds of every gprim below *root*, keyed by its path relative to *root*."""
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    bounds = {}
    predicate = Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)
    for prim in Usd.PrimRange(stage.GetPrimAtPath(root), predicate):
        if prim.IsA(UsdGeom.Gprim):
            box = cache.ComputeWorldBound(prim).ComputeAlignedRange()
            key = str(prim.GetPath().MakeRelativePath(Sdf.Path(root)))
            bounds[key] = tuple(round(v, 4) for v in (*box.GetMin(), *box.GetMax()))
    return bounds


def test_fixing_root_transforms_keeps_every_part_where_it_was():
    """Pivoted parts, implicit shapes, a scope and a reset stack stay where the source has them."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _unfrozen_rig(state.library_dir / "rig.usda")
        source = _gprim_bounds(Usd.Stage.Open(str(state.library_dir / "rig.usda")), "/rig")

        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset": "rig", "asset_name": "Rig", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
            "fix_root_transforms": True,
        }))
        assert r.success, r.error
        placed = _gprim_bounds(state.require_stage(), f"{r.data['prim_path']}/asset")
        assert placed == source
        assert "Bolts/Head" in placed

        geo = Usd.Stage.Open(str(state.require_project().assets_dir / "rig" / "geo.usda"))
        root = UsdGeom.Xformable(geo.GetPrimAtPath("/rig"))
        assert not root.GetOrderedXformOps()
        wheel_ops = [op.GetOpName() for op in
                     UsdGeom.Xformable(geo.GetPrimAtPath("/rig/wheel")).GetOrderedXformOps()]
        assert wheel_ops == [
            "xformOp:transform:frozenRoot", "xformOp:translate", "xformOp:rotateZ",
        ]


def test_freeze_asset_keeps_every_part_where_it_was():
    """freeze_asset on a project copy: identical world bounds before and after."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset_dir = project.assets_dir / "rig"
        asset_dir.mkdir(parents=True)
        _unfrozen_rig(asset_dir / "geo.usda")
        root_stage = Usd.Stage.CreateNew(str(asset_dir / "rig.usda"))
        root_stage.SetDefaultPrim(root_stage.DefinePrim("/rig", "Xform"))
        root_stage.GetDefaultPrim().GetPayloads().AddPayload("./geo.usda")
        root_stage.Save()
        before = _gprim_bounds(Usd.Stage.Open(str(asset_dir / "rig.usda")), "/rig")

        r = asyncio.run(exec_tool(state, "freeze_asset", {"name": "rig"}))
        assert r.success, r.error
        assert r.data["results"][0]["baked"] is True
        after = _gprim_bounds(Usd.Stage.Open(str(asset_dir / "rig.usda")), "/rig")
        assert after == before

        geo = Sdf.Layer.FindOrOpen(str(asset_dir / "geo.usda"))
        assert not [n for n in geo.GetPrimAtPath("/rig").properties.keys()
                    if n.startswith("xformOp") or n == "extentsHint"]
        assert list(geo.GetPrimAtPath("/rig/Spare").attributes["xformOpOrder"].default) == [
            "xformOp:transform:frozenRoot", "xformOp:translate",
        ]

        # A second transform on the root later merges into the same op.
        stage = Usd.Stage.Open(str(asset_dir / "geo.usda"))
        UsdGeom.Xformable(stage.GetPrimAtPath("/rig")).AddTranslateOp().Set(Gf.Vec3d(0, 0, 4))
        stage.Save()
        before = _gprim_bounds(Usd.Stage.Open(str(asset_dir / "rig.usda")), "/rig")
        r = asyncio.run(exec_tool(state, "freeze_asset", {}))
        assert r.success, r.error
        assert r.data["baked_count"] == 1
        assert _gprim_bounds(Usd.Stage.Open(str(asset_dir / "rig.usda")), "/rig") == before
        wheel_order = geo.GetPrimAtPath("/rig/wheel").attributes["xformOpOrder"].default
        assert list(wheel_order).count("xformOp:transform:frozenRoot") == 1


def test_an_animated_root_transform_is_not_frozen():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _unfrozen_rig(state.library_dir / "rig.usda", animated=True)

        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset": "rig", "asset_name": "Rig", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
            "fix_root_transforms": True,
        }))
        assert not r.success
        assert "animated" in r.error


def _moved_library_folder(library: Path, name: str, *, inline: bool) -> Path:
    """A library folder whose root file moves the root prim: parts inline, or in geo.usda."""
    folder = library / name
    folder.mkdir()
    stage = Usd.Stage.CreateNew(str(folder / f"{name}.usda"))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = UsdGeom.Xform.Define(stage, f"/{name}")
    stage.SetDefaultPrim(root.GetPrim())
    root.AddTranslateOp().Set(Gf.Vec3d(0.0, 5.0, 0.0))
    root.AddRotateXOp().Set(-90.0)
    if inline:
        UsdGeom.Cube.Define(stage, f"/{name}/Box").GetSizeAttr().Set(1.0)
    else:
        geo = Usd.Stage.CreateNew(str(folder / "geo.usda"))
        geo.SetDefaultPrim(UsdGeom.Xform.Define(geo, f"/{name}").GetPrim())
        box = UsdGeom.Cube.Define(geo, f"/{name}/Box")
        box.AddTranslateOp().Set(Gf.Vec3d(0.0, 2.0, 0.0))
        geo.Save()
        root.GetPrim().GetPayloads().AddPayload("./geo.usda")
    stage.Save()
    return folder


def _place_at_origin(state, asset: str, **flags):
    return asyncio.run(exec_tool(state, "place_asset", {
        "asset": asset, "asset_name": asset.title(), "group": "Props",
        "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0, **flags,
    }))


def test_a_transform_in_a_library_folders_root_file_is_refused_then_frozen():
    """Intake checks what the root file composes, not only geo.usda."""
    for inline in (False, True):
        with tempfile.TemporaryDirectory() as tmp:
            state = library_state(Path(tmp))
            folder = _moved_library_folder(state.library_dir, "keg", inline=inline)
            source_bytes = {f.name: f.read_bytes() for f in folder.iterdir()}
            truth = _gprim_bounds(Usd.Stage.Open(str(folder / "keg.usda")), "/keg")

            refused = _place_at_origin(state, "keg")
            assert not refused.success
            assert "fix_root_transforms" in refused.error
            assert not (state.require_project().assets_dir / "keg").exists()

            r = _place_at_origin(state, "keg", fix_root_transforms=True)
            assert r.success, r.error
            placed = _gprim_bounds(state.require_stage(), f"{r.data['prim_path']}/asset")
            assert placed == truth
            copy = Usd.Stage.Open(str(state.require_project().assets_dir / "keg" / "keg.usda"))
            assert not UsdGeom.Xformable(copy.GetDefaultPrim()).GetOrderedXformOps()
            assert {f.name: f.read_bytes() for f in folder.iterdir()} == source_bytes


def test_a_library_folder_with_a_shape_root_is_wrapped_and_keeps_its_geometry():
    """A folder whose one file has a Cube root: refused, then wrapped; the cube still shows."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        folder = state.library_dir / "keg"
        folder.mkdir()
        stage = Usd.Stage.CreateNew(str(folder / "keg.usda"))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        cube = UsdGeom.Cube.Define(stage, "/keg")
        stage.SetDefaultPrim(cube.GetPrim())
        Usd.ModelAPI(cube.GetPrim()).SetKind(Kind.Tokens.component)
        stage.Save()

        refused = _place_at_origin(state, "keg")
        assert not refused.success
        assert "fix_root_prim" in refused.error

        r = _place_at_origin(state, "keg", fix_root_prim=True)
        assert r.success, r.error
        scene = state.require_stage()
        shape = scene.GetPrimAtPath(f"{r.data['prim_path']}/asset/mesh")
        assert shape.GetTypeName() == "Cube"
        box = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default"]).ComputeWorldBound(
            shape,
        ).ComputeAlignedRange()
        assert (box.GetMin(), box.GetMax()) == (Gf.Vec3d(-1), Gf.Vec3d(1))
        assert Usd.ModelAPI(shape).GetKind() == ""
        assert Usd.ModelAPI(scene.GetPrimAtPath(f"{r.data['prim_path']}/asset")).GetKind() == (
            Kind.Tokens.component
        )
        issues = asyncio.run(exec_tool(state, "validate_scene", {}))
        assert issues.success, issues.error
        assert issues.data["error_count"] == 0


def _lod_asset(assets_dir: Path, *, root_offsets: tuple[float, float] = (0.0, 0.0)) -> Path:
    """A project asset whose root file moves the root and switches two LOD payloads.

    *root_offsets* also move each LOD file's own root (an unfrozen export per LOD).
    """
    asset_dir = assets_dir / "lamp"
    asset_dir.mkdir(parents=True)
    lods = (("geo.usda", 1.0, root_offsets[0]), ("geo_low.usda", 0.5, root_offsets[1]))
    for file_name, height, offset in lods:
        geo = Usd.Stage.CreateNew(str(asset_dir / file_name))
        root = UsdGeom.Xform.Define(geo, "/lamp")
        geo.SetDefaultPrim(root.GetPrim())
        if offset:
            root.AddTranslateOp().Set(Gf.Vec3d(offset, 0.0, 0.0))
        shade = UsdGeom.Cube.Define(geo, "/lamp/Shade")
        shade.AddTranslateOp().Set(Gf.Vec3d(0.0, height, 0.0))
        geo.Save()
    stage = Usd.Stage.CreateNew(str(asset_dir / "lamp.usda"))
    root = UsdGeom.Xform.Define(stage, "/lamp")
    stage.SetDefaultPrim(root.GetPrim())
    if not any(root_offsets):
        root.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 3.0))
        root.AddScaleOp().Set(Gf.Vec3f(2.0))
    lod = root.GetPrim().GetVariantSets().AddVariantSet("lod")
    for variant, file_name in (("high", "geo.usda"), ("low", "geo_low.usda")):
        lod.AddVariant(variant)
        lod.SetVariantSelection(variant)
        with lod.GetVariantEditContext():
            root.GetPrim().GetPayloads().AddPayload(f"./{file_name}")
    lod.SetVariantSelection("high")
    stage.Save()
    return asset_dir


def _lod_bounds(asset_dir: Path) -> dict[str, tuple[float, ...]]:
    stage = Usd.Stage.Open(str(asset_dir / "lamp.usda"))
    lod = stage.GetDefaultPrim().GetVariantSet("lod")
    bounds = {}
    for variant in ("high", "low"):
        lod.SetVariantSelection(variant)
        bounds[variant] = _gprim_bounds(stage, "/lamp")["Shade"]
    return bounds


def _root_ops(usd_file: Path) -> list[str]:
    stage = Usd.Stage.Open(str(usd_file))
    root = stage.GetDefaultPrim()
    ops = []
    for variant in root.GetVariantSet("lod").GetVariantNames() or [""]:
        if variant:
            root.GetVariantSet("lod").SetVariantSelection(variant)
        ops += [op.GetOpName() for op in UsdGeom.Xformable(root).GetOrderedXformOps()]
    return ops


def test_freezing_moves_every_lod():
    """The root's transform lands on the parts of every geometry variant, not only the selected."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        asset_dir = _lod_asset(project.assets_dir)
        before = _lod_bounds(asset_dir)
        assert before["high"] != before["low"]

        r = asyncio.run(exec_tool(state, "freeze_asset", {"name": "lamp"}))
        assert r.success, r.error
        assert r.data["results"][0]["baked"] is True
        assert _lod_bounds(asset_dir) == before
        assert _root_ops(asset_dir / "lamp.usda") == []


def test_each_lod_keeps_its_own_root_transform():
    """LOD files exported unfrozen with different root transforms: each LOD stays in place."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        asset_dir = _lod_asset(project.assets_dir, root_offsets=(3.0, 7.0))
        before = _lod_bounds(asset_dir)

        r = asyncio.run(exec_tool(state, "freeze_asset", {"name": "lamp"}))
        assert r.success, r.error
        assert _lod_bounds(asset_dir) == before
        assert _root_ops(asset_dir / "lamp.usda") == []


def test_parts_shared_by_variants_that_move_the_root_differently_are_refused():
    """One frozen transform can't fit two root poses: refused before anything is written."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        asset_dir = project.assets_dir / "sign"
        asset_dir.mkdir(parents=True)
        stage = Usd.Stage.CreateNew(str(asset_dir / "sign.usda"))
        root = UsdGeom.Xform.Define(stage, "/sign")
        stage.SetDefaultPrim(root.GetPrim())
        UsdGeom.Cube.Define(stage, "/sign/Board")
        pose = root.GetPrim().GetVariantSets().AddVariantSet("pose")
        for variant, height in (("low", 1.0), ("high", 4.0)):
            pose.AddVariant(variant)
            pose.SetVariantSelection(variant)
            with pose.GetVariantEditContext():
                root.AddTranslateOp().Set(Gf.Vec3d(0.0, height, 0.0))
        stage.Save()
        files = {f.name: f.read_bytes() for f in asset_dir.iterdir()}

        r = asyncio.run(exec_tool(state, "freeze_asset", {"name": "sign"}))
        assert not r.success
        assert "moves differently per variant" in r.error
        assert {f.name: f.read_bytes() for f in asset_dir.iterdir()} == files


def test_a_freeze_that_would_move_a_part_changes_nothing(monkeypatch):
    """The world-transform check is the safety net: any mismatch restores every file."""
    from bowerbot.utils.assets import freeze

    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        asset_dir = _lod_asset(project.assets_dir)
        files = {f.name: f.read_bytes() for f in asset_dir.iterdir()}
        monkeypatch.setattr(freeze, "_prepend_matrix", lambda spec, matrix, op_suffix: None)

        r = asyncio.run(exec_tool(state, "freeze_asset", {"name": "lamp"}))
        assert not r.success
        assert "nothing was changed" in r.error
        assert {f.name: f.read_bytes() for f in asset_dir.iterdir()} == files
        assert _root_ops(asset_dir / "lamp.usda") != []


def _usdz(library: Path, name: str, *, root_type: str = "Xform", moved: bool = False) -> None:
    source = library / f"{name}_src.usda"
    stage = Usd.Stage.CreateNew(str(source))
    root = stage.DefinePrim(f"/{name}", root_type)
    stage.SetDefaultPrim(root)
    if moved:
        UsdGeom.Xformable(root).AddTranslateOp().Set(Gf.Vec3d(0.0, 5.0, 0.0))
    if root_type == "Xform":
        UsdGeom.Cube.Define(stage, f"/{name}/Box")
    stage.Save()
    assert UsdUtils.CreateNewUsdzPackage(str(source), str(library / f"{name}.usdz"))
    source.unlink()


def test_a_usdz_a_placement_would_break_is_refused():
    """A package can't be repaired in place: a shape root or a moved root is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _usdz(state.library_dir, "boxed", root_type="Cube")
        _usdz(state.library_dir, "shifted", moved=True)
        _usdz(state.library_dir, "clean")

        for name, reason in (("boxed", "Cube"), ("shifted", "non-identity")):
            r = _place_at_origin(state, name)
            assert not r.success
            assert reason in r.error
            assert "unpack it" in r.error
            assert not (state.require_project().assets_dir / f"{name}.usdz").exists()
        assert _place_at_origin(state, "clean").success
