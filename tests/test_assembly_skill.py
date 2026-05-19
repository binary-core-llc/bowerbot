# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the scene-assembly tools through the dispatcher — no LLM involved."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom

from bowerbot.utils import stage_utils
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

        objects = stage_utils.list_prims(state.stage)
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


def test_update_light_with_texture_copies_hdri_and_sets_attr():
    """update_light with a DomeLight texture stages the HDRI and sets the attr."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        hdri = tmp_path / "studio.hdr"
        hdri.write_bytes(b"fake-hdri-payload")

        state, project = make_state(tmp_path, "dome_test")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "dome_test"}))

        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "DomeLight",
            "light_name": "Environment_Dome",
            "intensity": 1.0,
        }))
        assert r.success, f"create_light failed: {r.error}"
        prim_path = r.data["prim_path"]

        r = asyncio.run(exec_tool(state, "update_light", {
            "prim_path": prim_path,
            "texture": str(hdri),
        }))
        assert r.success, f"update_light failed: {r.error}"

        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": prim_path,
            "attribute_name": "inputs:intensity",
            "value": 2.5,
        }))
        assert r.success
        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": prim_path,
            "attribute_name": "inputs:exposure",
            "value": 1.0,
        }))
        assert r.success

        staged = project.path / "textures" / "studio.hdr"
        assert staged.exists(), "HDRI not copied into project/textures/"

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(prim_path)
        assert prim.IsValid()
        tex_attr = prim.GetAttribute("inputs:texture:file")
        assert tex_attr and tex_attr.Get(), (
            "inputs:texture:file not authored on the DomeLight"
        )
        tex_val = tex_attr.Get()
        tex_path = tex_val.path if hasattr(tex_val, "path") else str(tex_val)
        assert tex_path == "./textures/studio.hdr", (
            f"Expected './textures/studio.hdr', got {tex_path!r}"
        )
        assert prim.GetAttribute("inputs:intensity").Get() == 2.5
        assert prim.GetAttribute("inputs:exposure").Get() == 1.0


def _place_two_sofas_then_get_first_path(state, sofa_asset: Path) -> str:
    """Place two sofas referencing the same asset; return the first prim path."""
    asyncio.run(exec_tool(state, "create_stage", {"filename": "shared_test"}))
    first_path = ""
    for i in range(2):
        result = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(sofa_asset),
            "asset_name": "Sofa",
            "group": "Furniture",
            "translate_x": float(i * 2),
            "translate_y": 0.0,
            "translate_z": 0.0,
        }))
        assert result.success, f"Failed to place sofa {i}: {result.error}"
        if i == 0:
            first_path = result.data["prim_path"]
    return first_path


def test_place_asset_inside_blocks_shared_container_without_confirm():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, _ = make_state(tmp_path)
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        sofa = create_test_asset(source_dir, "sofa")
        pillow = create_test_asset(source_dir, "pillow")

        first_sofa = _place_two_sofas_then_get_first_path(state, sofa)

        result = asyncio.run(exec_tool(state, "place_asset_inside", {
            "asset_file_path": str(pillow),
            "asset_name": "Pillow",
            "container_prim_path": first_sofa,
            "group": "Props",
            "translate_x": 0.0,
            "translate_y": 0.5,
            "translate_z": 0.0,
        }))
        assert result.success is False
        assert "2 scene instances" in result.error
        assert "place_asset" in result.error
        assert "confirm_shared_modification" in result.error


def test_place_asset_inside_proceeds_with_confirm_flag():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, _ = make_state(tmp_path)
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        sofa = create_test_asset(source_dir, "sofa")
        pillow = create_test_asset(source_dir, "pillow")

        first_sofa = _place_two_sofas_then_get_first_path(state, sofa)

        result = asyncio.run(exec_tool(state, "place_asset_inside", {
            "asset_file_path": str(pillow),
            "asset_name": "Pillow",
            "container_prim_path": first_sofa,
            "group": "Props",
            "translate_x": 0.0,
            "translate_y": 0.5,
            "translate_z": 0.0,
            "confirm_shared_modification": True,
        }))
        assert result.success, f"Expected success with confirm flag: {result.error}"


def test_place_asset_inside_succeeds_for_unique_container():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, _ = make_state(tmp_path)
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        sofa = create_test_asset(source_dir, "sofa")
        pillow = create_test_asset(source_dir, "pillow")

        asyncio.run(exec_tool(state, "create_stage", {"filename": "unique_test"}))
        place_result = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(sofa),
            "asset_name": "Sofa",
            "group": "Furniture",
            "translate_x": 0.0,
            "translate_y": 0.0,
            "translate_z": 0.0,
        }))
        assert place_result.success
        single_sofa = place_result.data["prim_path"]

        result = asyncio.run(exec_tool(state, "place_asset_inside", {
            "asset_file_path": str(pillow),
            "asset_name": "Pillow",
            "container_prim_path": single_sofa,
            "group": "Props",
            "translate_x": 0.0,
            "translate_y": 0.5,
            "translate_z": 0.0,
        }))
        assert result.success, f"Expected success for unique container: {result.error}"


def test_move_asset_routes_nested_to_contents_layer():
    """move_asset on a nested path writes to contents.usda, not scene.usda."""
    from pxr import Sdf
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, project = make_state(tmp_path)
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        sofa = create_test_asset(source_dir, "sofa")
        pillow = create_test_asset(source_dir, "pillow")

        asyncio.run(exec_tool(state, "create_stage", {"filename": "route_test"}))
        place = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(sofa),
            "asset_name": "Sofa",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        sofa_prim = place.data["prim_path"]

        nested = asyncio.run(exec_tool(state, "place_asset_inside", {
            "asset_file_path": str(pillow),
            "asset_name": "Pillow",
            "container_prim_path": sofa_prim,
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.5, "translate_z": 0.0,
        }))
        assert nested.success
        nested_prim = nested.data["prim_path"]
        assert "/asset/contents/Props/" in nested_prim

        move = asyncio.run(exec_tool(state, "move_asset", {
            "prim_path": nested_prim,
            "translate_x": 0.0, "translate_y": 1.5, "translate_z": 0.0,
        }))
        assert move.success, f"move_asset failed: {move.error}"

        scene_layer = Sdf.Layer.FindOrOpen(str(project.scene_path))
        assert scene_layer.GetPrimAtPath(Sdf.Path(nested_prim)) is None, (
            "scene.usda should not author specs on nested paths"
        )

        sofa_dir = project.path / "assets" / "sofa"
        contents_layer = Sdf.Layer.FindOrOpen(str(sofa_dir / "contents.usda"))
        wrapper_spec = contents_layer.GetPrimAtPath(
            Sdf.Path("/sofa/contents/Props/Pillow_02"),
        )
        assert wrapper_spec is not None, "Wrapper missing in contents.usda"

        print("test_move_asset_routes_nested_to_contents_layer PASSED")


def test_save_scene_snapshot_strips_dcc_artifacts():
    """Snapshot is clean; scene.usda keeps its DCC scratch and is otherwise untouched."""
    from pxr import Sdf
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chair = create_test_asset(tmp_path, "chair")
        state, project = make_state(tmp_path, "strip")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "strip"}))
        asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(chair), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))

        scene = Usd.Stage.Open(str(project.scene_path))
        scene.GetRootLayer().customLayerData = {
            "cameraSettings": {"boundCamera": "/OmniverseKit_Persp"},
            "renderSettings": {},
        }
        scene.DefinePrim("/OmniverseKit_Persp", "Camera")
        scene.Save()
        del scene
        state.stage = stage_utils.open_stage(project.scene_path)

        r = asyncio.run(exec_tool(state, "save_scene_snapshot", {
            "name": "v1",
        }))
        assert r.success

        snapshot_path = project.scene_path.parent / "v1.usda"
        snapshot_layer = Sdf.Layer.FindOrOpen(str(snapshot_path))
        assert not snapshot_layer.customLayerData
        assert snapshot_layer.GetPrimAtPath(Sdf.Path("/OmniverseKit_Persp")) is None
        assert snapshot_layer.GetPrimAtPath(
            Sdf.Path("/Scene/Furniture/Chair_01"),
        ) is not None

        scene_layer = Sdf.Layer.FindOrOpen(str(project.scene_path))
        assert scene_layer.customLayerData.get("renderSettings") == {}
        assert scene_layer.GetPrimAtPath(
            Sdf.Path("/OmniverseKit_Persp"),
        ) is not None
        assert scene_layer.GetPrimAtPath(Sdf.Path("/Scene/Furniture/Chair_01")) is not None
        assert not scene_layer.subLayerPaths


def test_save_scene_snapshot_does_not_modify_scene_usda():
    """Snapshot writes the named file but leaves scene.usda byte-identical."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chair = create_test_asset(tmp_path, "chair")
        state, project = make_state(tmp_path, "untouched")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "untouched"}))
        asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(chair), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 1.0, "translate_y": 0.0, "translate_z": 1.0,
        }))

        scene_before = project.scene_path.read_bytes()
        r = asyncio.run(exec_tool(state, "save_scene_snapshot", {
            "name": "kitchen_v1",
        }))
        assert r.success
        snapshot_path = project.scene_path.parent / "kitchen_v1.usda"
        assert snapshot_path.exists()
        assert project.scene_path.read_bytes() == scene_before


