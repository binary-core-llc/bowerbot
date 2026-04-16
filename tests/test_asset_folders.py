# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test ASWF asset folder detection, placement, and incremental assembly."""

import tempfile
import asyncio
from pathlib import Path

from pxr import Usd, UsdGeom, UsdLux, UsdShade

from bowerbot.schemas import (
    ASWFLayerNames,
    LightParams,
    LightType,
    TransformParams,
)
from bowerbot.services import (
    asset_service,
    dependency_service,
    light_service,
    material_service,
    nested_service,
)
from bowerbot.skills.local.local import LocalSkill


# ── Helpers ─────────────────


def create_geometry(directory: Path, name: str) -> Path:
    """Create a simple geometry .usda file."""
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, f"/{name}/top")
    UsdGeom.Cube.Define(stage, f"/{name}/legs")
    stage.Save()
    return path


def create_material(directory: Path, name: str) -> Path:
    """Create a material .usda file under /mtl/<name>."""
    path = directory / f"mtl_{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    scope = stage.DefinePrim("/mtl", "Scope")
    stage.SetDefaultPrim(scope)
    UsdShade.Material.Define(stage, f"/mtl/{name}")
    stage.Save()
    return path


def create_aswf_folder(parent_dir: Path, name: str) -> Path:
    """Create a minimal ASWF asset folder and return the root file."""
    asset_dir = parent_dir / name
    asset_dir.mkdir(parents=True, exist_ok=True)

    geo_path = asset_dir / "geo.usda"
    geo_stage = Usd.Stage.CreateNew(str(geo_path))
    UsdGeom.SetStageMetersPerUnit(geo_stage, 1.0)
    UsdGeom.SetStageUpAxis(geo_stage, UsdGeom.Tokens.y)
    root = geo_stage.DefinePrim(f"/{name}", "Xform")
    geo_stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(geo_stage, f"/{name}/Mesh")
    geo_stage.Save()

    mtl_path = asset_dir / "mtl.usda"
    mtl_stage = Usd.Stage.CreateNew(str(mtl_path))
    UsdGeom.SetStageMetersPerUnit(mtl_stage, 1.0)
    UsdGeom.SetStageUpAxis(mtl_stage, UsdGeom.Tokens.y)
    mtl_stage.Save()

    root_path = asset_dir / f"{name}.usda"
    root_stage = Usd.Stage.CreateNew(str(root_path))
    UsdGeom.SetStageMetersPerUnit(root_stage, 1.0)
    UsdGeom.SetStageUpAxis(root_stage, UsdGeom.Tokens.y)
    root_prim = root_stage.DefinePrim(f"/{name}", "Xform")
    root_stage.SetDefaultPrim(root_prim)
    root_prim.GetReferences().AddReference("./mtl.usda")
    root_prim.GetReferences().AddReference("./geo.usda")
    root_stage.Save()

    return root_path


# ── Asset Folder Detection (Local Skill) ─


def test_detect_asset_folder():
    """Local skill detects an ASWF folder as a single 'package' asset."""
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = Path(tmp) / "assets"
        assets_dir.mkdir()
        create_aswf_folder(assets_dir, "single_table")

        skill = LocalSkill()
        skill._assets_dir = assets_dir

        result = asyncio.run(skill.execute("list_assets", {}))

        assert result.success
        names = {e["name"] for e in result.data}
        categories = {e["category"] for e in result.data}

        assert "single_table" in names
        assert "package" in categories
        assert "geo" not in names
        assert "mtl" not in names


