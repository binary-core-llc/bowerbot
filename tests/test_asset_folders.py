# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test ASWF asset folder detection, placement, and incremental assembly."""

import tempfile
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdLux, UsdShade

from bowerbot.schemas import (
    ASWFLayerNames,
    LightParams,
    LightType,
    TransformParams,
)
from bowerbot.utils import (
    asset_intake_utils,
    dependency_utils,
    light_utils,
    material_utils,
)
from bowerbot.utils.asset_folder_utils import to_layer_local_path

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


# ── asset_service: Create Folder ─


def test_create_asset_folder():
    """create_asset_folder produces root + geo.usd; geo composed via payload."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")

        root = asset_intake_utils.create_asset_folder(
            output_dir=output_dir,
            asset_name="table",
            geometry_file=geo,
        )

        assert root.exists()
        assert root.name == "table.usda"
        assert root.parent.name == "table"
        assert (root.parent / "geo.usda").exists()
        assert not (root.parent / "mtl.usda").exists()

        stage = Usd.Stage.Open(str(root))
        default_prim = stage.GetDefaultPrim()
        assert default_prim is not None

        ref_paths = []
        refs = default_prim.GetMetadata("references")
        if refs:
            for ref_list in (refs.prependedItems, refs.appendedItems, refs.explicitItems):
                if ref_list:
                    ref_paths.extend(r.assetPath for r in ref_list)
        assert "./geo.usda" not in ref_paths
        assert "./mtl.usda" not in ref_paths

        payload_paths = []
        payloads = default_prim.GetMetadata("payload")
        if payloads:
            for pl_list in (
                payloads.prependedItems,
                payloads.appendedItems,
                payloads.explicitItems,
            ):
                if pl_list:
                    payload_paths.extend(p.assetPath for p in pl_list)
        assert "./geo.usda" in payload_paths


def test_intake_folder_normalises_geo_to_payload():
    """Folder intake rewrites geo as a payload arc on the canonical root."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "couch"
        source.mkdir()

        geo_path = source / "geo.usda"
        geo_stage = Usd.Stage.CreateNew(str(geo_path))
        UsdGeom.SetStageMetersPerUnit(geo_stage, 1.0)
        UsdGeom.SetStageUpAxis(geo_stage, UsdGeom.Tokens.y)
        geo_root = geo_stage.DefinePrim("/couch", "Xform")
        geo_stage.SetDefaultPrim(geo_root)
        UsdGeom.Cube.Define(geo_stage, "/couch/Mesh")
        geo_stage.Save()

        root_path = source / "couch.usda"
        root_stage = Usd.Stage.CreateNew(str(root_path))
        UsdGeom.SetStageMetersPerUnit(root_stage, 1.0)
        UsdGeom.SetStageUpAxis(root_stage, UsdGeom.Tokens.y)
        root_prim = root_stage.DefinePrim("/couch", "Xform")
        root_stage.SetDefaultPrim(root_prim)
        root_prim.GetReferences().AddReference("./geo.usda")
        root_stage.Save()

        assets_dir = tmp_path / "project_assets"
        assets_dir.mkdir()
        report = asset_intake_utils.intake_folder(source, assets_dir)

        canonical = assets_dir / report.asset_folder_name / report.root_canonical_name
        composed = Usd.Stage.Open(str(canonical))
        default_prim = composed.GetDefaultPrim()

        ref_paths = []
        refs = default_prim.GetMetadata("references")
        if refs:
            for rl in (refs.prependedItems, refs.appendedItems, refs.explicitItems):
                if rl:
                    ref_paths.extend(r.assetPath for r in rl)
        assert "./geo.usda" not in ref_paths

        payload_paths = []
        payloads = default_prim.GetMetadata("payload")
        if payloads:
            for pl in (payloads.prependedItems, payloads.appendedItems, payloads.explicitItems):
                if pl:
                    payload_paths.extend(p.assetPath for p in pl)
        assert "./geo.usda" in payload_paths