def test_save_scene_snapshot_supports_multiple_named_versions():
    """Multiple named snapshots coexist alongside scene.usda."""
    from pxr import Sdf
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chair = create_test_asset(tmp_path, "chair")
        state, project = make_state(tmp_path, "versions")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "versions"}))
        asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(chair), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))

        r1 = asyncio.run(exec_tool(state, "save_scene_snapshot", {
            "name": "kitchen_v1",
        }))
        assert r1.success
        r2 = asyncio.run(exec_tool(state, "save_scene_snapshot", {
            "name": "kitchen_v2",
        }))
        assert r2.success

        listing = asyncio.run(exec_tool(state, "list_scene_snapshots", {}))
        assert listing.success
        names = {s["name"] for s in listing.data["snapshots"]}
        assert names == {"kitchen_v1", "kitchen_v2"}

        for name in names:
            path = project.scene_path.parent / f"{name}.usda"
            layer = Sdf.Layer.FindOrOpen(str(path))
            assert layer.GetPrimAtPath(
                Sdf.Path("/Scene/Furniture/Chair_01"),
            ) is not None


def test_save_scene_snapshot_refuses_overwrite_without_force():
    """Re-using a snapshot name must require force=true."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chair = create_test_asset(tmp_path, "chair")
        state, _project = make_state(tmp_path, "force")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "force"}))
        asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(chair), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))

        r1 = asyncio.run(exec_tool(state, "save_scene_snapshot", {"name": "v1"}))
        assert r1.success
        r2 = asyncio.run(exec_tool(state, "save_scene_snapshot", {"name": "v1"}))
        assert not r2.success
        assert "already exists" in r2.error.lower()
        r3 = asyncio.run(exec_tool(state, "save_scene_snapshot", {
            "name": "v1", "force": True,
        }))
        assert r3.success


def test_delete_scene_snapshot_removes_file():
    """delete_scene_snapshot removes the named file."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chair = create_test_asset(tmp_path, "chair")
        state, project = make_state(tmp_path, "del")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "del"}))
        asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(chair), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        asyncio.run(exec_tool(state, "save_scene_snapshot", {"name": "v1"}))
        snapshot_path = project.scene_path.parent / "v1.usda"
        assert snapshot_path.exists()

        r = asyncio.run(exec_tool(state, "delete_scene_snapshot", {"name": "v1"}))
        assert r.success
        assert not snapshot_path.exists()

        missing = asyncio.run(exec_tool(state, "delete_scene_snapshot", {"name": "v1"}))
        assert not missing.success