def test_detect_mixed_assets():
    """Asset folders and loose files coexist correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = Path(tmp) / "assets"
        assets_dir.mkdir()

        create_aswf_folder(assets_dir, "single_table")
        create_geometry(assets_dir, "loose_chair")
        create_material(assets_dir, "wood")

        skill = LocalSkill()
        skill._assets_dir = assets_dir

        result = asyncio.run(skill.execute("list_assets", {}))

        assert result.success
        names = {e["name"] for e in result.data}
        assert "single_table" in names
        assert "loose_chair" in names
        assert "mtl_wood" in names
        assert len(result.data) == 3


def test_search_package_by_name():
    """search_assets finds packages by keyword."""
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = Path(tmp) / "assets"
        assets_dir.mkdir()
        create_aswf_folder(assets_dir, "single_table")

        skill = LocalSkill()
        skill._assets_dir = assets_dir

        result = asyncio.run(skill.execute(
            "search_assets", {"query": "table"},
        ))

        assert result.success
        assert len(result.data) == 1
        assert result.data[0]["category"] == "package"


def test_search_filter_by_category():
    """search_assets with category filter works."""
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = Path(tmp) / "assets"
        assets_dir.mkdir()

        create_aswf_folder(assets_dir, "single_table")
        create_geometry(assets_dir, "chair")

        skill = LocalSkill()
        skill._assets_dir = assets_dir

        result = asyncio.run(skill.execute(
            "search_assets",
            {"query": "", "category": "package"},
        ))

        assert result.success
        assert all(e["category"] == "package" for e in result.data)


# ── asset_service: Create Folder ─


def test_create_asset_folder():
    """create_asset_folder produces root + geo.usd."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")

        root = asset_service.create_asset_folder(
            output_dir=output_dir,
            asset_name="table",
            geometry_file=geo,
        )

        assert root.exists()
        assert root.name == "table.usda"
        assert root.parent.name == "table"
        assert (root.parent / "geo.usda").exists()
        assert not (root.parent / "mtl.usda").exists()

        # Root should reference geo.usd on the defaultPrim
        stage = Usd.Stage.Open(str(root))
        default_prim = stage.GetDefaultPrim()
        assert default_prim is not None
        refs = default_prim.GetMetadata("references")
        ref_paths = []
        if refs:
            for ref_list in (refs.prependedItems, refs.appendedItems, refs.explicitItems):
                if ref_list:
                    ref_paths.extend(r.assetPath for r in ref_list)
        assert "./geo.usda" in ref_paths
        assert "./mtl.usda" not in ref_paths


# ── material_service: Add Material ─


def test_add_material_creates_mtl():
    """add_material creates mtl.usd and updates root file."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")
        mat = create_material(source_dir, "wood")

        root = asset_service.create_asset_folder(
            output_dir, "table", geo,
        )

        material_service.add_material(
            asset_dir=root.parent,
            material_file=mat,
            prim_path="/table/top",
            material_prim_path="/mtl/wood",
        )

        # mtl.usd should exist now
        assert (root.parent / "mtl.usda").exists()

        # Root should now reference mtl.usd
        stage = Usd.Stage.Open(str(root))
        default_prim = stage.GetDefaultPrim()
        refs = default_prim.GetMetadata("references")
        ref_paths = []
        if refs:
            for ref_list in (refs.prependedItems, refs.appendedItems, refs.explicitItems):
                if ref_list:
                    ref_paths.extend(r.assetPath for r in ref_list)
        assert "./mtl.usda" in ref_paths

        # Material should be defined inline in mtl.usd under /table/mtl/
        mtl_stage = Usd.Stage.Open(str(root.parent / "mtl.usda"))
        mat_prim = mtl_stage.GetPrimAtPath("/table/mtl/wood")
        assert mat_prim.IsValid()
        assert mat_prim.IsA(UsdShade.Material)


def test_add_material_with_binding():
    """add_material creates binding that resolves through composition."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")
        mat = create_material(source_dir, "wood")

        root = asset_service.create_asset_folder(
            output_dir, "table", geo,
        )
        material_service.add_material(
            root.parent, mat, "/table/top", "/mtl/wood",
        )

        # Open composed root and check binding
        stage = Usd.Stage.Open(str(root))
        prim = stage.GetPrimAtPath("/table/top")
        assert prim.IsValid()

        binding_api = UsdShade.MaterialBindingAPI(prim)
        bound_mat, _ = binding_api.ComputeBoundMaterial()
        assert bound_mat is not None
        assert str(bound_mat.GetPath()) == "/table/mtl/wood"


