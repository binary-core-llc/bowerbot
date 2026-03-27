# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test material binding, look file support, and dependency resolution."""

import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom, UsdShade

from bowerbot.engine.dependency_resolver import DependencyResolver
from bowerbot.engine.stage_writer import StageWriter


# ── Helpers ──────────────────────────────────────────────────────


def create_test_geometry(directory: Path, name: str) -> Path:
    """Create a simple USD geometry asset."""
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, f"/{name}/Mesh")
    stage.Save()
    return path


def create_test_material(directory: Path, name: str) -> Path:
    """Create a material .usda file under /mtl/<name>."""
    path = directory / f"mtl_{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    scope = stage.DefinePrim("/mtl", "Scope")
    stage.SetDefaultPrim(scope)
    UsdShade.Material.Define(stage, f"/mtl/{name}")
    stage.Save()
    return path


def create_test_look_file(
    directory: Path,
    look_name: str,
    geometry_file: str,
    material_files: list[str],
) -> Path:
    """Create a look .usda that sublayers geometry + materials."""
    path = directory / f"{look_name}.usda"
    sub_layers = ",\n        ".join(
        f"@{m}@" for m in material_files + [geometry_file]
    )
    content = f"""#usda 1.0
(
    defaultPrim = "root"
    metersPerUnit = 1.0
    subLayers = [
        {sub_layers}
    ]
    upAxis = "Y"
)
"""
    path.write_text(content, encoding="utf-8")
    return path


# ── Dependency Resolver Tests ────────────────────────────────────


def test_resolver_finds_sublayers():
    """DependencyResolver finds all sublayered files."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mat_dir = tmp_path / "materials"
        mat_dir.mkdir()

        create_test_geometry(tmp_path, "table")
        create_test_material(mat_dir, "wood")
        create_test_material(mat_dir, "metal")
        look = create_test_look_file(
            tmp_path, "table_look", "table.usda",
            ["materials/mtl_wood.usda", "materials/mtl_metal.usda"],
        )

        resolver = DependencyResolver()
        found, missing = resolver.resolve(look)
        dep_names = {d.name for d in found}

        assert "table_look.usda" in dep_names
        assert "table.usda" in dep_names
        assert "mtl_wood.usda" in dep_names
        assert "mtl_metal.usda" in dep_names
        assert len(found) == 4
        assert len(missing) == 0


def test_resolver_handles_missing_file():
    """DependencyResolver reports missing dependencies."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        look = tmp_path / "look.usda"
        look.write_text(
            '#usda 1.0\n(\n    subLayers = [@missing.usda@]\n)\n',
            encoding="utf-8",
        )

        resolver = DependencyResolver()
        found, missing = resolver.resolve(look)
        assert len(found) == 1
        assert found[0].name == "look.usda"
        assert len(missing) == 1
        assert missing[0].name == "missing.usda"


def test_resolver_handles_circular():
    """DependencyResolver does not loop on circular sublayer references."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        a = tmp_path / "a.usda"
        b = tmp_path / "b.usda"
        a.write_text(
            '#usda 1.0\n(\n    subLayers = [@b.usda@]\n)\n',
            encoding="utf-8",
        )
        b.write_text(
            '#usda 1.0\n(\n    subLayers = [@a.usda@]\n)\n',
            encoding="utf-8",
        )

        resolver = DependencyResolver()
        found, missing = resolver.resolve(a)
        assert len(found) == 2


def test_resolver_find_first_material():
    """find_first_material returns the prim path of the first Material."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mat = create_test_material(tmp_path, "wood")

        result = DependencyResolver.find_first_material(mat)
        assert result == "/mtl/wood"


# ── StageWriter Material Tests ───────────────────────────────────


def test_add_material_sublayer():
    """add_material_sublayer adds the path and deduplicates."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stage_path = tmp_path / "scene.usda"

        writer = StageWriter()
        writer.create_stage(stage_path)

        writer.add_material_sublayer("assets/materials/mtl_wood.usda")
        writer.add_material_sublayer("assets/materials/mtl_wood.usda")  # duplicate
        writer.add_material_sublayer("assets/materials/mtl_metal.usda")
        writer.save()

        stage = Usd.Stage.Open(str(stage_path))
        sublayers = list(stage.GetRootLayer().subLayerPaths)
        assert sublayers.count("assets/materials/mtl_wood.usda") == 1
        assert "assets/materials/mtl_metal.usda" in sublayers


def test_bind_material():
    """bind_material writes a material:binding relationship."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        mat_dir = assets_dir / "materials"
        mat_dir.mkdir()

        # Create geometry and material
        geo = create_test_geometry(assets_dir, "table")
        mat = create_test_material(mat_dir, "wood")

        # Create stage, add reference, sublayer material
        stage_path = tmp_path / "scene.usda"
        writer = StageWriter()
        writer.create_stage(stage_path)

        from bowerbot.schemas import AssetMetadata, SceneObject
        writer.add_reference(SceneObject(
            prim_path="/Scene/Furniture/Table_01",
            asset=AssetMetadata(
                name="table", source_skill="local",
                source_id="x", file_path="assets/table.usda",
            ),
        ))

        writer.add_material_sublayer("assets/materials/mtl_wood.usda")
        writer.save()

        # Reopen to compose the sublayer
        writer.open_stage(stage_path)

        writer.bind_material("/Scene/Furniture/Table_01", "/mtl/wood")
        writer.save()

        # Verify binding
        stage = Usd.Stage.Open(str(stage_path))
        prim = stage.GetPrimAtPath("/Scene/Furniture/Table_01")
        binding_api = UsdShade.MaterialBindingAPI(prim)
        mat, _ = binding_api.ComputeBoundMaterial()
        assert mat is not None
        assert str(mat.GetPath()) == "/mtl/wood"