def test_move_asset_preserves_omitted_axes():
    """When the LLM omits axes, those axes keep their current value."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chair = create_test_asset(tmp_path, "chair")
        state, project = make_state(tmp_path, "axes")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "axes"}))
        place = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(chair), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 5.0, "translate_y": 0.0, "translate_z": 4.0,
        }))
        prim_path = place.data["prim_path"]

        # Move ONLY Y; X and Z must stay at 5.0 / 4.0
        r = asyncio.run(exec_tool(state, "move_asset", {
            "prim_path": prim_path, "translate_y": 2.0,
        }))
        assert r.success
        assert r.data["position"] == {"x": 5.0, "y": 2.0, "z": 4.0}

        # Move ONLY Y back down
        r = asyncio.run(exec_tool(state, "move_asset", {
            "prim_path": prim_path, "translate_y": 0.0,
        }))
        assert r.success
        assert r.data["position"] == {"x": 5.0, "y": 0.0, "z": 4.0}


def test_move_asset_refuses_path_inside_referenced_asset():
    """move_asset on a path inside a referenced asset (not a wrapper) refuses."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, _ = make_state(tmp_path)
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        sofa = create_test_asset(source_dir, "sofa")

        asyncio.run(exec_tool(state, "create_stage", {"filename": "guard_test"}))
        place = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(sofa),
            "asset_name": "Sofa",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        sofa_prim = place.data["prim_path"]

        result = asyncio.run(exec_tool(state, "move_asset", {
            "prim_path": f"{sofa_prim}/asset/Mesh",
            "translate_x": 1.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert not result.success
        assert "referenced" in result.error.lower()

        print("test_move_asset_refuses_path_inside_referenced_asset PASSED")


def test_rename_prim_refuses_nested_path():
    """rename_prim on a nested-contents path returns an error."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, _ = make_state(tmp_path)
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        sofa = create_test_asset(source_dir, "sofa")
        pillow = create_test_asset(source_dir, "pillow")

        asyncio.run(exec_tool(state, "create_stage", {"filename": "rename_test"}))
        place = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(sofa),
            "asset_name": "Sofa",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        sofa_prim = place.data["prim_path"]

        nested = asyncio.run(exec_tool(state, "place_asset_inside", {
            "asset_file_path": str(pillow),
            "asset_name": "Pillow",
            "container_prim_path": sofa_prim,
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.5, "translate_z": 0.0,
        }))
        nested_prim = nested.data["prim_path"]

        result = asyncio.run(exec_tool(state, "rename_prim", {
            "old_path": nested_prim,
            "new_path": nested_prim.replace("Pillow_02", "Pillow_99"),
        }))
        assert not result.success
        assert "scene level" in result.error.lower()

        print("test_rename_prim_refuses_nested_path PASSED")


def _create_dirty_test_asset(directory: Path, name: str) -> Path:
    """Create a USD asset with a non-identity root transform (Maya-style)."""
    from pxr import Gf
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Xformable(root).AddTranslateOp().Set(Gf.Vec3d(5.0, 0.0, 4.0))
    cube = UsdGeom.Cube.Define(stage, f"/{name}/Mesh")
    cube.GetSizeAttr().Set(1.0)
    stage.Save()
    return path


def test_place_asset_rejects_dirty_root_without_flag():
    """place_asset on an unfrozen asset fails with a helpful message + rolls back."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, project = make_state(tmp_path)
        dirty = _create_dirty_test_asset(tmp_path, "dirty_thing")

        asyncio.run(exec_tool(state, "create_stage", {"filename": "dirty_test"}))
        result = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(dirty),
            "asset_name": "Dirty",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert not result.success
        assert "non-identity transforms" in result.error.lower()

        target = project.path / "assets" / "dirty_thing"
        assert not target.exists(), "Failed intake should roll back the copy"

        print("test_place_asset_rejects_dirty_root_without_flag PASSED")


def test_place_asset_bakes_with_fix_root_transforms_flag():
    """place_asset with fix_root_transforms=True bakes; source untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, project = make_state(tmp_path)
        dirty = _create_dirty_test_asset(tmp_path, "dirty_thing")
        source_size_before = dirty.stat().st_size

        asyncio.run(exec_tool(state, "create_stage", {"filename": "bake_test"}))
        result = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(dirty),
            "asset_name": "Dirty",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
            "fix_root_transforms": True,
        }))
        assert result.success, f"Expected success: {result.error}"

        target_geo = project.path / "assets" / "dirty_thing" / "geo.usda"
        assert target_geo.exists()
        baked_stage = Usd.Stage.Open(str(target_geo))
        baked_root = baked_stage.GetDefaultPrim()
        assert UsdGeom.Xformable(baked_root).GetXformOpOrderAttr().Get() in (
            None, [],
        ), "Baked geo.usda should have no xform ops on root"

        assert dirty.stat().st_size == source_size_before, (
            "Source file should not be modified by bake"
        )

        print("test_place_asset_bakes_with_fix_root_transforms_flag PASSED")


def test_freeze_asset_batch_freezes_every_dirty_asset():
    """freeze_asset with no name freezes every dirty asset in the project."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, project = make_state(tmp_path)
        d1 = _create_dirty_test_asset(tmp_path, "dirty_a")
        d2 = _create_dirty_test_asset(tmp_path, "dirty_b")
        clean = create_test_asset(tmp_path, "clean_c")

        asyncio.run(exec_tool(state, "create_stage", {"filename": "batch_test"}))
        for path, name, group in [
            (d1, "DirtyA", "Furniture"),
            (d2, "DirtyB", "Props"),
            (clean, "CleanC", "Lighting"),
        ]:
            asyncio.run(exec_tool(state, "place_asset", {
                "asset_file_path": str(path),
                "asset_name": name,
                "group": group,
                "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
                "fix_root_transforms": True,
            }))

        re_dirty = project.path / "assets" / "dirty_a" / "geo.usda"
        layer = Usd.Stage.Open(str(re_dirty))
        prim = layer.GetDefaultPrim()
        UsdGeom.Xformable(prim).AddTranslateOp().Set(__import__("pxr").Gf.Vec3d(1, 0, 0))
        layer.Save()

        result = asyncio.run(exec_tool(state, "freeze_asset", {}))
        assert result.success, f"Batch freeze failed: {result.error}"
        names = {r["name"] for r in result.data["results"]}
        assert {"dirty_a", "dirty_b", "clean_c"}.issubset(names)

        baked_a = next(
            r for r in result.data["results"] if r["name"] == "dirty_a"
        )
        assert baked_a["baked"] is True
        baked_c = next(
            r for r in result.data["results"] if r["name"] == "clean_c"
        )
        assert baked_c["baked"] is False

        print("test_freeze_asset_batch_freezes_every_dirty_asset PASSED")


def test_list_and_set_prim_attribute_generic_path():
    """list_prim_attributes discovers schema inputs; set_prim_attribute authors override."""
    from pxr import Sdf
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chair = create_test_asset(tmp_path, "chair")
        state, project = make_state(tmp_path, "generic_attr")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "generic_attr"}))
        place = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(chair), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        prim_path = place.data["prim_path"]
        mesh_path = f"{prim_path}/asset/Mesh"

        asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path,
            "material_name": "walnut",
            "base_color_r": 0.4, "base_color_g": 0.2, "base_color_b": 0.1,
        }))

        shader_path = f"{prim_path}/asset/mtl/walnut/standard_surface"
        r = asyncio.run(exec_tool(state, "list_prim_attributes", {
            "prim_path": shader_path,
        }))
        assert r.success
        names = {a["name"] for a in r.data["attributes"]}
        assert "inputs:base_color" in names
        # MaterialX schema exposes these even if not authored
        assert "inputs:sheen" in names or any(
            n.startswith("inputs:") for n in names
        )

        # Author a per-instance override on a schema attribute (sheen)
        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": shader_path,
            "attribute_name": "inputs:sheen",
            "value": 0.4,
        }))
        assert r.success

        # Override lands in scene.usda, NOT the asset's mtl.usda
        scene_layer = Sdf.Layer.FindOrOpen(str(project.scene_path))
        spec = scene_layer.GetPrimAtPath(Sdf.Path(shader_path))
        assert spec is not None
        attr = spec.attributes.get("inputs:sheen")
        assert attr is not None
        assert abs(float(attr.default) - 0.4) < 1e-6

        mtl_path = project.path / "assets" / "chair" / "mtl.usda"
        mtl_layer = Sdf.Layer.FindOrOpen(str(mtl_path))
        mtl_spec = mtl_layer.GetPrimAtPath(
            Sdf.Path("/chair/mtl/walnut/standard_surface"),
        )
        assert mtl_spec is None or mtl_spec.attributes.get("inputs:sheen") is None