def test_add_multiple_materials():
    """Multiple materials coexist in mtl.usd."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")
        mat_wood = create_material(source_dir, "wood")
        mat_metal = create_material(source_dir, "metal")

        root = asset_service.create_asset_folder(
            output_dir, "table", geo,
        )
        material_service.add_material(
            root.parent, mat_wood, "/table/top", "/mtl/wood",
        )
        material_service.add_material(
            root.parent, mat_metal, "/table/legs", "/mtl/metal",
        )

        # Both materials in mtl.usd under /table/mtl/
        mtl_stage = Usd.Stage.Open(str(root.parent / "mtl.usda"))
        assert mtl_stage.GetPrimAtPath("/table/mtl/wood").IsValid()
        assert mtl_stage.GetPrimAtPath("/table/mtl/metal").IsValid()

        # Both bindings resolve
        stage = Usd.Stage.Open(str(root))
        top_api = UsdShade.MaterialBindingAPI(
            stage.GetPrimAtPath("/table/top"),
        )
        top_mat, _ = top_api.ComputeBoundMaterial()
        assert str(top_mat.GetPath()) == "/table/mtl/wood"

        legs_api = UsdShade.MaterialBindingAPI(
            stage.GetPrimAtPath("/table/legs"),
        )
        legs_mat, _ = legs_api.ComputeBoundMaterial()
        assert str(legs_mat.GetPath()) == "/table/mtl/metal"


def test_add_material_discovers_prim_path():
    """add_material auto-discovers material prim path if not provided."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")
        mat = create_material(source_dir, "wood")

        root = asset_service.create_asset_folder(
            output_dir, "table", geo,
        )

        result_path = material_service.add_material(
            asset_dir=root.parent,
            material_file=mat,
            prim_path="/table/top",
            material_prim_path=None,  # auto-discover
        )

        assert result_path == "/table/mtl/wood"


# ── material_service: Remove Material ─


def test_remove_material_binding():
    """remove_material_binding clears binding and cleans up."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")
        mat = create_material(source_dir, "wood")

        root = asset_service.create_asset_folder(
            output_dir, "table", geo,
        )
        material_service.add_material(
            root.parent, mat, "/table/top", "/mtl/wood",
        )

        # Remove the binding
        material_service.remove_material_binding(root.parent, "/table/top")

        # mtl.usd should be deleted (no materials left)
        assert not (root.parent / "mtl.usda").exists()

        # Root should no longer reference mtl.usd
        stage = Usd.Stage.Open(str(root))
        default_prim = stage.GetDefaultPrim()
        refs = default_prim.GetMetadata("references")
        ref_paths = []
        if refs:
            for ref_list in (refs.prependedItems, refs.appendedItems, refs.explicitItems):
                if ref_list:
                    ref_paths.extend(r.assetPath for r in ref_list)
        assert "./mtl.usda" not in ref_paths
        assert "./geo.usda" in ref_paths


# ── material_service: List Materials ─


def test_list_materials():
    """list_materials returns materials from the asset folder."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")
        mat = create_material(source_dir, "wood")

        root = asset_service.create_asset_folder(
            output_dir, "table", geo,
        )
        material_service.add_material(
            root.parent, mat, "/table/top", "/mtl/wood",
        )

        materials = material_service.list_materials(root.parent)
        assert len(materials) >= 1
        wood = [m for m in materials if m["material_name"] == "wood"]
        assert len(wood) == 1
        assert "/table/top" in wood[0]["bound_prims"]


# ── dependency_service ─


def test_validate_asset_folder_valid():
    """validate_asset_folder passes for a complete folder."""
    with tempfile.TemporaryDirectory() as tmp:
        root_file = create_aswf_folder(Path(tmp), "single_table")

        is_valid, errors = dependency_service.validate_asset_folder(root_file)

        assert is_valid
        assert len(errors) == 0


