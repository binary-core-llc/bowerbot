# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the scene-assembly tools through the dispatcher — no LLM involved."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom

from bowerbot.services import stage_service
from tests._helpers import exec_tool, make_state


def create_test_asset(directory: Path, name: str) -> Path:
    """Create a simple USD asset for testing."""
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    cube = UsdGeom.Cube.Define(stage, f"/{name}/Mesh")
    cube.GetSizeAttr().Set(1.0)
    stage.Save()
    return path


def test_create_stage():
    """create_stage produces a valid USD file."""
    with tempfile.TemporaryDirectory() as tmp:
        state, project = make_state(Path(tmp))
        result = asyncio.run(
            exec_tool(state, "create_stage", {"filename": "my_store"}),
        )

        assert result.success, f"Failed: {result.error}"
        assert project.scene_path.exists(), "Stage file not on disk"

        stage = Usd.Stage.Open(str(project.scene_path))
        assert stage.GetDefaultPrim().IsValid()

        print("test_create_stage PASSED")


def test_place_asset():
    """place_asset adds a referenced prim with correct transform."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        asset_path = create_test_asset(tmp_path, "table")

        state, project = make_state(tmp_path, "place_test")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "test_scene"}))

        result = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset_path),
            "asset_name": "DisplayTable",
            "group": "Furniture",
            "translate_x": 3.0,
            "translate_y": 0.0,
            "translate_z": 4.0,
            "rotate_y": 90.0,
        }))

        assert result.success, f"Failed: {result.error}"
        prim_path = result.data["prim_path"]
        assert prim_path.startswith("/Scene/Furniture/")

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(prim_path)
        assert prim.IsValid(), f"Prim not found: {prim_path}"

        xformable = UsdGeom.Xformable(prim)
        translate = xformable.GetLocalTransformation().ExtractTranslation()
        assert abs(translate[0] - 3.0) < 0.01
        assert abs(translate[1] - 0.0) < 0.01
        assert abs(translate[2] - 4.0) < 0.01

        print(f"test_place_asset PASSED — placed at {prim_path}")


def test_place_multiple_assets():
    """Place several assets and verify unique prim paths."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        table_path = create_test_asset(tmp_path, "table")
        chair_path = create_test_asset(tmp_path, "chair")

        state, _ = make_state(tmp_path, "multi_test")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "multi_test"}))

        prim_paths = []
        for asset, name, x, z in [
            (table_path, "Table", 3.0, 4.0),
            (table_path, "Table", 5.0, 4.0),
            (chair_path, "Chair", 3.0, 2.0),
            (chair_path, "Chair", 5.0, 2.0),
        ]:
            result = asyncio.run(exec_tool(state, "place_asset", {
                "asset_file_path": str(asset),
                "asset_name": name,
                "group": "Furniture",
                "translate_x": x,
                "translate_y": 0.0,
                "translate_z": z,
            }))
            assert result.success, f"Failed: {result.error}"
            prim_paths.append(result.data["prim_path"])

        assert len(set(prim_paths)) == 4, f"Duplicate prim paths: {prim_paths}"

        print(f"test_place_multiple_assets PASSED — {prim_paths}")


def test_compute_grid_layout():
    """Grid layout returns correct number of positions."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp), "grid_test")
        result = asyncio.run(exec_tool(state, "compute_grid_layout", {
            "count": 6,
            "spacing": 2.5,
        }))

        assert result.success
        assert len(result.data["positions"]) == 6

        print(f"test_compute_grid_layout PASSED — {result.data['positions']}")


def test_validate_scene():
    """Validator approves a well-formed scene."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        asset_path = create_test_asset(tmp_path, "item")

        state, _ = make_state(tmp_path, "valid_test")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "valid_test"}))
        asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset_path),
            "asset_name": "Item",
            "group": "Props",
            "translate_x": 1.0,
            "translate_y": 0.0,
            "translate_z": 1.0,
        }))

        result = asyncio.run(exec_tool(state, "validate_scene"))
        assert result.success
        assert result.data["is_valid"], f"Validation failed: {result.data['issues']}"

        print("test_validate_scene PASSED")