def test_set_prim_attribute_supports_color_vec(tmp_path=None):
    """set_prim_attribute accepts a 3-list for Color3f / Vec3f attributes."""
    from pxr import Sdf
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chair = create_test_asset(tmp_path, "chair")
        state, project = make_state(tmp_path, "vec_attr")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "vec_attr"}))
        place = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(chair), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        prim_path = place.data["prim_path"]
        mesh_path = f"{prim_path}/asset/Mesh"
        asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path, "material_name": "x",
            "base_color_r": 0.5, "base_color_g": 0.5, "base_color_b": 0.5,
        }))

        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": f"{prim_path}/asset/mtl/x/standard_surface",
            "attribute_name": "inputs:base_color",
            "value": [0.1, 0.2, 0.9],
        }))
        assert r.success

        scene_layer = Sdf.Layer.FindOrOpen(str(project.scene_path))
        spec = scene_layer.GetPrimAtPath(
            Sdf.Path(f"{prim_path}/asset/mtl/x/standard_surface"),
        )
        color = tuple(float(c) for c in spec.attributes.get("inputs:base_color").default)
        assert abs(color[0] - 0.1) < 1e-5
        assert abs(color[1] - 0.2) < 1e-5
        assert abs(color[2] - 0.9) < 1e-5


def test_set_prim_attribute_per_instance_override_leaves_asset_untouched():
    """set_prim_attribute on both shaders authors a per-instance override only in scene.usda."""
    from pxr import Sdf
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chair = create_test_asset(tmp_path, "chair")
        state, project = make_state(tmp_path, "mtl_override")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "mtl_override"}))
        place = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(chair), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        prim_path = place.data["prim_path"]
        mesh_path = f"{prim_path}/asset/Mesh"

        r = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": mesh_path,
            "material_name": "walnut",
            "base_color_r": 0.4, "base_color_g": 0.2, "base_color_b": 0.1,
            "roughness": 0.7,
        }))
        assert r.success

        mtl_path = project.path / "assets" / "chair" / "mtl.usda"
        mtl_layer = Sdf.Layer.FindOrOpen(str(mtl_path))
        baseline_color = tuple(
            float(c) for c in mtl_layer.GetPrimAtPath(
                Sdf.Path("/chair/mtl/walnut/standard_surface"),
            ).attributes["inputs:base_color"].default
        )

        std_path = f"{prim_path}/asset/mtl/walnut/standard_surface"
        prev_path = f"{prim_path}/asset/mtl/walnut/preview_surface"
        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": std_path,
            "attribute_name": "inputs:base_color",
            "value": [0.0, 0.0, 1.0],
        }))
        assert r.success
        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": prev_path,
            "attribute_name": "inputs:diffuseColor",
            "value": [0.0, 0.0, 1.0],
        }))
        assert r.success

        mtl_layer_2 = Sdf.Layer.FindOrOpen(str(mtl_path))
        after_color = tuple(
            float(c) for c in mtl_layer_2.GetPrimAtPath(
                Sdf.Path("/chair/mtl/walnut/standard_surface"),
            ).attributes["inputs:base_color"].default
        )
        assert after_color == baseline_color

        scene_layer = Sdf.Layer.FindOrOpen(str(project.scene_path))
        std_over = scene_layer.GetPrimAtPath(Sdf.Path(std_path))
        prev_over = scene_layer.GetPrimAtPath(Sdf.Path(prev_path))
        assert std_over is not None and prev_over is not None
        std_override_color = tuple(
            float(c) for c in std_over.attributes["inputs:base_color"].default
        )
        prev_override_color = tuple(
            float(c) for c in prev_over.attributes["inputs:diffuseColor"].default
        )
        assert all(abs(a - b) < 1e-5 for a, b in zip(std_override_color, (0.0, 0.0, 1.0), strict=True))
        assert all(abs(a - b) < 1e-5 for a, b in zip(prev_override_color, (0.0, 0.0, 1.0), strict=True))