def test_validate_asset_folder_missing_dep():
    """validate_asset_folder reports missing dependencies."""
    with tempfile.TemporaryDirectory() as tmp:
        asset_dir = Path(tmp) / "table"
        asset_dir.mkdir()

        root_path = asset_dir / "table.usda"
        root_path.write_text(
            '#usda 1.0\n(\n    subLayers = [@./geo.usd@]\n)\n',
            encoding="utf-8",
        )

        is_valid, errors = dependency_service.validate_asset_folder(root_path)

        assert not is_valid
        assert any("geo.usd" in e for e in errors)


# ── Placement Helper ─


def test_is_asset_folder_root():
    """is_asset_folder_root identifies ASWF root files."""
    assert asset_service.is_asset_folder_root(
        Path("/assets/table/table.usd"),
    )
    assert asset_service.is_asset_folder_root(
        Path("/assets/chair/chair.usda"),
    )
    assert not asset_service.is_asset_folder_root(
        Path("/assets/table.usdz"),
    )
    assert not asset_service.is_asset_folder_root(
        Path("/assets/table/geo.usd"),
    )


# ── Asset-Level Lights (light_service) ─


def test_add_light_creates_lgt():
    """add_light creates lgt.usda and updates root file."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "lamp")

        root = asset_service.create_asset_folder(
            output_dir, "lamp", geo,
        )

        light_service.add_light(
            asset_dir=root.parent,
            light_name="bulb",
            light=LightParams(
                light_type=LightType.SPHERE,
                translate=(0.0, 0.5, 0.0),
                intensity=500.0,
                radius=0.05,
            ),
        )

        # lgt.usda should exist
        assert (root.parent / "lgt.usda").exists()

        # Root should reference lgt.usda
        stage = Usd.Stage.Open(str(root))
        default_prim = stage.GetDefaultPrim()
        refs = default_prim.GetMetadata("references")
        ref_paths = []
        if refs:
            for ref_list in (
                refs.prependedItems,
                refs.appendedItems,
                refs.explicitItems,
            ):
                if ref_list:
                    ref_paths.extend(r.assetPath for r in ref_list)
        assert "./lgt.usda" in ref_paths

        # Light should exist in composed stage
        found_light = False
        for prim in stage.Traverse():
            if prim.HasAPI(UsdLux.LightAPI):
                found_light = True
                assert "bulb" in prim.GetName()
        assert found_light


def test_add_multiple_lights():
    """Multiple lights coexist in lgt.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "lamp")

        root = asset_service.create_asset_folder(
            output_dir, "lamp", geo,
        )

        light_service.add_light(
            root.parent, "bulb",
            LightParams(
                light_type=LightType.SPHERE,
                translate=(0.0, 0.5, 0.0),
                radius=0.05,
            ),
        )
        light_service.add_light(
            root.parent, "glow",
            LightParams(
                light_type=LightType.DISK,
                translate=(0.0, 0.3, 0.0),
                radius=0.1,
            ),
        )

        lights = light_service.list_lights(root.parent)
        assert len(lights) == 2
        names = {l["name"] for l in lights}
        assert "bulb" in names
        assert "glow" in names