def test_package_scene():
    """Package produces a .usdz file."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        asset_path = create_test_asset(tmp_path, "item")

        state, _ = make_state(tmp_path, "package_test")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "package_test"}))
        asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset_path),
            "asset_name": "Item",
            "group": "Props",
            "translate_x": 1.0,
            "translate_y": 0.0,
            "translate_z": 1.0,
        }))

        result = asyncio.run(exec_tool(state, "package_scene"))

        assert result.success, f"Failed: {result.error}"
        usdz_path = Path(result.data["usdz_path"])
        assert usdz_path.exists()
        assert usdz_path.suffix == ".usdz"
        assert usdz_path.stat().st_size > 0

        size = usdz_path.stat().st_size
        print(f"test_package_scene PASSED — {usdz_path.name} ({size} bytes)")


def test_move_asset():
    """move_asset updates transform without creating a duplicate."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mug_path = create_test_asset(tmp_path, "mug")
        table_path = create_test_asset(tmp_path, "table")

        state, project = make_state(tmp_path, "move_test")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "move_test"}))

        asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(table_path),
            "asset_name": "Table",
            "group": "Furniture",
            "translate_x": 5.0,
            "translate_y": 0.0,
            "translate_z": 4.0,
        }))

        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(mug_path),
            "asset_name": "Mug",
            "group": "Products",
            "translate_x": 5.0,
            "translate_y": 0.0,
            "translate_z": 4.0,
        }))
        assert r.success
        mug_prim_path = r.data["prim_path"]

        r = asyncio.run(exec_tool(state, "move_asset", {
            "prim_path": mug_prim_path,
            "translate_x": 5.0,
            "translate_y": 0.75,
            "translate_z": 4.0,
        }))
        assert r.success

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(mug_prim_path)
        assert prim.IsValid(), f"Prim not found: {mug_prim_path}"

        xformable = UsdGeom.Xformable(prim)
        t = xformable.GetLocalTransformation().ExtractTranslation()
        assert abs(t[1] - 0.75) < 0.01, f"Y should be 0.75, got {t[1]}"

        objects = stage_service.list_prims(state.stage)
        mug_prims = [o for o in objects if "Mug" in o["prim_path"]]
        assert len(mug_prims) == 1, (
            f"Expected 1 mug prim, got {len(mug_prims)}: {mug_prims}"
        )

        print("test_move_asset PASSED")


def test_unit_conversion():
    """Assets in cm are auto-scaled to meters."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        cm_asset = tmp_path / "table_cm.usda"
        stage = Usd.Stage.CreateNew(str(cm_asset))
        UsdGeom.SetStageMetersPerUnit(stage, 0.01)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        root = stage.DefinePrim("/table", "Xform")
        stage.SetDefaultPrim(root)
        cube = UsdGeom.Cube.Define(stage, "/table/Mesh")
        cube.GetSizeAttr().Set(80.0)  # 80 cm
        stage.Save()

        state, _ = make_state(tmp_path, "unit_test")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "unit_test"}))

        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(cm_asset),
            "asset_name": "Table",
            "group": "Furniture",
            "translate_x": 5.0,
            "translate_y": 0.0,
            "translate_z": 4.0,
        }))
        assert r.success, f"Failed: {r.error}"

        r = asyncio.run(exec_tool(state, "list_scene"))
        assert r.success
        table_obj = r.data["objects"][0]
        bounds = table_obj["bounds"]

        height = bounds["max"]["y"] - bounds["min"]["y"]
        assert 0.7 < height < 0.9, f"Expected ~0.8m height, got {height}"

        print("test_unit_conversion PASSED")


def test_full_pipeline():
    """Full pipeline — create → place → validate → package."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        table = create_test_asset(tmp_path, "table")
        light = create_test_asset(tmp_path, "pendant")

        state, _ = make_state(tmp_path, "full_pipeline")
        r = asyncio.run(exec_tool(state, "create_stage", {"filename": "full_pipeline"}))
        assert r.success

        r = asyncio.run(exec_tool(
            state, "compute_grid_layout", {"count": 4, "spacing": 2.0},
        ))
        assert r.success
        positions = r.data["positions"]

        for pos in positions:
            r = asyncio.run(exec_tool(state, "place_asset", {
                "asset_file_path": str(table),
                "asset_name": "Table",
                "group": "Furniture",
                "translate_x": pos["x"],
                "translate_y": 0.0,
                "translate_z": pos["z"],
            }))
            assert r.success

        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(light),
            "asset_name": "CeilingLight",
            "group": "Lighting",
            "translate_x": 5.0,
            "translate_y": 2.7,
            "translate_z": 4.0,
        }))
        assert r.success

        r = asyncio.run(exec_tool(state, "validate_scene"))
        assert r.success
        assert r.data["is_valid"], f"Validation errors: {r.data['issues']}"

        r = asyncio.run(exec_tool(state, "package_scene"))
        assert r.success
        usdz_path = Path(r.data["usdz_path"])
        assert usdz_path.exists()

        size = usdz_path.stat().st_size
        print("test_full_pipeline PASSED")
        print(f"   4 tables + 1 light -> {usdz_path.name} ({size} bytes)")


if __name__ == "__main__":
    test_create_stage()
    test_place_asset()
    test_place_multiple_assets()
    test_compute_grid_layout()
    test_validate_scene()
    test_package_scene()
    test_move_asset()
    test_unit_conversion()
    test_full_pipeline()
    print("\nAll scene builder tests passed!")