def test_set_prim_attribute_writes_to_scene_for_asset_light():
    """set_prim_attribute on an asset light writes to scene.usda; lgt.usda is untouched."""
    from pxr import Sdf
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chair = create_test_asset(tmp_path, "chair")
        state, project = make_state(tmp_path, "scene_write")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "scene_write"}))
        place = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(chair), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        prim_path = place.data["prim_path"]
        light_create = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": prim_path,
            "light_type": "SphereLight",
            "light_name": "Bulb",
            "intensity": 1000.0,
        }))
        assert light_create.success
        light_scene_path = light_create.data["prim_path"]

        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": light_scene_path,
            "attribute_name": "inputs:intensity",
            "value": 2500.0,
        }))
        assert r.success, r.error

        scene_layer = Sdf.Layer.FindOrOpen(str(project.scene_path))
        scene_spec = scene_layer.GetPrimAtPath(Sdf.Path(light_scene_path))
        assert scene_spec is not None
        assert abs(
            float(scene_spec.attributes["inputs:intensity"].default) - 2500.0,
        ) < 1e-5

        lgt_path = project.path / "assets" / "chair" / "lgt.usda"
        lgt_layer = Sdf.Layer.FindOrOpen(str(lgt_path))
        bulb = lgt_layer.GetPrimAtPath(Sdf.Path("/chair/lgt/Bulb"))
        assert abs(
            float(bulb.attributes["inputs:intensity"].default) - 1000.0,
        ) < 1e-5