def test_create_asset_folder_sets_kind_and_asset_info():
    """create_asset_folder authors kind=component + assetInfo on the root."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()
        geo = create_geometry(source_dir, "chair")

        root = asset_intake_utils.create_asset_folder(
            output_dir=output_dir, asset_name="chair", geometry_file=geo,
        )

        stage = Usd.Stage.Open(str(root))
        default_prim = stage.GetDefaultPrim()
        assert Usd.ModelAPI(default_prim).GetKind() == "component"

        info = default_prim.GetAssetInfo()
        assert info is not None
        assert info["name"] == "chair"
        assert info["version"] == "1.0"
        assert info["identifier"].path == "./chair.usda"


def test_create_asset_folder_authors_class_prim_with_inherits():
    """Asset root has a class _class_<name> sibling; defaultPrim inherits it."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()
        geo = create_geometry(source_dir, "lamp")

        root = asset_intake_utils.create_asset_folder(
            output_dir, "lamp", geo,
        )

        layer = Sdf.Layer.FindOrOpen(str(root))
        class_spec = layer.GetPrimAtPath(Sdf.Path("/_class_lamp"))
        assert class_spec is not None
        assert class_spec.specifier == Sdf.SpecifierClass

        root_spec = layer.GetPrimAtPath(Sdf.Path("/lamp"))
        inherits = root_spec.inheritPathList.prependedItems
        assert Sdf.Path("/_class_lamp") in list(inherits)


def test_apply_aswf_root_metadata_preserves_existing_unless_forced():
    """apply_aswf_root_metadata respects upstream metadata when force=False."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "root.usda"
        stage = Usd.Stage.CreateNew(str(path))
        prim = stage.DefinePrim("/asset", "Xform")
        stage.SetDefaultPrim(prim)
        Usd.ModelAPI(prim).SetKind("assembly")
        prim.SetAssetInfo({"version": "2.5.0"})

        asset_intake_utils.apply_aswf_root_metadata(
            prim, asset_name="asset", asset_identifier="./root.usda",
        )

        assert Usd.ModelAPI(prim).GetKind() == "assembly"
        info = prim.GetAssetInfo()
        assert info["version"] == "2.5.0"
        assert info["name"] == "asset"


def test_create_stage_produces_single_scene_file():
    """create_stage produces only scene.usda; no sublayer by default."""
    from bowerbot.utils import stage_utils
    with tempfile.TemporaryDirectory() as tmp:
        scene_path = Path(tmp) / "scene.usda"

        stage_utils.create_stage(scene_path)

        assert scene_path.exists()
        scene_text = scene_path.read_text(encoding="utf-8")
        assert "subLayers" not in scene_text


def test_open_stage_uses_root_layer_edit_target():
    """open_stage targets the root scene.usda layer; saves land there."""
    from bowerbot.utils import stage_utils
    with tempfile.TemporaryDirectory() as tmp:
        scene_path = Path(tmp) / "scene.usda"
        stage_utils.create_stage(scene_path)

        stage = stage_utils.open_stage(scene_path)
        edit_target = stage.GetEditTarget()
        assert Path(edit_target.GetLayer().identifier) == scene_path

        stage.DefinePrim("/Scene/Furniture", "Xform")
        stage.Save()

        scene_layer = Sdf.Layer.FindOrOpen(str(scene_path))
        assert scene_layer.GetPrimAtPath(Sdf.Path("/Scene/Furniture")) is not None


def test_add_nested_asset_reference_authors_canonical_xform_op_set():
    """Nested-asset wrapper always gets translate + rotate + scale + xformOpOrder."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        container_root = create_aswf_folder(assets_dir, "sofa")
        nested_root = create_aswf_folder(assets_dir, "pillow")
        container_dir = container_root.parent

        wrapper_path = asset_intake_utils.add_nested_asset_reference(
            container_dir=container_dir,
            group="Props",
            prim_name="Pillow_01",
            ref_asset_path=f"../{nested_root.parent.name}/{nested_root.name}",
            transform=TransformParams(translate=(1.0, 0.0, 2.0)),
        )

        stage = Usd.Stage.Open(str(container_dir / ASWFLayerNames.CONTENTS))
        wrapper_prim = stage.GetPrimAtPath(wrapper_path)
        op_order = UsdGeom.Xformable(wrapper_prim).GetXformOpOrderAttr().Get()
        assert list(op_order) == [
            "xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale",
        ]


def test_run_usd_compliance_checker_returns_no_issues_for_clean_stage():
    """The modern UsdValidation framework reports zero errors on a clean stage."""
    from bowerbot.utils import validation_utils
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clean.usda"
        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        prim = stage.DefinePrim("/asset", "Xform")
        stage.SetDefaultPrim(prim)
        UsdGeom.Cube.Define(stage, "/asset/Mesh")
        stage.Save()

        issues = validation_utils.run_usd_compliance_checker(path)
        errors = [i for i in issues if i.severity.value == "error"]
        assert errors == []