def test_clear_material_bindings():
    """clear_material_bindings removes binding opinions."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        mat_dir = assets_dir / "materials"
        mat_dir.mkdir()

        geo = create_test_geometry(assets_dir, "table")
        mat = create_test_material(mat_dir, "wood")

        stage_path = tmp_path / "scene.usda"
        writer = StageWriter()
        writer.create_stage(stage_path)

        from bowerbot.schemas import AssetMetadata, SceneObject
        writer.add_reference(SceneObject(
            prim_path="/Scene/Furniture/Table_01",
            asset=AssetMetadata(
                name="table", source_skill="local",
                source_id="x", file_path="assets/table.usda",
            ),
        ))
        writer.add_material_sublayer("assets/materials/mtl_wood.usda")
        writer.save()
        writer.open_stage(stage_path)

        writer.bind_material("/Scene/Furniture/Table_01", "/mtl/wood")
        writer.clear_material_bindings("/Scene/Furniture/Table_01")
        writer.save()

        # Verify binding is removed
        stage = Usd.Stage.Open(str(stage_path))
        prim = stage.GetPrimAtPath("/Scene/Furniture/Table_01")
        binding_api = UsdShade.MaterialBindingAPI(prim)
        mat, _ = binding_api.ComputeBoundMaterial()
        assert mat is None or not mat.GetPath()


def test_swap_reference_preserves_transform():
    """swap_reference changes the asset but keeps translate/rotate/scale."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()

        geo = create_test_geometry(assets_dir, "table")
        look = create_test_geometry(assets_dir, "table_look")  # stand-in

        stage_path = tmp_path / "scene.usda"
        writer = StageWriter()
        writer.create_stage(stage_path)

        from bowerbot.schemas import AssetMetadata, SceneObject
        writer.add_reference(SceneObject(
            prim_path="/Scene/Furniture/Table_01",
            asset=AssetMetadata(
                name="table", source_skill="local",
                source_id="x", file_path="assets/table.usda",
            ),
            translate=(3.0, 0.0, 4.0),
            rotate=(0.0, 45.0, 0.0),
        ))
        writer.save()

        writer.swap_reference("/Scene/Furniture/Table_01", "assets/table_look.usda")
        writer.save()

        # Verify transform preserved
        stage = Usd.Stage.Open(str(stage_path))
        prim = stage.GetPrimAtPath("/Scene/Furniture/Table_01")
        xf = UsdGeom.Xformable(prim)
        t = xf.GetLocalTransformation().ExtractTranslation()
        assert abs(t[0] - 3.0) < 0.01
        assert abs(t[2] - 4.0) < 0.01

        # Verify reference changed
        refs = prim.GetMetadata("references")
        found = False
        for ref_list in [refs.prependedItems, refs.appendedItems, refs.explicitItems]:
            if ref_list:
                for ref in ref_list:
                    if "table_look" in ref.assetPath:
                        found = True
        assert found, "Reference was not swapped"


def test_list_materials():
    """list_materials returns materials and their bindings."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        mat_dir = assets_dir / "materials"
        mat_dir.mkdir()

        create_test_geometry(assets_dir, "table")
        create_test_material(mat_dir, "wood")

        stage_path = tmp_path / "scene.usda"
        writer = StageWriter()
        writer.create_stage(stage_path)

        from bowerbot.schemas import AssetMetadata, SceneObject
        writer.add_reference(SceneObject(
            prim_path="/Scene/Furniture/Table_01",
            asset=AssetMetadata(
                name="table", source_skill="local",
                source_id="x", file_path="assets/table.usda",
            ),
        ))
        writer.add_material_sublayer("assets/materials/mtl_wood.usda")
        writer.save()
        writer.open_stage(stage_path)

        writer.bind_material("/Scene/Furniture/Table_01", "/mtl/wood")
        writer.save()

        materials = writer.list_materials()
        assert len(materials) >= 1
        wood = [m for m in materials if m["material_name"] == "wood"]
        assert len(wood) == 1
        assert "/Scene/Furniture/Table_01" in wood[0]["bound_prims"]


def test_shared_material_deduplication():
    """Same material sublayered twice appears only once."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stage_path = tmp_path / "scene.usda"

        writer = StageWriter()
        writer.create_stage(stage_path)

        writer.add_material_sublayer("assets/materials/mtl_wood.usda")
        writer.add_material_sublayer("assets/materials/mtl_wood.usda")
        writer.save()

        stage = Usd.Stage.Open(str(stage_path))
        sublayers = list(stage.GetRootLayer().subLayerPaths)
        wood_entries = [s for s in sublayers if "mtl_wood" in s]
        assert len(wood_entries) == 1