def test_set_prim_attribute_null_clears_authored_opinion():
    """value=None on set_prim_attribute clears the authored override."""
    from pxr import Sdf
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chair = create_test_asset(tmp_path, "chair")
        state, project = make_state(tmp_path, "clear_attr")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "clear_attr"}))
        place = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(chair), "asset_name": "Chair",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        prim_path = place.data["prim_path"]
        light_create = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": prim_path,
            "light_type": "SphereLight",
            "light_name": "Bulb",
            "intensity": 1000.0,
        }))
        light_scene_path = light_create.data["prim_path"]

        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": light_scene_path,
            "attribute_name": "inputs:intensity",
            "value": 5000.0,
        }))
        assert r.success
        scene_layer = Sdf.Layer.FindOrOpen(str(project.scene_path))
        spec = scene_layer.GetPrimAtPath(Sdf.Path(light_scene_path))
        assert spec is not None
        assert "inputs:intensity" in spec.attributes

        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": light_scene_path,
            "attribute_name": "inputs:intensity",
            "value": None,
        }))
        assert r.success, r.error
        scene_layer_2 = Sdf.Layer.FindOrOpen(str(project.scene_path))
        spec_after = scene_layer_2.GetPrimAtPath(Sdf.Path(light_scene_path))
        assert spec_after is None or "inputs:intensity" not in spec_after.attributes