def test_apply_aswf_root_metadata_overwrites_when_forced():
    """force=True overwrites existing kind + assetInfo."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "root.usda"
        stage = Usd.Stage.CreateNew(str(path))
        prim = stage.DefinePrim("/asset", "Xform")
        stage.SetDefaultPrim(prim)
        Usd.ModelAPI(prim).SetKind("assembly")
        prim.SetAssetInfo({"version": "2.5.0"})

        asset_intake_utils.apply_aswf_root_metadata(
            prim, asset_name="asset", asset_identifier="./root.usda",
            force=True,
        )

        assert Usd.ModelAPI(prim).GetKind() == "component"
        info = prim.GetAssetInfo()
        assert info["version"] == "1.0"


# ── material_service: Add Material ─


def test_create_procedural_material_authors_hybrid_outputs():
    """Procedural materials carry both MaterialX and UsdPreviewSurface outputs."""
    from bowerbot.schemas import ProceduralMaterialParams
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()
        geo = create_geometry(source_dir, "table")
        root = asset_intake_utils.create_asset_folder(output_dir, "table", geo)

        material_utils.create_procedural_material_in_folder(
            asset_dir=root.parent,
            prim_path="/table/top",
            params=ProceduralMaterialParams(
                material_name="red_matte",
                base_color=(0.8, 0.05, 0.05),
                metalness=0.0,
                roughness=0.85,
            ),
        )

        mtl_stage = Usd.Stage.Open(str(root.parent / "mtl.usda"))
        material = UsdShade.Material(
            mtl_stage.GetPrimAtPath("/table/mtl/red_matte"),
        )
        assert material

        mtlx_out = material.GetSurfaceOutput("mtlx")
        assert mtlx_out and mtlx_out.HasConnectedSource()

        preview_out = material.GetSurfaceOutput()
        assert preview_out and preview_out.HasConnectedSource()

        mtlx_shader = UsdShade.Shader(
            mtl_stage.GetPrimAtPath("/table/mtl/red_matte/standard_surface"),
        )
        assert mtlx_shader.GetIdAttr().Get() == "ND_standard_surface_surfaceshader"

        preview_shader = UsdShade.Shader(
            mtl_stage.GetPrimAtPath("/table/mtl/red_matte/preview_surface"),
        )
        assert preview_shader.GetIdAttr().Get() == "UsdPreviewSurface"
        diffuse = preview_shader.GetInput("diffuseColor").Get()
        assert abs(diffuse[0] - 0.8) < 1e-5
        roughness = preview_shader.GetInput("roughness").Get()
        assert abs(roughness - 0.85) < 1e-5


def test_add_material_creates_mtl():
    """add_material creates mtl.usd and updates root file."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")
        mat = create_material(source_dir, "wood")

        root = asset_intake_utils.create_asset_folder(
            output_dir, "table", geo,
        )

        material_utils.add_material_to_folder(
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

        root = asset_intake_utils.create_asset_folder(
            output_dir, "table", geo,
        )
        material_utils.add_material_to_folder(
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

        root = asset_intake_utils.create_asset_folder(
            output_dir, "table", geo,
        )
        material_utils.add_material_to_folder(
            root.parent, mat_wood, "/table/top", "/mtl/wood",
        )
        material_utils.add_material_to_folder(
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

        root = asset_intake_utils.create_asset_folder(
            output_dir, "table", geo,
        )

        result_path = material_utils.add_material_to_folder(
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

        root = asset_intake_utils.create_asset_folder(
            output_dir, "table", geo,
        )
        material_utils.add_material_to_folder(
            root.parent, mat, "/table/top", "/mtl/wood",
        )

        # Remove the binding
        material_utils.remove_material_binding_from_folder(root.parent, "/table/top")

        # mtl.usd should be deleted (no materials left)
        assert not (root.parent / "mtl.usda").exists()

        stage = Usd.Stage.Open(str(root))
        default_prim = stage.GetDefaultPrim()

        ref_paths = []
        refs = default_prim.GetMetadata("references")
        if refs:
            for ref_list in (refs.prependedItems, refs.appendedItems, refs.explicitItems):
                if ref_list:
                    ref_paths.extend(r.assetPath for r in ref_list)
        assert "./mtl.usda" not in ref_paths

        payload_paths = []
        payloads = default_prim.GetMetadata("payload")
        if payloads:
            for pl_list in (
                payloads.prependedItems,
                payloads.appendedItems,
                payloads.explicitItems,
            ):
                if pl_list:
                    payload_paths.extend(p.assetPath for p in pl_list)
        assert "./geo.usda" in payload_paths


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

        root = asset_intake_utils.create_asset_folder(
            output_dir, "table", geo,
        )
        material_utils.add_material_to_folder(
            root.parent, mat, "/table/top", "/mtl/wood",
        )

        materials = material_utils.list_materials_in_folder(root.parent)
        assert len(materials) >= 1
        wood = [m for m in materials if m["material_name"] == "wood"]
        assert len(wood) == 1
        assert "/table/top" in wood[0]["bound_prims"]


def test_cleanup_unused_materials_removes_unbound():
    """cleanup_unused_materials deletes defined-but-unbound material prims."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")
        wood = create_material(source_dir, "wood")
        metal = create_material(source_dir, "metal")

        root = asset_intake_utils.create_asset_folder(output_dir, "table", geo)

        # Bind wood to the top; leave metal and an extra unbound material.
        material_utils.add_material_to_folder(
            root.parent, wood, "/table/top", "/mtl/wood",
        )
        # Copy metal definition in too, but never bind it.
        material_utils.add_material_to_folder(
            root.parent, metal, "/table/top", "/mtl/metal",
        )
        # Rebind top to wood so metal becomes unbound.
        material_utils.add_material_to_folder(
            root.parent, wood, "/table/top", "/mtl/wood",
        )

        mtl_stage = Usd.Stage.Open(str(root.parent / "mtl.usda"))
        before = {
            p.GetName() for p in mtl_stage.TraverseAll() if p.IsA(UsdShade.Material)
        }
        assert "wood" in before
        assert "metal" in before

        removed = material_utils.cleanup_unused_in_folder(root.parent)
        assert removed == ["metal"]

        mtl_stage = Usd.Stage.Open(str(root.parent / "mtl.usda"))
        after = {
            p.GetName() for p in mtl_stage.TraverseAll() if p.IsA(UsdShade.Material)
        }
        assert after == {"wood"}


def test_cleanup_unused_materials_no_mtl_layer():
    """cleanup_unused_materials returns [] when mtl.usda doesn't exist."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")
        root = asset_intake_utils.create_asset_folder(output_dir, "table", geo)

        assert not (root.parent / "mtl.usda").exists()
        assert material_utils.cleanup_unused_in_folder(root.parent) == []


def test_cleanup_unused_materials_drops_empty_layer():
    """When every material is unbound, the layer is deleted and root refs rebuild."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "table")
        wood = create_material(source_dir, "wood")

        root = asset_intake_utils.create_asset_folder(output_dir, "table", geo)
        material_utils.add_material_to_folder(
            root.parent, wood, "/table/top", "/mtl/wood",
        )
        material_utils.remove_material_binding_from_folder(root.parent, "/table/top")

        # remove_material_binding already triggered cleanup; follow-up should
        # be a no-op and mtl.usda should be gone.
        assert not (root.parent / "mtl.usda").exists()
        assert material_utils.cleanup_unused_in_folder(root.parent) == []


# ── dependency_utils ─


def test_validate_asset_folder_valid():
    """validate_asset_folder passes for a complete folder."""
    with tempfile.TemporaryDirectory() as tmp:
        root_file = create_aswf_folder(Path(tmp), "single_table")

        is_valid, errors = dependency_utils.validate_asset_folder(root_file)

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

        is_valid, errors = dependency_utils.validate_asset_folder(root_path)

        assert not is_valid
        assert any("geo.usd" in e for e in errors)


# ── Asset-Level Lights (light_service) ─


def test_add_light_creates_lgt():
    """add_light creates lgt.usda and updates root file."""
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        source_dir.mkdir()
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        geo = create_geometry(source_dir, "lamp")

        root = asset_intake_utils.create_asset_folder(
            output_dir, "lamp", geo,
        )

        light_utils.add_light_to_folder(
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

        root = asset_intake_utils.create_asset_folder(
            output_dir, "lamp", geo,
        )

        light_utils.add_light_to_folder(
            root.parent, "bulb",
            LightParams(
                light_type=LightType.SPHERE,
                translate=(0.0, 0.5, 0.0),
                radius=0.05,
            ),
        )
        light_utils.add_light_to_folder(
            root.parent, "glow",
            LightParams(
                light_type=LightType.DISK,
                translate=(0.0, 0.3, 0.0),
                radius=0.1,
            ),
        )

        lights = light_utils.list_lights_in_folder(root.parent)
        assert len(lights) == 2
        names = {light["name"] for light in lights}
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

        root = asset_intake_utils.create_asset_folder(
            output_dir, "lamp", geo,
        )

        light_utils.add_light_to_folder(
            root.parent, "bulb",
            LightParams(
                light_type=LightType.SPHERE,
                translate=(0.0, 0.5, 0.0),
            ),
        )
        light_utils.remove_light_from_folder(root.parent, "bulb")

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

        root = asset_intake_utils.create_asset_folder(
            output_dir, "table", geo,
        )

        light_utils.add_light_to_folder(
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

        root = asset_intake_utils.create_asset_folder(
            output_dir, "wall", geo,
        )

        light_utils.add_light_to_folder(
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


# ── Nested Asset Placement (asset_service) ─


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

        prim_path = asset_intake_utils.add_nested_asset_reference(
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

        asset_intake_utils.add_nested_asset_reference(
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


def test_to_layer_local_path_root_with_distinct_name():
    assert to_layer_local_path("/", "Single_Plant") == "/Single_Plant"
    assert to_layer_local_path("", "Single_Plant") == "/Single_Plant"
    assert to_layer_local_path("/Single_Plant", "Single_Plant") == "/Single_Plant"


def test_to_layer_local_path_root_when_name_collides_with_input():
    assert to_layer_local_path("/plant", "plant") == "/plant"
    assert to_layer_local_path("/", "plant") == "/plant"


def test_to_layer_local_path_child_already_canonical():
    assert to_layer_local_path("/plant/soil", "plant") == "/plant/soil"
    assert to_layer_local_path(
        "/Single_Plant/leaves", "Single_Plant",
    ) == "/Single_Plant/leaves"


def test_to_layer_local_path_relative_child_under_distinct_root():
    assert to_layer_local_path("/leaves", "Single_Plant") == "/Single_Plant/leaves"


def test_to_layer_local_path_child_named_same_as_root():
    assert to_layer_local_path("/plant/plant", "plant") == "/plant/plant"


def test_remove_nested_asset_reference_removes_from_contents():
    """remove_nested_asset_reference removes the prim spec from contents.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()

        container_root = create_aswf_folder(assets_dir, "sofa")
        nested_root = create_aswf_folder(assets_dir, "accent_pillow")
        container_dir = container_root.parent

        ref_asset_path = (
            f"../{nested_root.parent.name}/{nested_root.name}"
        )

        prim_path = asset_intake_utils.add_nested_asset_reference(
            container_dir=container_dir,
            group="Props",
            prim_name="Accent_Pillow_01",
            ref_asset_path=ref_asset_path,
            transform=TransformParams(),
        )

        stage = Usd.Stage.Open(str(container_root))
        assert stage.GetPrimAtPath(prim_path).IsValid()

        removed = asset_intake_utils.remove_nested_asset_reference(
            container_dir, "Props", "Accent_Pillow_01",
        )
        assert removed is True

        stage = Usd.Stage.Open(str(container_root))
        assert not stage.GetPrimAtPath(prim_path).IsValid()


def test_remove_nested_asset_reference_is_idempotent_when_already_absent():
    """Removing a non-existent prim is a no-op success (post-condition met)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        container_root = create_aswf_folder(assets_dir, "sofa")
        container_dir = container_root.parent

        removed = asset_intake_utils.remove_nested_asset_reference(
            container_dir, "Props", "Accent_Pillow_99",
        )
        assert removed is True


def test_remove_nested_asset_reference_drops_empty_layer():
    """When the last nested ref is removed, contents.usda + root ref disappear."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()

        container_root = create_aswf_folder(assets_dir, "sofa")
        nested_root = create_aswf_folder(assets_dir, "accent_pillow")
        container_dir = container_root.parent

        ref_asset_path = (
            f"../{nested_root.parent.name}/{nested_root.name}"
        )
        asset_intake_utils.add_nested_asset_reference(
            container_dir=container_dir,
            group="Props",
            prim_name="Accent_Pillow_01",
            ref_asset_path=ref_asset_path,
            transform=TransformParams(),
        )
        contents_path = container_dir / ASWFLayerNames.CONTENTS
        assert contents_path.exists()

        asset_intake_utils.remove_nested_asset_reference(
            container_dir, "Props", "Accent_Pillow_01",
        )

        assert not contents_path.exists(), (
            "contents.usda should be removed when empty"
        )

        stage = Usd.Stage.Open(str(container_root))
        ref_paths = []
        default_prim = stage.GetDefaultPrim()
        refs = default_prim.GetMetadata("references")
        if refs:
            for ref_list in (
                refs.prependedItems, refs.appendedItems, refs.explicitItems,
            ):
                if ref_list:
                    ref_paths.extend(r.assetPath for r in ref_list)
        assert "./contents.usda" not in ref_paths


def test_cleanup_unused_contents_in_folder_drops_orphan_layer():
    """Empty contents.usda left over from prior versions gets cleaned up."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()

        container_root = create_aswf_folder(assets_dir, "sofa")
        nested_root = create_aswf_folder(assets_dir, "accent_pillow")
        container_dir = container_root.parent

        ref_asset_path = (
            f"../{nested_root.parent.name}/{nested_root.name}"
        )
        asset_intake_utils.add_nested_asset_reference(
            container_dir=container_dir,
            group="Props",
            prim_name="Pillow_01",
            ref_asset_path=ref_asset_path,
            transform=TransformParams(),
        )

        contents_path = container_dir / ASWFLayerNames.CONTENTS
        layer = Sdf.Layer.FindOrOpen(str(contents_path))
        props_spec = layer.GetPrimAtPath(Sdf.Path("/sofa/contents/Props"))
        del props_spec.nameChildren["Pillow_01"]
        layer.Save()

        assert contents_path.exists()

        removed = asset_intake_utils.cleanup_unused_contents_in_folder(container_dir)

        assert removed == ["Props"]
        assert not contents_path.exists()


def test_cleanup_unused_contents_in_folder_preserves_layer_with_refs():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()

        container_root = create_aswf_folder(assets_dir, "sofa")
        nested_root = create_aswf_folder(assets_dir, "accent_pillow")
        container_dir = container_root.parent

        asset_intake_utils.add_nested_asset_reference(
            container_dir=container_dir,
            group="Props",
            prim_name="Pillow_01",
            ref_asset_path=f"../{nested_root.parent.name}/{nested_root.name}",
            transform=TransformParams(),
        )

        removed = asset_intake_utils.cleanup_unused_contents_in_folder(container_dir)

        assert removed == []
        assert (container_dir / ASWFLayerNames.CONTENTS).exists()


def test_cleanup_unused_contents_in_folder_no_layer_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        container_root = create_aswf_folder(assets_dir, "sofa")
        container_dir = container_root.parent

        removed = asset_intake_utils.cleanup_unused_contents_in_folder(container_dir)
        assert removed == []


def test_remove_nested_asset_reference_keeps_layer_when_other_refs_remain():
    """Removing one nested ref while another exists preserves contents.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()

        container_root = create_aswf_folder(assets_dir, "sofa")
        nested_root = create_aswf_folder(assets_dir, "accent_pillow")
        container_dir = container_root.parent

        ref_asset_path = (
            f"../{nested_root.parent.name}/{nested_root.name}"
        )
        for prim_name in ("Pillow_01", "Pillow_02"):
            asset_intake_utils.add_nested_asset_reference(
                container_dir=container_dir,
                group="Props",
                prim_name=prim_name,
                ref_asset_path=ref_asset_path,
                transform=TransformParams(),
            )
        contents_path = container_dir / ASWFLayerNames.CONTENTS

        asset_intake_utils.remove_nested_asset_reference(
            container_dir, "Props", "Pillow_01",
        )

        assert contents_path.exists()
        stage = Usd.Stage.Open(str(container_root))
        assert stage.GetPrimAtPath(
            "/sofa/contents/Props/Pillow_02",
        ).IsValid()


def test_remove_nested_asset_reference_idempotent_double_remove():
    """Calling remove twice for the same prim succeeds both times.

    This is the shared-asset case: when 4 sofa instances reference the
    same asset folder, removing 'sofa 1's pillows' removes them from
    the shared contents.usda. The follow-up calls for 'sofa 2's
    pillows' (same prim names) hit an already-absent state and must
    not error.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        container_root = create_aswf_folder(assets_dir, "sofa")
        nested_root = create_aswf_folder(assets_dir, "accent_pillow")
        container_dir = container_root.parent

        ref_asset_path = (
            f"../{nested_root.parent.name}/{nested_root.name}"
        )
        asset_intake_utils.add_nested_asset_reference(
            container_dir=container_dir,
            group="Props",
            prim_name="Accent_Pillow_01",
            ref_asset_path=ref_asset_path,
            transform=TransformParams(),
        )

        first = asset_intake_utils.remove_nested_asset_reference(
            container_dir, "Props", "Accent_Pillow_01",
        )
        second = asset_intake_utils.remove_nested_asset_reference(
            container_dir, "Props", "Accent_Pillow_01",
        )
        assert first is True
        assert second is True


def test_parse_nested_contents_path_recognises_nested():
    from bowerbot.services.stage_service import _parse_nested_contents_path
    result = _parse_nested_contents_path(
        "/Scene/Furniture/Single_Sofa_04_44/asset/contents/Props/Accent_Pillow_01_45",
    )
    assert result == ("Props", "Accent_Pillow_01_45")


def test_parse_nested_contents_path_returns_none_for_scene_level_wrapper():
    from bowerbot.services.stage_service import _parse_nested_contents_path
    assert _parse_nested_contents_path("/Scene/Furniture/Single_Sofa_04_44") is None


def test_parse_nested_contents_path_raises_for_path_inside_top_level_asset():
    import pytest

    from bowerbot.services.stage_service import _parse_nested_contents_path
    with pytest.raises(ValueError, match="referenced top-level asset"):
        _parse_nested_contents_path(
            "/Scene/Furniture/Single_Sofa_04_44/asset",
        )
    with pytest.raises(ValueError, match="referenced top-level asset"):
        _parse_nested_contents_path(
            "/Scene/Furniture/Single_Sofa_04_44/asset/legs",
        )


def test_parse_nested_contents_path_raises_for_path_deeper_than_nested_wrapper():
    import pytest

    from bowerbot.services.stage_service import _parse_nested_contents_path
    with pytest.raises(ValueError, match="not at the wrapper level"):
        _parse_nested_contents_path(
            "/Scene/Furniture/Single_Sofa_04_44/asset/contents/Props",
        )
    with pytest.raises(ValueError, match="not at the wrapper level"):
        _parse_nested_contents_path(
            "/Scene/Furniture/Single_Sofa_04_44/"
            "asset/contents/Props/Pillow_01/asset",
        )
    with pytest.raises(ValueError, match="not at the wrapper level"):
        _parse_nested_contents_path(
            "/Scene/Furniture/Single_Sofa_04_44/"
            "asset/contents/Props/Pillow_01/asset/Mesh",
        )


def _build_scene_with_n_instances(
    tmp_path: Path, container_name: str, n_instances: int,
) -> tuple[Path, Path]:
    """Author a scene that references *container_name* asset n_instances times."""
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    container_root = create_aswf_folder(assets_dir, container_name)
    container_dir = container_root.parent

    scene_path = tmp_path / "scene.usda"
    scene_stage = Usd.Stage.CreateNew(str(scene_path))
    UsdGeom.SetStageMetersPerUnit(scene_stage, 1.0)
    UsdGeom.SetStageUpAxis(scene_stage, UsdGeom.Tokens.y)
    scene_root = scene_stage.DefinePrim("/Scene", "Xform")
    scene_stage.SetDefaultPrim(scene_root)
    rel = container_root.relative_to(tmp_path).as_posix()
    for i in range(1, n_instances + 1):
        wrapper = scene_stage.DefinePrim(
            f"/Scene/Furniture/{container_name}_{i:02d}", "Xform",
        )
        ref_prim = scene_stage.DefinePrim(
            f"{wrapper.GetPath()}/asset", "Xform",
        )
        ref_prim.GetReferences().AddReference(f"./{rel}")
    scene_stage.Save()
    return scene_path, container_dir


def test_count_scene_refs_to_asset_dir_returns_n_instances():
    from bowerbot.utils import stage_utils
    with tempfile.TemporaryDirectory() as tmp:
        scene_path, container_dir = _build_scene_with_n_instances(
            Path(tmp), "single_sofa", 4,
        )
        stage = Usd.Stage.Open(str(scene_path))
        assert stage_utils.count_scene_refs_to_asset_dir(stage, container_dir) == 4


def test_count_scene_refs_to_asset_dir_returns_zero_when_unreferenced():
    from bowerbot.utils import stage_utils
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        container_root = create_aswf_folder(assets_dir, "lonely_asset")
        container_dir = container_root.parent

        scene_path = tmp_path / "scene.usda"
        scene_stage = Usd.Stage.CreateNew(str(scene_path))
        scene_stage.DefinePrim("/Scene", "Xform")
        scene_stage.Save()
        stage = Usd.Stage.Open(str(scene_path))
        assert stage_utils.count_scene_refs_to_asset_dir(stage, container_dir) == 0


def test_add_nested_asset_reference_uses_wrapper_asset_convention():
    """Nested placement mirrors scene-level: wrapper holds xform, /asset holds ref."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()

        container_root = create_aswf_folder(assets_dir, "sofa")
        nested_root = create_aswf_folder(assets_dir, "pillow")
        container_dir = container_root.parent

        wrapper_path = asset_intake_utils.add_nested_asset_reference(
            container_dir=container_dir,
            group="Props",
            prim_name="Pillow_01",
            ref_asset_path=f"../{nested_root.parent.name}/{nested_root.name}",
            transform=TransformParams(translate=(1.0, 0.0, 2.0)),
        )

        contents_path = container_dir / ASWFLayerNames.CONTENTS
        layer = Sdf.Layer.FindOrOpen(str(contents_path))

        wrapper_spec = layer.GetPrimAtPath(Sdf.Path(wrapper_path))
        assert wrapper_spec is not None, "Wrapper prim missing"
        assert not wrapper_spec.hasReferences, (
            "Wrapper should not carry the reference"
        )

        asset_child = layer.GetPrimAtPath(Sdf.Path(f"{wrapper_path}/asset"))
        assert asset_child is not None, "Inner /asset child missing"
        assert asset_child.hasReferences, (
            "Inner /asset child must carry the reference arc"
        )


def _make_geo_with_root_xform(
    geo_path: Path,
    asset_name: str,
    *,
    translate: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotate_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
    points: tuple[tuple[float, float, float], ...] = (
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
    ),
) -> None:
    """Author a geo.usda with the given root-prim xform ops + mesh points."""
    from pxr import Gf
    stage = Usd.Stage.CreateNew(str(geo_path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{asset_name}", "Xform")
    stage.SetDefaultPrim(root)
    xf = UsdGeom.Xformable(root)
    if translate != (0.0, 0.0, 0.0):
        xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
    if rotate_xyz != (0.0, 0.0, 0.0):
        xf.AddRotateXYZOp().Set(Gf.Vec3f(*rotate_xyz))
    if scale != (1.0, 1.0, 1.0):
        xf.AddScaleOp().Set(Gf.Vec3f(*scale))
    mesh = UsdGeom.Mesh.Define(stage, f"/{asset_name}/mesh")
    mesh.GetPointsAttr().Set([Gf.Vec3f(*p) for p in points])
    stage.Save()


def test_bake_root_transforms_translates_points():
    """bake_root_transforms shifts mesh points by the root translate op."""
    with tempfile.TemporaryDirectory() as tmp:
        geo_path = Path(tmp) / "geo.usda"
        _make_geo_with_root_xform(
            geo_path, "thing", translate=(5.0, 0.0, 4.0),
        )

        baked = asset_intake_utils.bake_root_transforms(geo_path)
        assert baked is True

        stage = Usd.Stage.Open(str(geo_path))
        mesh = UsdGeom.Mesh(stage.GetPrimAtPath("/thing/mesh"))
        new_points = list(mesh.GetPointsAttr().Get())
        assert abs(new_points[0][0] - 5.0) < 1e-5
        assert abs(new_points[0][2] - 4.0) < 1e-5
        assert abs(new_points[1][0] - 6.0) < 1e-5

        root = stage.GetDefaultPrim()
        assert UsdGeom.Xformable(root).GetXformOpOrderAttr().Get() in (None, [])
        assert "xformOp:translate" not in root.GetPropertyNames()


def test_bake_root_transforms_scales_points():
    """bake_root_transforms applies scale to mesh points."""
    with tempfile.TemporaryDirectory() as tmp:
        geo_path = Path(tmp) / "geo.usda"
        _make_geo_with_root_xform(
            geo_path, "thing", scale=(0.1, 0.1, 0.1),
        )

        asset_intake_utils.bake_root_transforms(geo_path)

        stage = Usd.Stage.Open(str(geo_path))
        mesh = UsdGeom.Mesh(stage.GetPrimAtPath("/thing/mesh"))
        points = list(mesh.GetPointsAttr().Get())
        assert abs(points[1][0] - 0.1) < 1e-5


def test_bake_root_transforms_skips_identity():
    """bake_root_transforms returns False when root is already identity."""
    with tempfile.TemporaryDirectory() as tmp:
        geo_path = Path(tmp) / "geo.usda"
        _make_geo_with_root_xform(geo_path, "thing")

        baked = asset_intake_utils.bake_root_transforms(geo_path)
        assert baked is False


def test_ensure_aswf_compliance_rejects_dirty_root_without_flag():
    """ensure_aswf_compliance raises when root has non-identity transforms."""
    import pytest
    with tempfile.TemporaryDirectory() as tmp:
        geo_path = Path(tmp) / "geo.usda"
        _make_geo_with_root_xform(geo_path, "thing", translate=(5.0, 0.0, 0.0))

        with pytest.raises(ValueError, match="non-identity transforms"):
            asset_intake_utils.ensure_aswf_compliance(geo_path)


def test_ensure_aswf_compliance_bakes_when_flag_set():
    """ensure_aswf_compliance bakes when fix_root_transforms=True."""
    with tempfile.TemporaryDirectory() as tmp:
        geo_path = Path(tmp) / "geo.usda"
        _make_geo_with_root_xform(geo_path, "thing", translate=(5.0, 0.0, 0.0))

        asset_intake_utils.ensure_aswf_compliance(
            geo_path, fix_root_transforms=True,
        )

        stage = Usd.Stage.Open(str(geo_path))
        mesh = UsdGeom.Mesh(stage.GetPrimAtPath("/thing/mesh"))
        points = list(mesh.GetPointsAttr().Get())
        assert abs(points[0][0] - 5.0) < 1e-5