def test_remove_light():
    """remove_light removes the light and cleans up lgt.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "lamp")

        root = asset_service.create_asset_folder(
            output_dir, "lamp", geo,
        )

        light_service.add_light(
            root.parent, "bulb",
            LightParams(
                light_type=LightType.SPHERE,
                translate=(0.0, 0.5, 0.0),
            ),
        )
        light_service.remove_light(root.parent, "bulb")

        # lgt.usda should be deleted (no lights left)
        assert not (root.parent / "lgt.usda").exists()

        # Root should no longer reference lgt.usda
        stage = Usd.Stage.Open(str(root))
        default_prim = stage.GetDefaultPrim()
        refs = default_prim.GetMetadata("references")
        ref_paths = []
        if refs:
            for ref_list in (
                refs.prependedItems,
                refs.appendedItems,
                refs.explicitItems,
            ):
                if ref_list:
                    ref_paths.extend(r.assetPath for r in ref_list)
        assert "./lgt.usda" not in ref_paths


def test_disk_light_rotation_facing_down():
    """DiskLight with rotate_x=-90 should face downward."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")

        root = asset_service.create_asset_folder(
            output_dir, "table", geo,
        )

        light_service.add_light(
            asset_dir=root.parent,
            light_name="downlight",
            light=LightParams(
                light_type=LightType.DISK,
                translate=(0.0, 1.0, 0.0),
                rotate=(-90.0, 0.0, 0.0),
                intensity=1000.0,
                radius=0.3,
            ),
        )

        # Open lgt.usda and verify rotation
        lgt_path = root.parent / "lgt.usda"
        assert lgt_path.exists()

        stage = Usd.Stage.Open(str(lgt_path))
        prim = stage.GetPrimAtPath("/table/lgt/downlight")
        assert prim.IsValid()

        xf = UsdGeom.Xformable(prim)
        ops = xf.GetOrderedXformOps()
        op_names = [op.GetOpName() for op in ops]
        assert "xformOp:rotateXYZ" in op_names

        for op in ops:
            if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                rot = op.Get()
                assert rot[0] == -90.0
                assert rot[1] == 0.0
                assert rot[2] == 0.0


def test_rect_light_rotation_facing_right():
    """RectLight with rotate_y=-90 should face right."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "wall")

        root = asset_service.create_asset_folder(
            output_dir, "wall", geo,
        )

        light_service.add_light(
            asset_dir=root.parent,
            light_name="sidelight",
            light=LightParams(
                light_type=LightType.RECT,
                translate=(0.5, 0.0, 0.0),
                rotate=(0.0, -90.0, 0.0),
                intensity=800.0,
                width=0.5,
                height=0.5,
            ),
        )

        lgt_path = root.parent / "lgt.usda"
        stage = Usd.Stage.Open(str(lgt_path))
        prim = stage.GetPrimAtPath("/wall/lgt/sidelight")
        assert prim.IsValid()

        xf = UsdGeom.Xformable(prim)
        for op in xf.GetOrderedXformOps():
            if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                rot = op.Get()
                assert rot[1] == -90.0


def test_update_light_position_offset():
    """update_light should correctly update translate values."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "lamp")

        root = asset_service.create_asset_folder(
            output_dir, "lamp", geo,
        )

        # Create light at initial position
        light_service.add_light(
            asset_dir=root.parent,
            light_name="spot",
            light=LightParams(
                light_type=LightType.DISK,
                translate=(0.0, 1.0, 0.0),
                rotate=(-90.0, 0.0, 0.0),
                intensity=1000.0,
            ),
        )

        # Update position
        light_service.update_light(
            asset_dir=root.parent,
            light_name="spot",
            translate=(0.5, 2.0, -0.3),
        )

        lgt_path = root.parent / "lgt.usda"
        stage = Usd.Stage.Open(str(lgt_path))
        prim = stage.GetPrimAtPath("/lamp/lgt/spot")
        assert prim.IsValid()

        xf = UsdGeom.Xformable(prim)
        for op in xf.GetOrderedXformOps():
            if op.GetOpName() == "xformOp:translate":
                pos = op.Get()
                # Geometry is in cm (mpu=0.01), so values
                # should be scaled by 1/0.01 = 100
                assert pos[0] == 50.0  # 0.5 * 100
                assert pos[1] == 200.0  # 2.0 * 100
                assert pos[2] == -30.0  # -0.3 * 100
                break
        else:
            raise AssertionError("No translate op found")