def test_bind_material_blocks_shared_container_without_confirm():
    """bind_material on an asset shared by 2+ scene instances refuses."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, _ = make_state(tmp_path)
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        sofa_asset = create_test_asset(source_dir, "sofa")
        material_path = source_dir / "wood.usda"
        mtl_stage = Usd.Stage.CreateNew(str(material_path))
        UsdGeom.SetStageMetersPerUnit(mtl_stage, 1.0)
        UsdGeom.SetStageUpAxis(mtl_stage, UsdGeom.Tokens.y)
        from pxr import UsdShade
        scope = mtl_stage.DefinePrim("/mtl", "Scope")
        mtl_stage.SetDefaultPrim(scope)
        UsdShade.Material.Define(mtl_stage, "/mtl/wood")
        mtl_stage.Save()

        first_sofa = _place_two_sofas_then_get_first_path(state, sofa_asset)

        result = asyncio.run(exec_tool(state, "bind_material", {
            "prim_path": f"{first_sofa}/asset/Mesh",
            "material_file": str(material_path),
            "material_prim_path": "/mtl/wood",
        }))
        assert result.success is False
        assert "2 scene instances" in result.error
        assert "place_asset" in result.error
        assert "confirm_shared_modification" in result.error


def test_bind_material_proceeds_with_confirm_flag():
    """bind_material with confirm_shared_modification=True succeeds on shared asset."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, _ = make_state(tmp_path)
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        sofa_asset = create_test_asset(source_dir, "sofa")
        material_path = source_dir / "wood.usda"
        mtl_stage = Usd.Stage.CreateNew(str(material_path))
        UsdGeom.SetStageMetersPerUnit(mtl_stage, 1.0)
        UsdGeom.SetStageUpAxis(mtl_stage, UsdGeom.Tokens.y)
        from pxr import UsdShade
        scope = mtl_stage.DefinePrim("/mtl", "Scope")
        mtl_stage.SetDefaultPrim(scope)
        UsdShade.Material.Define(mtl_stage, "/mtl/wood")
        mtl_stage.Save()

        first_sofa = _place_two_sofas_then_get_first_path(state, sofa_asset)

        result = asyncio.run(exec_tool(state, "bind_material", {
            "prim_path": f"{first_sofa}/asset/Mesh",
            "material_file": str(material_path),
            "material_prim_path": "/mtl/wood",
            "confirm_shared_modification": True,
        }))
        assert result.success, f"Expected success: {result.error}"


def test_create_material_blocks_shared_container_without_confirm():
    """create_material on an asset shared by 2+ scene instances refuses."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state, _ = make_state(tmp_path)
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        sofa_asset = create_test_asset(source_dir, "sofa")

        first_sofa = _place_two_sofas_then_get_first_path(state, sofa_asset)

        result = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": f"{first_sofa}/asset/Mesh",
            "material_name": "red_gloss",
            "base_color_r": 0.8, "base_color_g": 0.05, "base_color_b": 0.05,
        }))
        assert result.success is False
        assert "2 scene instances" in result.error
        assert "place_asset" in result.error
        assert "confirm_shared_modification" in result.error


def test_intaken_asset_uses_posix_relative_paths_only():
    """Cross-platform invariant: intaken assets author POSIX-relative paths."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        asset_path = create_test_asset(tmp_path, "table")

        state, project = make_state(tmp_path, "posix_test")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "posix_test"}))
        place = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset_path),
            "asset_name": "Table",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert place.success

        for usd_file in project.path.rglob("*.usda"):
            text = usd_file.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "@" in line and ".usda" in line:
                    assert "\\" not in line, (
                        f"Non-POSIX backslash in {usd_file}: {line!r}"
                    )

        print("test_intaken_asset_uses_posix_relative_paths_only PASSED")


def test_create_light_authors_light_link_collection():
    """create_light with light_link_includes authors a UsdLux light:link collection."""
    from pxr import Sdf, UsdLux
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        asset_path = create_test_asset(tmp_path, "hero")

        state, project = make_state(tmp_path, "linking_test")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "linking_test"}))
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset_path),
            "asset_name": "Hero",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        hero_path = placed.data["prim_path"]

        result = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "RectLight",
            "light_name": "Rim",
            "translate_x": 1.0, "translate_y": 1.5, "translate_z": 0.0,
            "intensity": 200.0,
            "light_link_includes": [hero_path],
        }))
        assert result.success

        stage = Usd.Stage.Open(str(project.scene_path))
        light_prim = stage.GetPrimAtPath(result.data["prim_path"])
        assert light_prim.IsValid()
        light_api = UsdLux.LightAPI(light_prim)
        link_collection = light_api.GetLightLinkCollectionAPI()
        targets = link_collection.GetIncludesRel().GetTargets()
        assert Sdf.Path(hero_path) in targets

        print("test_create_light_authors_light_link_collection PASSED")


def test_package_scene_apple_validation_blocks_on_udim_texture():
    """package_scene(for_apple=true) refuses when a shader uses a UDIM texture."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        from pxr import Sdf, UsdShade
        asset_path = create_test_asset(tmp_path, "table")

        state, _ = make_state(tmp_path, "apple_block")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "apple_block"}))
        asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset_path),
            "asset_name": "Table",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))

        scene_stage = Usd.Stage.Open(str(state.stage_path))
        material = UsdShade.Material.Define(
            scene_stage, "/Scene/Furniture/Table_01/asset/UDIM_Mat",
        )
        shader = UsdShade.Shader.Define(
            scene_stage, "/Scene/Furniture/Table_01/asset/UDIM_Mat/tex",
        )
        shader.CreateIdAttr("UsdUVTexture")
        shader.CreateInput(
            "file", Sdf.ValueTypeNames.Asset,
        ).Set(Sdf.AssetPath("./tex/diffuse.<UDIM>.png"))
        material.CreateSurfaceOutput().ConnectToSource(
            shader.CreateOutput("surface", Sdf.ValueTypeNames.Token),
        )
        scene_stage.Save()

        result = asyncio.run(exec_tool(state, "package_scene", {
            "for_apple_ar_quick_look": True,
        }))
        assert result.success
        assert result.data["usdz_path"] is None
        assert result.data["is_valid_for_apple"] is False
        messages = " ".join(i["message"] for i in result.data["apple_issues"])
        assert "UDIM" in messages

        print("test_package_scene_apple_validation_blocks_on_udim_texture PASSED")


def test_package_scene_default_does_not_run_apple_validation():
    """Default package_scene packages without Apple validation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        asset_path = create_test_asset(tmp_path, "table")

        state, _ = make_state(tmp_path, "apple_default")
        asyncio.run(exec_tool(state, "create_stage", {"filename": "apple_default"}))
        asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset_path),
            "asset_name": "Table",
            "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))

        result = asyncio.run(exec_tool(state, "package_scene", {}))
        assert result.success
        assert result.data["usdz_path"] is not None
        assert result.data["for_apple_ar_quick_look"] is False
        assert result.data["apple_issues"] == []

        print("test_package_scene_default_does_not_run_apple_validation PASSED")


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
    test_update_light_with_texture_copies_hdri_and_sets_attr()
    print("\nAll scene builder tests passed!")