def test_update_light_rotation():
    """update_light should correctly update rotation values."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "lamp")

        root = asset_service.create_asset_folder(
            output_dir, "lamp", geo,
        )

        # Create light facing down
        light_service.add_light(
            asset_dir=root.parent,
            light_name="spot",
            light=LightParams(
                light_type=LightType.DISK,
                translate=(0.0, 1.0, 0.0),
                rotate=(-90.0, 0.0, 0.0),
                intensity=1000.0,
            ),
        )

        # Update rotation to face right
        light_service.update_light(
            asset_dir=root.parent,
            light_name="spot",
            rotate=(0.0, -90.0, 0.0),
        )

        lgt_path = root.parent / "lgt.usda"
        stage = Usd.Stage.Open(str(lgt_path))
        prim = stage.GetPrimAtPath("/lamp/lgt/spot")
        assert prim.IsValid()

        xf = UsdGeom.Xformable(prim)
        for op in xf.GetOrderedXformOps():
            if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                rot = op.Get()
                assert rot[0] == 0.0
                assert rot[1] == -90.0
                assert rot[2] == 0.0
                break
        else:
            raise AssertionError("No rotateXYZ op found")


# ── Nested Asset Placement (nested_service) ─


def test_add_nested_asset_reference_creates_contents():
    """add_nested_asset_reference writes a reference into contents.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()

        container_root = create_aswf_folder(assets_dir, "building")
        nested_root = create_aswf_folder(assets_dir, "counter_table")
        container_dir = container_root.parent

        ref_asset_path = (
            f"../{nested_root.parent.name}/{nested_root.name}"
        )

        prim_path = nested_service.add_nested_asset_reference(
            container_dir=container_dir,
            group="Furniture",
            prim_name="Counter_01",
            ref_asset_path=ref_asset_path,
            transform=TransformParams(
                translate=(1.0, 0.0, 2.0),
                rotate=(0.0, 90.0, 0.0),
            ),
        )

        # contents.usda exists and has the correct prim
        contents_path = container_dir / ASWFLayerNames.CONTENTS
        assert contents_path.exists()
        assert prim_path.endswith("/contents/Furniture/Counter_01")

        # Root file references contents.usda
        stage = Usd.Stage.Open(str(container_root))
        composed = stage.GetPrimAtPath(prim_path)
        assert composed.IsValid(), (
            f"Composed prim not found at {prim_path}"
        )

        # Transform is applied
        xf = UsdGeom.Xformable(composed)
        translate = xf.GetLocalTransformation().ExtractTranslation()
        assert abs(translate[0] - 1.0) < 0.01
        assert abs(translate[2] - 2.0) < 0.01


def test_nested_reference_composed_in_scene():
    """Nested reference resolves correctly when the container is
    itself referenced by a scene."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()

        container_root = create_aswf_folder(assets_dir, "building")
        nested_root = create_aswf_folder(assets_dir, "counter_table")
        container_dir = container_root.parent

        nested_service.add_nested_asset_reference(
            container_dir=container_dir,
            group="Furniture",
            prim_name="Counter_01",
            ref_asset_path=f"../{nested_root.parent.name}/{nested_root.name}",
            transform=TransformParams(translate=(0.5, 0.0, 0.0)),
        )

        # Compose the container as if placed in a scene
        scene_path = tmp_path / "scene.usda"
        scene_stage = Usd.Stage.CreateNew(str(scene_path))
        UsdGeom.SetStageMetersPerUnit(scene_stage, 1.0)
        UsdGeom.SetStageUpAxis(scene_stage, UsdGeom.Tokens.y)
        scene_root = scene_stage.DefinePrim("/Scene", "Xform")
        scene_stage.SetDefaultPrim(scene_root)
        building_prim = scene_stage.DefinePrim(
            "/Scene/Building_01", "Xform",
        )
        rel = container_root.relative_to(tmp_path).as_posix()
        building_prim.GetReferences().AddReference(f"./{rel}")
        scene_stage.Save()

        scene_stage = Usd.Stage.Open(str(scene_path))
        nested_composed = scene_stage.GetPrimAtPath(
            "/Scene/Building_01/contents/Furniture/Counter_01",
        )
        assert nested_composed.IsValid(), (
            "Nested reference not resolved in scene composition"
        )
