# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant set foundation, orchestrators, and removal tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pxr import Sdf, Usd, UsdGeom, UsdLux, UsdShade

from bowerbot.config import SceneDefaults
from bowerbot.services import variant_service
from bowerbot.state import SceneState
from bowerbot.utils import (
    material_utils,
    stage_utils,
    validation_utils,
    variant_utils,
)

# ── Asset builder ──


def make_asset(
    parent: Path, name: str, *, with_materials: bool = False,
) -> Path:
    """Build a minimal ASWF asset folder (root + geo, optionally mtl)."""
    asset_dir = parent / name
    asset_dir.mkdir()

    geo_stage = Usd.Stage.CreateNew(str(asset_dir / "geo.usda"))
    UsdGeom.SetStageMetersPerUnit(geo_stage, 1.0)
    UsdGeom.SetStageUpAxis(geo_stage, UsdGeom.Tokens.y)
    geo_root = geo_stage.DefinePrim(f"/{name}", "Xform")
    geo_stage.SetDefaultPrim(geo_root)
    UsdGeom.Cube.Define(geo_stage, f"/{name}/Mesh")
    UsdGeom.Cube.Define(geo_stage, f"/{name}/MeshB")
    geo_stage.Save()

    if with_materials:
        mtl_stage = Usd.Stage.CreateNew(str(asset_dir / "mtl.usda"))
        UsdGeom.SetStageMetersPerUnit(mtl_stage, 1.0)
        UsdGeom.SetStageUpAxis(mtl_stage, UsdGeom.Tokens.y)
        mtl_root = mtl_stage.DefinePrim(f"/{name}", "Xform")
        mtl_stage.SetDefaultPrim(mtl_root)
        mtl_stage.DefinePrim(f"/{name}/Materials", "Scope")
        UsdShade.Material.Define(mtl_stage, f"/{name}/Materials/Wood")
        UsdShade.Material.Define(mtl_stage, f"/{name}/Materials/Metal")
        mtl_stage.Save()

    root_stage = Usd.Stage.CreateNew(str(asset_dir / f"{name}.usda"))
    UsdGeom.SetStageMetersPerUnit(root_stage, 1.0)
    UsdGeom.SetStageUpAxis(root_stage, UsdGeom.Tokens.y)
    root_prim = root_stage.DefinePrim(f"/{name}", "Xform")
    root_stage.SetDefaultPrim(root_prim)
    root_prim.GetPayloads().AddPayload("./geo.usda")
    if with_materials:
        root_prim.GetReferences().AddReference("./mtl.usda")
    root_stage.Save()
    return asset_dir


def make_scene(parent: Path) -> Path:
    """Build a single-file scene.usda and return its path."""
    scene_path = parent / "scene.usda"
    scene_stage = Usd.Stage.CreateNew(str(scene_path))
    UsdGeom.SetStageMetersPerUnit(scene_stage, 1.0)
    UsdGeom.SetStageUpAxis(scene_stage, UsdGeom.Tokens.y)
    scene_root = scene_stage.DefinePrim("/Scene", "Xform")
    scene_stage.SetDefaultPrim(scene_root)
    scene_stage.Save()
    return scene_path


def _empty_state() -> SceneState:
    """SceneState with no project."""
    return SceneState(scene_defaults=SceneDefaults())


def place_asset_in_scene(
    parent: Path, asset: Path, scene_prim_path: str = "/Scene/Furniture/Asset_01",
) -> tuple[SceneState, Path]:
    """Create a scene + place an asset using BowerBot's wrapper pattern."""
    scene_path = make_scene(parent)
    setup_stage = Usd.Stage.Open(str(scene_path))

    parts = scene_prim_path.strip("/").split("/")
    cursor = ""
    for part in parts[:-1]:
        cursor = f"{cursor}/{part}"
        setup_stage.DefinePrim(cursor, "Xform")
    wrapper = setup_stage.DefinePrim(scene_prim_path, "Xform")
    asset_child = setup_stage.DefinePrim(f"{scene_prim_path}/asset", "Xform")
    asset_child.GetReferences().AddReference(
        f"./{asset.name}/{asset.name}.usda",
    )
    setup_stage.Save()
    del wrapper, asset_child, setup_stage

    state = _empty_state()
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)
    return state, scene_path


# ── Util primitives ──


def test_ensure_variants_layer_creates_file(tmp_path):
    asset = make_asset(tmp_path, "table")
    path = variant_utils.ensure_variants_layer(asset)
    assert path.exists()
    assert path.name == "variants.usda"
    layer = Sdf.Layer.FindOrOpen(str(path))
    assert layer is not None
    assert layer.defaultPrim == "table"


def test_ensure_variants_layer_idempotent(tmp_path):
    asset = make_asset(tmp_path, "table")
    p1 = variant_utils.ensure_variants_layer(asset)
    p2 = variant_utils.ensure_variants_layer(asset)
    assert p1 == p2


def test_ensure_variants_referenced_idempotent(tmp_path):
    asset = make_asset(tmp_path, "table")
    variant_utils.ensure_variants_layer(asset)
    variant_utils.ensure_variants_referenced(asset)
    variant_utils.ensure_variants_referenced(asset)
    layer = Sdf.Layer.FindOrOpen(str(asset / "table.usda"))
    prim_spec = layer.GetPrimAtPath("/table")
    refs = list(prim_spec.referenceList.prependedItems)
    matches = [r for r in refs if r.assetPath == "./variants.usda"]
    assert len(matches) == 1


def test_author_in_variant_keystone_is_universal(tmp_path):
    """The same primitive authors materials, lights, AND deactivation."""
    asset = make_asset(tmp_path, "fixture", with_materials=True)
    variant_utils.ensure_variants_layer(asset)
    variant_utils.ensure_variants_referenced(asset)
    stage = variant_utils.open_variants_stage(asset)

    def bind_material(stage, _prim_path):
        mesh = stage.OverridePrim("/fixture/Mesh")
        api = UsdShade.MaterialBindingAPI.Apply(mesh)
        api.GetDirectBindingRel().SetTargets(
            [Sdf.Path("/fixture/Materials/Wood")],
        )

    def author_light(stage, _prim_path):
        light_prim = stage.DefinePrim("/fixture/RimLight", "SphereLight")
        UsdLux.SphereLight(light_prim).CreateIntensityAttr().Set(1500.0)

    def deactivate(stage, _prim_path):
        target = stage.OverridePrim("/fixture/MeshB")
        target.SetActive(False)

    variant_utils.author_in_variant(
        stage, "/fixture", "look", "wood", bind_material,
    )
    variant_utils.author_in_variant(
        stage, "/fixture", "lighting", "rim", author_light,
    )
    variant_utils.author_in_variant(
        stage, "/fixture", "configuration", "stripped", deactivate,
    )

    summary = variant_utils.get_variant_summary(asset)
    assert sorted(s.name for s in summary.variant_sets) == [
        "configuration", "lighting", "look",
    ]


def test_apply_variant_creates_layer_and_reference(tmp_path):
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(
        asset, "finish", "wood", lambda s, p: None,
    )
    assert (asset / "variants.usda").exists()
    layer = Sdf.Layer.FindOrOpen(str(asset / "table.usda"))
    refs = list(layer.GetPrimAtPath("/table").referenceList.prependedItems)
    assert any(r.assetPath == "./variants.usda" for r in refs)


def test_set_default_variant_lives_on_asset_root(tmp_path):
    """Default selection lives in <asset>.usda, NOT variants.usda."""
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(
        asset, "finish", "wood", lambda s, p: None, set_as_default=True,
    )

    root_layer = Sdf.Layer.FindOrOpen(str(asset / "table.usda"))
    root_prim = root_layer.GetPrimAtPath("/table")
    assert root_prim.variantSelections.get("finish") == "wood"

    variants_layer = Sdf.Layer.FindOrOpen(str(asset / "variants.usda"))
    variants_prim = variants_layer.GetPrimAtPath("/table")
    assert "finish" not in variants_prim.variantSelections


# ── Removal + cleanup ──


def test_remove_variant_idempotent_when_missing(tmp_path):
    asset = make_asset(tmp_path, "table")
    assert variant_utils.remove_variant(asset, "finish", "wood") is False


def test_remove_variant_set_idempotent_when_missing(tmp_path):
    asset = make_asset(tmp_path, "table")
    assert variant_utils.remove_variant_set(asset, "finish") is False


def test_cleanup_after_last_variant_set_removed(tmp_path):
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(
        asset, "finish", "wood", lambda s, p: None, set_as_default=True,
    )
    variant_utils.remove_variant_set(asset, "finish")
    variant_utils.clear_default_variant(asset, "finish")
    cleaned = variant_utils.cleanup_if_empty(asset)
    assert cleaned is True
    assert not (asset / "variants.usda").exists()
    layer = Sdf.Layer.FindOrOpen(str(asset / "table.usda"))
    refs = list(layer.GetPrimAtPath("/table").referenceList.prependedItems)
    assert not any(r.assetPath == "./variants.usda" for r in refs)


def test_cleanup_does_not_warn_with_open_scene_referencing_asset(tmp_path):
    """cleanup_if_empty scrubs the variants.usda ref before clearing the layer."""
    import os
    import sys

    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(
        asset, "finish", "wood", lambda s, p: None, set_as_default=True,
    )

    state, _scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Furniture/Table_01",
    )
    assert state.stage.GetPrimAtPath("/Scene/Furniture/Table_01/asset").IsValid()

    variant_utils.remove_variant_set(asset, "finish")
    variant_utils.clear_default_variant(asset, "finish")

    sys.stderr.flush()
    saved_fd = os.dup(2)
    read_fd, write_fd = os.pipe()
    os.dup2(write_fd, 2)
    os.close(write_fd)
    try:
        cleaned = variant_utils.cleanup_if_empty(asset)
        state.stage.Reload()
        sys.stderr.flush()
    finally:
        os.dup2(saved_fd, 2)
        os.close(saved_fd)

    captured = b""
    os.set_blocking(read_fd, False)
    try:
        while True:
            chunk = os.read(read_fd, 8192)
            if not chunk:
                break
            captured += chunk
    except BlockingIOError:
        pass
    os.close(read_fd)
    text = captured.decode("utf-8", "replace")

    assert cleaned is True
    assert (
        "Unresolved reference prim path" not in text
        or "variants.usda" not in text
    ), text


def _make_lod_payload(
    asset_dir: Path, file_name: str, asset_name: str, mesh_names: list[str],
) -> Path:
    """Write a standalone payload file with the given mesh hierarchy."""
    path = asset_dir / file_name
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{asset_name}", "Xform")
    stage.SetDefaultPrim(root)
    for mesh in mesh_names:
        UsdGeom.Cube.Define(stage, f"/{asset_name}/{mesh}")
    stage.Save()
    return path


def test_setup_geometry_variants_refuses_divergent_lod_namespace(tmp_path):
    asset = make_asset(tmp_path, "chair")
    _make_lod_payload(asset, "geo_low.usda", "chair", ["body"])
    with pytest.raises(ValueError, match="divergent prim hierarchies"):
        variant_utils.setup_geometry_variant_set(
            asset, "lod",
            {"high": "./geo.usda", "low": "./geo_low.usda"},
            default_variant="high",
        )


def test_setup_geometry_variants_accepts_matching_lod_namespace(tmp_path):
    asset = make_asset(tmp_path, "chair")
    _make_lod_payload(asset, "geo_low.usda", "chair", ["Mesh", "MeshB"])
    variant_utils.setup_geometry_variant_set(
        asset, "lod",
        {"high": "./geo.usda", "low": "./geo_low.usda"},
        default_variant="high",
    )
    summary = variant_utils.get_variant_summary(asset)
    lod = next(s for s in summary.variant_sets if s.name == "lod")
    assert set(lod.variants) == {"high", "low"}


def test_add_geometry_variant_refuses_divergent_payload(tmp_path):
    asset = make_asset(tmp_path, "chair")
    _make_lod_payload(asset, "geo_low.usda", "chair", ["Mesh", "MeshB"])
    _make_lod_payload(asset, "geo_merged.usda", "chair", ["AllInOne"])
    variant_utils.setup_geometry_variant_set(
        asset, "lod",
        {"high": "./geo.usda", "low": "./geo_low.usda"},
        default_variant="high",
    )
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Chair_01")
    with pytest.raises(ValueError, match="divergent prim hierarchies"):
        variant_service.add_asset_geometry_variant(state, {
            "prim_path": "/Scene/Furniture/Chair_01",
            "variant_set": "lod",
            "variant_name": "proxy",
            "payloads": {"/Geo": "./geo_merged.usda"},
        })


def test_remove_variant_keeps_set_when_others_remain(tmp_path):
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(asset, "finish", "wood", lambda s, p: None)
    variant_utils.apply_variant(asset, "finish", "metal", lambda s, p: None)
    assert variant_utils.remove_variant(asset, "finish", "wood") is True
    summary = variant_utils.get_variant_summary(asset)
    finish = next(s for s in summary.variant_sets if s.name == "finish")
    assert finish.variants == ["metal"]


# ── Service: category orchestrators ──


def test_service_add_material_variant(tmp_path):
    asset = make_asset(tmp_path, "table", with_materials=True)
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    result = variant_service.add_asset_material_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "wood",
        "bindings": {"/Mesh": "/Materials/Wood"},
        "set_as_default": True,
    })
    assert result["category"] == "material"
    assert result["default_selected"] is True
    summary = variant_utils.get_variant_summary(asset)
    finish = next(s for s in summary.variant_sets if s.name == "finish")
    assert finish.selection == "wood"


def test_service_add_geometry_variant_extends_existing_set(tmp_path):
    asset = make_asset(tmp_path, "house")
    _make_lod_payload(asset, "geo_low.usda", "house", ["Mesh", "MeshB"])
    _make_lod_payload(asset, "geo_mid.usda", "house", ["Mesh", "MeshB"])
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Architecture/House_01")
    variant_service.setup_asset_geometry_variants(state, {
        "prim_path": "/Scene/Architecture/House_01",
        "variant_set": "lod",
        "variants": {"high": "./geo.usda", "low": "./geo_low.usda"},
        "default_variant": "high",
    })
    result = variant_service.add_asset_geometry_variant(state, {
        "prim_path": "/Scene/Architecture/House_01",
        "variant_set": "lod",
        "variant_name": "mid",
        "payloads": {"/": "./geo_mid.usda"},
    })
    assert result["category"] == "geometry"
    summary = variant_utils.get_variant_summary(asset)
    lod = next(s for s in summary.variant_sets if s.name == "lod")
    assert set(lod.variants) == {"high", "low", "mid"}


def test_setup_geometry_variants_actually_swaps_payload(tmp_path):
    """The Pixar pattern: each variant body authors its own payload spec."""
    asset = make_asset(tmp_path, "table")
    _make_lod_payload(asset, "geo_low.usda", "table", ["Mesh", "MeshB"])

    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    variant_service.setup_asset_geometry_variants(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "lod",
        "variants": {"high": "./geo.usda", "low": "./geo_low.usda"},
        "default_variant": "high",
    })

    refs = variant_utils.get_variant_payload_refs(asset, "lod")
    assert refs == {"high": "./geo.usda", "low": "./geo_low.usda"}


def test_setup_geometry_variants_clears_root_payload(tmp_path):
    """After setup, the asset root must have no direct payload."""
    asset = make_asset(tmp_path, "table")
    _make_lod_payload(asset, "geo_low.usda", "table", ["Mesh", "MeshB"])
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    variant_service.setup_asset_geometry_variants(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "lod",
        "variants": {"high": "./geo.usda", "low": "./geo_low.usda"},
        "default_variant": "high",
    })

    layer = Sdf.Layer.FindOrOpen(str(asset / "table.usda"))
    prim_spec = layer.GetPrimAtPath(Sdf.Path("/table"))
    plist = prim_spec.payloadList
    assert not plist.prependedItems
    assert not plist.appendedItems
    assert not plist.explicitItems


def test_removing_geometry_variant_set_restores_canonical_payload(tmp_path):
    """Removing the last geo variant set must restore the asset's ./geo.usda payload."""
    asset = make_asset(tmp_path, "table")
    _make_lod_payload(asset, "geo_low.usda", "table", ["Mesh", "MeshB"])
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    variant_service.setup_asset_geometry_variants(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "lod",
        "variants": {"high": "./geo.usda", "low": "./geo_low.usda"},
        "default_variant": "high",
    })
    variant_service.remove_asset_variant_set(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "lod",
    })

    layer = Sdf.Layer.FindOrOpen(str(asset / "table.usda"))
    prim = layer.GetPrimAtPath(Sdf.Path("/table"))
    payloads = [p.assetPath for p in prim.payloadList.prependedItems]
    assert payloads == ["./geo.usda"]


def test_removing_last_geometry_variant_restores_canonical_payload(tmp_path):
    """Whittling a geo variant set down to empty must also restore the payload."""
    asset = make_asset(tmp_path, "table")
    _make_lod_payload(asset, "geo_low.usda", "table", ["Mesh", "MeshB"])
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    variant_service.setup_asset_geometry_variants(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "lod",
        "variants": {"high": "./geo.usda", "low": "./geo_low.usda"},
        "default_variant": "high",
    })
    variant_service.remove_asset_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "lod",
        "variant_name": "high",
    })
    variant_service.remove_asset_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "lod",
        "variant_name": "low",
    })

    layer = Sdf.Layer.FindOrOpen(str(asset / "table.usda"))
    prim = layer.GetPrimAtPath(Sdf.Path("/table"))
    payloads = [p.assetPath for p in prim.payloadList.prependedItems]
    assert payloads == ["./geo.usda"]


def test_removing_non_geometry_variant_set_leaves_root_payload_alone(tmp_path):
    """Removing a material variant set should not touch the root payload."""
    asset = make_asset(tmp_path, "table", with_materials=True)
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    variant_service.add_asset_material_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "wood",
        "bindings": {"/Mesh": "/Materials/Wood"},
    })

    layer_before = Sdf.Layer.FindOrOpen(str(asset / "table.usda"))
    spec_before = layer_before.GetPrimAtPath(Sdf.Path("/table"))
    payloads_before = [
        p.assetPath for p in spec_before.payloadList.prependedItems
    ]

    variant_service.remove_asset_variant_set(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
    })

    layer_after = Sdf.Layer.FindOrOpen(str(asset / "table.usda"))
    spec_after = layer_after.GetPrimAtPath(Sdf.Path("/table"))
    payloads_after = [
        p.assetPath for p in spec_after.payloadList.prependedItems
    ]
    assert payloads_after == payloads_before
    assert "./geo.usda" in payloads_after


def test_add_asset_geometry_variant_refuses_when_root_payload_present(tmp_path):
    """add_asset_geometry_variant must redirect to setup when asset isn't restructured."""
    asset = make_asset(tmp_path, "table")
    (asset / "geo_low.usda").write_text(
        "#usda 1.0\n(\n    defaultPrim = \"table\"\n)\n", encoding="utf-8",
    )
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    with pytest.raises(ValueError, match="setup_asset_geometry_variants"):
        variant_service.add_asset_geometry_variant(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "lod",
            "variant_name": "low",
            "payloads": {"/Mesh": "./geo_low.usda"},
        })


def test_geometry_variant_rejects_missing_payload(tmp_path):
    """The variant must not be authored if the payload file is missing."""
    asset = make_asset(tmp_path, "house")
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Architecture/House_01")
    with pytest.raises(ValueError, match="does not exist"):
        variant_service.add_asset_geometry_variant(state, {
            "prim_path": "/Scene/Architecture/House_01",
            "variant_set": "lod",
            "variant_name": "low",
            "payloads": {"/Mesh": "./geo_low.usda"},
        })
    assert not (asset / "variants.usda").exists()


def test_geometry_variant_strips_scene_namespace_from_prim_path(tmp_path):
    """A scene-rooted prim path must normalise to asset-local before authoring."""
    asset = make_asset(tmp_path, "table")
    _make_lod_payload(asset, "geo_low.usda", "table", ["Mesh", "MeshB"])
    _make_lod_payload(asset, "geo_mid.usda", "table", ["Mesh", "MeshB"])
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    variant_service.setup_asset_geometry_variants(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "lod",
        "variants": {"high": "./geo.usda", "low": "./geo_low.usda"},
        "default_variant": "high",
    })
    variant_service.add_asset_geometry_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "lod",
        "variant_name": "mid",
        "payloads": {
            "/Scene/Furniture/Table_01/asset/Mesh": "./geo_mid.usda",
        },
    })

    layer = Sdf.Layer.FindOrOpen(str(asset / "variants.usda"))
    variant_prim_spec = layer.GetPrimAtPath(
        Sdf.Path("/table{lod=mid}Mesh"),
    )
    assert variant_prim_spec is not None
    payloads = list(variant_prim_spec.payloadList.prependedItems)
    assert payloads
    assert payloads[0].assetPath == "./geo_mid.usda"


def test_material_variant_strips_scene_namespace_from_paths(tmp_path):
    """Scene-rooted mesh and material paths must normalise before authoring."""
    asset = make_asset(tmp_path, "table", with_materials=True)
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    variant_service.add_asset_material_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "wood",
        "bindings": {
            "/Scene/Furniture/Table_01/asset/Mesh":
                "/Scene/Furniture/Table_01/asset/Materials/Wood",
        },
    })

    layer = Sdf.Layer.FindOrOpen(str(asset / "variants.usda"))
    variant_prim_spec = layer.GetPrimAtPath(
        Sdf.Path("/table{finish=wood}Mesh"),
    )
    assert variant_prim_spec is not None
    rel = variant_prim_spec.relationships.get("material:binding")
    assert rel is not None
    targets = list(rel.targetPathList.GetAddedOrExplicitItems())
    assert targets == [Sdf.Path("/table/Materials/Wood")]


def test_configuration_variant_strips_scene_namespace(tmp_path):
    """Scene-rooted prim path normalises before activation is authored."""
    asset = make_asset(tmp_path, "box")
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Props/Box_01")
    variant_service.add_asset_configuration_variant(state, {
        "prim_path": "/Scene/Props/Box_01",
        "variant_set": "configuration",
        "variant_name": "open",
        "activations": {"/Scene/Props/Box_01/asset/MeshB": False},
    })

    layer = Sdf.Layer.FindOrOpen(str(asset / "variants.usda"))
    variant_prim_spec = layer.GetPrimAtPath(
        Sdf.Path("/box{configuration=open}MeshB"),
    )
    assert variant_prim_spec is not None
    assert variant_prim_spec.active is False


def test_list_asset_geo_files_excludes_canonical_layers(tmp_path):
    asset = make_asset(tmp_path, "table", with_materials=True)
    (asset / "geo_low.usda").write_text(
        "#usda 1.0\n(\n    defaultPrim = \"table\"\n)\n",
        encoding="utf-8",
    )
    (asset / "geo_high.usda").write_text(
        "#usda 1.0\n(\n    defaultPrim = \"table\"\n)\n",
        encoding="utf-8",
    )
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    result = variant_service.list_asset_geo_files(state, {
        "prim_path": "/Scene/Furniture/Table_01",
    })
    assert sorted(result["geo_files"]) == ["geo_high.usda", "geo_low.usda"]


def test_geometry_variant_rejects_cross_asset_payload(tmp_path):
    """Cross-asset payload refs violate ASWF self-containment and are refused."""
    asset = make_asset(tmp_path, "house")
    sibling = make_asset(tmp_path, "round_house")
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Architecture/House_01")
    with pytest.raises(ValueError, match="outside the asset folder"):
        variant_service.add_asset_geometry_variant(state, {
            "prim_path": "/Scene/Architecture/House_01",
            "variant_set": "lod",
            "variant_name": "low",
            "payloads": {"/Mesh": f"../{sibling.name}/geo.usda"},
        })
    assert not (asset / "variants.usda").exists()


def test_service_add_configuration_variant(tmp_path):
    asset = make_asset(tmp_path, "box")
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Props/Box_01")
    result = variant_service.add_asset_configuration_variant(state, {
        "prim_path": "/Scene/Props/Box_01",
        "variant_set": "configuration",
        "variant_name": "open",
        "activations": {"/MeshB": False},
    })
    assert result["category"] == "configuration"


def test_service_add_attribute_variant_accepts_relative_path_without_slash(
    tmp_path,
):
    """Override keys like 'lgt/Bulb' must normalize correctly under defaultPrim."""
    asset = make_asset(tmp_path, "lamp")
    geo_layer = Sdf.Layer.FindOrOpen(str(asset / "geo.usda"))
    mesh_spec = geo_layer.GetPrimAtPath("/lamp/Mesh")
    attr = Sdf.AttributeSpec(
        mesh_spec, "inputs:color", Sdf.ValueTypeNames.Color3f,
    )
    attr.default = (1.0, 1.0, 1.0)
    geo_layer.Save()

    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Props/Lamp_01")
    variant_service.add_asset_attribute_variant(state, {
        "prim_path": "/Scene/Props/Lamp_01",
        "variant_set": "tint",
        "variant_name": "blue",
        "overrides": {"Mesh": {"inputs:color": [0.2, 0.4, 1.0]}},
    })

    v_layer = Sdf.Layer.FindOrOpen(str(asset / "variants.usda"))
    assert v_layer.GetPrimAtPath("/lampMesh") is None, (
        "Malformed concatenation /lampMesh leaked into variants.usda"
    )
    variant_path = Sdf.Path("/lamp{tint=blue}Mesh")
    inner = v_layer.GetObjectAtPath(variant_path)
    assert inner is not None
    color = inner.attributes["inputs:color"].default
    assert tuple(float(c) for c in color) == (
        pytest.approx(0.2), pytest.approx(0.4), pytest.approx(1.0),
    )


def test_add_attribute_variant_refuses_when_scene_override_masks_attribute(tmp_path):
    """Refuse to author when a per-instance scene override would mask the variant."""
    asset = make_asset(tmp_path, "lamp")
    geo_layer = Sdf.Layer.FindOrOpen(str(asset / "geo.usda"))
    Sdf.AttributeSpec(
        geo_layer.GetPrimAtPath("/lamp/Mesh"),
        "inputs:color", Sdf.ValueTypeNames.Color3f,
    ).default = (1.0, 1.0, 1.0)
    geo_layer.Save()

    state, scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Props/Lamp_01",
    )
    scene_layer = Sdf.Layer.FindOrOpen(str(scene_path))
    Sdf.CreatePrimInLayer(scene_layer, "/Scene/Props/Lamp_01/asset/Mesh")
    over = scene_layer.GetPrimAtPath("/Scene/Props/Lamp_01/asset/Mesh")
    over.specifier = Sdf.SpecifierOver
    Sdf.AttributeSpec(
        over, "inputs:color", Sdf.ValueTypeNames.Color3f,
    ).default = (0.5, 0.5, 0.5)
    scene_layer.Save()
    state.stage = stage_utils.open_stage(scene_path)

    overrides = {"Mesh": {"inputs:color": [0.2, 0.4, 1.0]}}
    with pytest.raises(ValueError, match="mask"):
        variant_service.add_asset_attribute_variant(state, {
            "prim_path": "/Scene/Props/Lamp_01",
            "variant_set": "tint",
            "variant_name": "blue",
            "overrides": overrides,
        })


def test_add_attribute_variant_clears_masking_overrides_when_flag_set(tmp_path):
    """clear_masking_overrides=true strips the masking opinions and authors."""
    asset = make_asset(tmp_path, "lamp")
    geo_layer = Sdf.Layer.FindOrOpen(str(asset / "geo.usda"))
    Sdf.AttributeSpec(
        geo_layer.GetPrimAtPath("/lamp/Mesh"),
        "inputs:color", Sdf.ValueTypeNames.Color3f,
    ).default = (1.0, 1.0, 1.0)
    geo_layer.Save()

    state, scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Props/Lamp_01",
    )
    scene_layer = Sdf.Layer.FindOrOpen(str(scene_path))
    over = scene_layer.GetPrimAtPath(
        "/Scene/Props/Lamp_01/asset/Mesh",
    ) or Sdf.CreatePrimInLayer(scene_layer, "/Scene/Props/Lamp_01/asset/Mesh")
    over = scene_layer.GetPrimAtPath("/Scene/Props/Lamp_01/asset/Mesh")
    over.specifier = Sdf.SpecifierOver
    Sdf.AttributeSpec(
        over, "inputs:color", Sdf.ValueTypeNames.Color3f,
    ).default = (0.5, 0.5, 0.5)
    scene_layer.Save()
    state.stage = stage_utils.open_stage(scene_path)

    result = variant_service.add_asset_attribute_variant(state, {
        "prim_path": "/Scene/Props/Lamp_01",
        "variant_set": "tint",
        "variant_name": "blue",
        "overrides": {"Mesh": {"inputs:color": [0.2, 0.4, 1.0]}},
        "clear_masking_overrides": True,
    })
    assert result["category"] == "attribute"

    reopened = Sdf.Layer.FindOrOpen(str(scene_path))
    spec = reopened.GetPrimAtPath("/Scene/Props/Lamp_01/asset/Mesh")
    assert spec is None or "inputs:color" not in spec.attributes


def test_add_material_variant_refuses_when_scene_binding_masks_it(tmp_path):
    """Per-instance material:binding in scene.usda masks the variant; refuse."""
    asset = make_asset(tmp_path, "table", with_materials=True)
    state, scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Furniture/Table_01",
    )
    scene_layer = Sdf.Layer.FindOrOpen(str(scene_path))
    spec = scene_layer.GetPrimAtPath(
        "/Scene/Furniture/Table_01/asset/Mesh",
    ) or Sdf.CreatePrimInLayer(scene_layer, "/Scene/Furniture/Table_01/asset/Mesh")
    spec = scene_layer.GetPrimAtPath("/Scene/Furniture/Table_01/asset/Mesh")
    spec.specifier = Sdf.SpecifierOver
    rel = Sdf.RelationshipSpec(spec, "material:binding")
    rel.targetPathList.explicitItems = [Sdf.Path("/table/mtl/Wood")]
    scene_layer.Save()
    state.stage = stage_utils.open_stage(scene_path)

    with pytest.raises(ValueError, match="mask"):
        variant_service.add_asset_material_variant(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "finish",
            "variant_name": "wood",
            "bindings": {"/Mesh": "/Materials/Wood"},
        })


def test_add_material_variant_clears_masking_binding_when_flag_set(tmp_path):
    """clear_masking_overrides=true strips scene-level material:binding then authors."""
    asset = make_asset(tmp_path, "table", with_materials=True)
    state, scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Furniture/Table_01",
    )
    scene_layer = Sdf.Layer.FindOrOpen(str(scene_path))
    Sdf.CreatePrimInLayer(scene_layer, "/Scene/Furniture/Table_01/asset/Mesh")
    spec = scene_layer.GetPrimAtPath("/Scene/Furniture/Table_01/asset/Mesh")
    spec.specifier = Sdf.SpecifierOver
    rel = Sdf.RelationshipSpec(spec, "material:binding")
    rel.targetPathList.explicitItems = [Sdf.Path("/table/mtl/Wood")]
    scene_layer.Save()
    state.stage = stage_utils.open_stage(scene_path)

    result = variant_service.add_asset_material_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "wood",
        "bindings": {"/Mesh": "/Materials/Wood"},
        "clear_masking_overrides": True,
    })
    assert result["category"] == "material"

    reopened = Sdf.Layer.FindOrOpen(str(scene_path))
    spec_after = reopened.GetPrimAtPath("/Scene/Furniture/Table_01/asset/Mesh")
    assert spec_after is None or "material:binding" not in spec_after.relationships


def test_add_configuration_variant_refuses_when_scene_active_masks_it(tmp_path):
    """Per-instance 'active' opinion in scene.usda masks the variant; refuse."""
    asset = make_asset(tmp_path, "box")
    state, scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Props/Box_01",
    )
    scene_layer = Sdf.Layer.FindOrOpen(str(scene_path))
    Sdf.CreatePrimInLayer(scene_layer, "/Scene/Props/Box_01/asset/MeshB")
    spec = scene_layer.GetPrimAtPath("/Scene/Props/Box_01/asset/MeshB")
    spec.specifier = Sdf.SpecifierOver
    spec.SetInfo("active", False)
    scene_layer.Save()
    state.stage = stage_utils.open_stage(scene_path)

    with pytest.raises(ValueError, match="mask"):
        variant_service.add_asset_configuration_variant(state, {
            "prim_path": "/Scene/Props/Box_01",
            "variant_set": "config",
            "variant_name": "open",
            "activations": {"/MeshB": False},
        })


def test_add_configuration_variant_clears_masking_active_when_flag_set(tmp_path):
    """clear_masking_overrides=true clears scene-level active opinion then authors."""
    asset = make_asset(tmp_path, "box")
    state, scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Props/Box_01",
    )
    scene_layer = Sdf.Layer.FindOrOpen(str(scene_path))
    Sdf.CreatePrimInLayer(scene_layer, "/Scene/Props/Box_01/asset/MeshB")
    spec = scene_layer.GetPrimAtPath("/Scene/Props/Box_01/asset/MeshB")
    spec.specifier = Sdf.SpecifierOver
    spec.SetInfo("active", False)
    scene_layer.Save()
    state.stage = stage_utils.open_stage(scene_path)

    result = variant_service.add_asset_configuration_variant(state, {
        "prim_path": "/Scene/Props/Box_01",
        "variant_set": "config",
        "variant_name": "open",
        "activations": {"/MeshB": False},
        "clear_masking_overrides": True,
    })
    assert result["category"] == "configuration"

    reopened = Sdf.Layer.FindOrOpen(str(scene_path))
    spec_after = reopened.GetPrimAtPath("/Scene/Props/Box_01/asset/MeshB")
    assert spec_after is None or not spec_after.HasInfo("active")


def test_remove_asset_variant_set_scrubs_dangling_scene_selections(tmp_path):
    """remove_asset_variant_set drops the set's selection from every placement."""
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(
        asset, "lod", "high", lambda s, p: None, set_as_default=True,
    )
    state, scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Furniture/Table_01",
    )
    asset_layer = Sdf.Layer.FindOrOpen(str(scene_path))
    placement = asset_layer.GetPrimAtPath("/Scene/Furniture/Table_01/asset")
    placement.variantSelections["lod"] = "high"
    asset_layer.Save()
    state.stage = stage_utils.open_stage(scene_path)

    variant_service.remove_asset_variant_set(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "lod",
    })

    reopened = Sdf.Layer.FindOrOpen(str(scene_path))
    spec = reopened.GetPrimAtPath("/Scene/Furniture/Table_01/asset")
    assert spec is None or "lod" not in spec.variantSelections


def test_clear_scene_attribute_prunes_empty_over_ancestors(tmp_path):
    """Clearing the last attr on an over prim removes the now-empty ancestor specs."""
    asset = make_asset(tmp_path, "lamp")
    state, scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Props/Lamp_01",
    )
    scene_layer = Sdf.Layer.FindOrOpen(str(scene_path))
    Sdf.CreatePrimInLayer(
        scene_layer, "/Scene/Props/Lamp_01/asset/lgt/Bulb",
    )
    over = scene_layer.GetPrimAtPath("/Scene/Props/Lamp_01/asset/lgt/Bulb")
    over.specifier = Sdf.SpecifierOver
    scene_layer.GetPrimAtPath(
        "/Scene/Props/Lamp_01/asset/lgt",
    ).specifier = Sdf.SpecifierOver
    Sdf.AttributeSpec(
        over, "inputs:intensity", Sdf.ValueTypeNames.Float,
    ).default = 2000.0
    scene_layer.Save()
    state.stage = stage_utils.open_stage(scene_path)

    stage_utils.set_prim_attribute(
        state.stage,
        "/Scene/Props/Lamp_01/asset/lgt/Bulb",
        "inputs:intensity",
        None,
    )
    state.stage.GetRootLayer().Save()

    reopened = Sdf.Layer.FindOrOpen(str(scene_path))
    assert reopened.GetPrimAtPath(
        "/Scene/Props/Lamp_01/asset/lgt/Bulb",
    ) is None
    assert reopened.GetPrimAtPath(
        "/Scene/Props/Lamp_01/asset/lgt",
    ) is None


def test_add_attribute_variant_respects_declared_float_type_for_int_value(tmp_path):
    """Integer value for a Float attribute must author the variant as Float."""
    asset = make_asset(tmp_path, "lamp")
    geo_layer = Sdf.Layer.FindOrOpen(str(asset / "geo.usda"))
    Sdf.AttributeSpec(
        geo_layer.GetPrimAtPath("/lamp/Mesh"),
        "inputs:intensity", Sdf.ValueTypeNames.Float,
    ).default = 1000.0
    geo_layer.Save()

    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Props/Lamp_01")
    variant_service.add_asset_attribute_variant(state, {
        "prim_path": "/Scene/Props/Lamp_01",
        "variant_set": "brightness",
        "variant_name": "high",
        "overrides": {"Mesh": {"inputs:intensity": 4000}},
    })

    v_layer = Sdf.Layer.FindOrOpen(str(asset / "variants.usda"))
    variant_attr = v_layer.GetObjectAtPath(
        Sdf.Path("/lamp{brightness=high}Mesh.inputs:intensity"),
    )
    assert variant_attr is not None
    assert str(variant_attr.typeName) == "float", (
        f"Expected Float (UsdLux schema), got {variant_attr.typeName}"
    )
    assert abs(float(variant_attr.default) - 4000.0) < 1e-5


def test_service_add_attribute_variant_swaps_value_across_variants(tmp_path):
    """Per-variant attribute opinions; switching variants changes the value."""
    asset = make_asset(tmp_path, "lamp")
    # Author an inputs:color attribute on /lamp/Mesh as the baseline.
    geo_layer = Sdf.Layer.FindOrOpen(str(asset / "geo.usda"))
    mesh_spec = geo_layer.GetPrimAtPath("/lamp/Mesh")
    color_attr = Sdf.AttributeSpec(
        mesh_spec, "inputs:color", Sdf.ValueTypeNames.Color3f,
    )
    color_attr.default = (1.0, 1.0, 1.0)
    geo_layer.Save()

    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Props/Lamp_01")

    for name, value in (
        ("blue", [0.2, 0.4, 1.0]),
        ("red", [1.0, 0.2, 0.2]),
    ):
        result = variant_service.add_asset_attribute_variant(state, {
            "prim_path": "/Scene/Props/Lamp_01",
            "variant_set": "tint",
            "variant_name": name,
            "overrides": {"/Mesh": {"inputs:color": value}},
            "set_as_default": (name == "blue"),
        })
        assert result["category"] == "attribute"

    root_stage = Usd.Stage.Open(str(asset / "lamp.usda"))
    root = root_stage.GetDefaultPrim()
    vset = root.GetVariantSets().GetVariantSet("tint")
    mesh = root_stage.GetPrimAtPath("/lamp/Mesh")
    for name, expected in (
        ("blue", (0.2, 0.4, 1.0)),
        ("red", (1.0, 0.2, 0.2)),
    ):
        vset.SetVariantSelection(name)
        actual = tuple(float(c) for c in mesh.GetAttribute("inputs:color").Get())
        for got, want in zip(actual, expected, strict=True):
            assert abs(got - want) < 1e-5, f"{name}: {actual} != {expected}"


def test_service_list_variants_returns_scene_carriers(tmp_path):
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(asset, "finish", "wood", lambda s, p: None)
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    result = variant_service.list_variants(state, {
        "prim_path": "/Scene/Furniture/Table_01",
    })
    assert len(result["carriers"]) == 1
    carrier = result["carriers"][0]
    assert carrier["prim_path"] == "/Scene/Furniture/Table_01/asset"
    assert carrier["variant_sets"][0]["name"] == "finish"
    assert carrier["variant_sets"][0]["selection"] == "wood"


def test_service_remove_variant_set_clears_default(tmp_path):
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(
        asset, "finish", "wood", lambda s, p: None, set_as_default=True,
    )
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    result = variant_service.remove_asset_variant_set(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
    })
    assert result["removed"] is True
    summary = variant_utils.get_variant_summary(asset)
    assert summary.variant_sets == []
    assert not (asset / "variants.usda").exists()


def test_service_remove_variant_idempotent(tmp_path):
    asset = make_asset(tmp_path, "table")
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    result = variant_service.remove_asset_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "wood",
    })
    assert result["removed"] is False


def test_invalid_variant_name_raises(tmp_path):
    asset = make_asset(tmp_path, "table")
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    with pytest.raises(ValueError):
        variant_service.add_asset_material_variant(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "bad name",
            "variant_name": "wood",
            "bindings": {"/Mesh": "/Materials/Wood"},
        })


def test_variants_reference_stays_strongest_when_mtl_added_later(tmp_path):
    """variants.usda stays first in prepend references after mtl is re-added."""
    from bowerbot.utils.asset_folder_utils import (
        ensure_root_reference,
        find_root_file,
    )

    asset = make_asset(tmp_path, "table", with_materials=True)
    (asset / "table.usda").write_text(
        "#usda 1.0\n(\n    defaultPrim = \"table\"\n)\n\n"
        "def Xform \"table\" (\n"
        "    prepend payload = @./geo.usda@\n"
        ")\n{\n}\n",
        encoding="utf-8",
    )
    ensure_root_reference(asset, "mtl.usda")
    variant_utils.apply_variant(asset, "finish", "wood", lambda s, p: None)

    layer = Sdf.Layer.FindOrOpen(str(find_root_file(asset)))
    refs = list(layer.GetPrimAtPath("/table").referenceList.prependedItems)
    paths = [r.assetPath for r in refs]
    assert paths.index("./variants.usda") < paths.index("./mtl.usda")


def test_missing_bindings_raises_clear_error(tmp_path):
    """A missing 'bindings' param must surface as a useful ValueError."""
    asset = make_asset(tmp_path, "table", with_materials=True)
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    with pytest.raises(ValueError, match="bindings"):
        variant_service.add_asset_material_variant(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "finish",
            "variant_name": "wood",
        })


def test_apply_variant_auto_sets_default_for_first_variant(tmp_path):
    """First authored variant in a set becomes the default automatically."""
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(asset, "finish", "wood", lambda s, p: None)
    summary = variant_utils.get_variant_summary(asset)
    finish = next(s for s in summary.variant_sets if s.name == "finish")
    assert finish.selection == "wood"


def test_apply_variant_does_not_overwrite_existing_default(tmp_path):
    """Once a default exists, additional variants don't change it."""
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(asset, "finish", "wood", lambda s, p: None)
    variant_utils.apply_variant(asset, "finish", "metal", lambda s, p: None)
    summary = variant_utils.get_variant_summary(asset)
    finish = next(s for s in summary.variant_sets if s.name == "finish")
    assert finish.selection == "wood"


def test_variant_actually_overrides_mtl_direct_binding(tmp_path):
    """End-to-end: switching variant resolves to a different bound material."""
    from pxr import UsdShade

    asset = make_asset(tmp_path, "table", with_materials=True)
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Table_01")
    variant_service.add_asset_material_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "wood",
        "bindings": {"/Mesh": "/Materials/Wood"},
    })
    variant_service.add_asset_material_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "metal",
        "bindings": {"/Mesh": "/Materials/Metal"},
    })

    stage = Usd.Stage.Open(str(asset / "table.usda"))
    vs = stage.GetDefaultPrim().GetVariantSets().GetVariantSet("finish")

    vs.SetVariantSelection("wood")
    mat, _ = UsdShade.MaterialBindingAPI(
        stage.GetPrimAtPath("/table/Mesh"),
    ).ComputeBoundMaterial()
    assert mat.GetPath() == Sdf.Path("/table/Materials/Wood")

    vs.SetVariantSelection("metal")
    mat, _ = UsdShade.MaterialBindingAPI(
        stage.GetPrimAtPath("/table/Mesh"),
    ).ComputeBoundMaterial()
    assert mat.GetPath() == Sdf.Path("/table/Materials/Metal")


# ── Per-asset isolation ──


def test_remove_isolates_assets(tmp_path):
    """Asset A and B both have a 'finish' set; removing from A leaves B intact."""
    asset_a = make_asset(tmp_path, "alpha")
    asset_b = make_asset(tmp_path, "beta")

    scene_path = make_scene(tmp_path)
    setup = Usd.Stage.Open(str(scene_path))
    a = setup.DefinePrim("/Scene/Alpha_01", "Xform")
    a.GetReferences().AddReference("./alpha/alpha.usda")
    b = setup.DefinePrim("/Scene/Beta_01", "Xform")
    b.GetReferences().AddReference("./beta/beta.usda")
    setup.Save()
    del setup

    state = _empty_state()
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)

    variant_service.add_asset_configuration_variant(state, {
        "prim_path": "/Scene/Alpha_01",
        "variant_set": "finish",
        "variant_name": "default",
        "activations": {"/Mesh": True},
    })
    variant_service.add_asset_configuration_variant(state, {
        "prim_path": "/Scene/Beta_01",
        "variant_set": "finish",
        "variant_name": "default",
        "activations": {"/Mesh": True},
    })

    variant_service.remove_asset_variant_set(state, {
        "prim_path": "/Scene/Alpha_01",
        "variant_set": "finish",
    })

    assert variant_utils.get_variant_summary(asset_a).variant_sets == []
    assert any(
        s.name == "finish"
        for s in variant_utils.get_variant_summary(asset_b).variant_sets
    )


# ── Per-instance scene override ──


def test_select_variant_for_instance_authors_in_scene(tmp_path):
    """Per-instance override lands inline in scene.usda, not in the asset."""
    asset = make_asset(tmp_path, "table", with_materials=True)
    state, scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Furniture/Table_01",
    )
    variant_service.add_asset_material_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "wood",
        "bindings": {"/Mesh": "/Materials/Wood"},
        "set_as_default": True,
    })
    variant_service.add_asset_material_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "metal",
        "bindings": {"/Mesh": "/Materials/Metal"},
    })

    result = variant_service.select_asset_variant_for_instance(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "metal",
    })
    assert result["prim_path"] == "/Scene/Furniture/Table_01/asset"
    assert result["requested_prim_path"] == "/Scene/Furniture/Table_01"

    scene_layer = Sdf.Layer.FindOrOpen(str(scene_path))
    placement_spec = scene_layer.GetPrimAtPath(
        Sdf.Path("/Scene/Furniture/Table_01/asset"),
    )
    assert placement_spec is not None
    assert placement_spec.variantSelections.get("finish") == "metal"

    asset_root_layer = Sdf.Layer.FindOrOpen(str(asset / "table.usda"))
    asset_root_spec = asset_root_layer.GetPrimAtPath("/table")
    assert asset_root_spec.variantSelections.get("finish") == "wood"


def test_select_variant_for_instance_disambiguates_nested_carriers(tmp_path):
    """When two prims under a placement carry the same variant set, raise."""
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(asset, "finish", "wood", lambda s, p: None)

    state, scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Furniture/Table_01",
    )
    setup = Usd.Stage.Open(str(scene_path))
    setup.SetEditTarget(setup.GetRootLayer())
    nested = setup.DefinePrim(
        "/Scene/Furniture/Table_01/asset/extra", "Xform",
    )
    nested.GetReferences().AddReference(f"./{asset.name}/{asset.name}.usda")
    setup.Save()
    del setup
    state.stage = stage_utils.open_stage(scene_path)

    with pytest.raises(ValueError, match="multiple prims"):
        variant_service.select_asset_variant_for_instance(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "finish",
            "variant_name": "wood",
        })


def test_select_variant_for_instance_per_placement_isolation(tmp_path):
    """Overriding Table_01 must not affect Table_02."""
    asset = make_asset(tmp_path, "table", with_materials=True)
    variant_service_state, scene_path = place_asset_in_scene(
        tmp_path, asset, "/Scene/Furniture/Table_01",
    )
    variant_service.add_asset_material_variant(variant_service_state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "wood",
        "bindings": {"/Mesh": "/Materials/Wood"},
    })
    variant_service.add_asset_material_variant(variant_service_state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "metal",
        "bindings": {"/Mesh": "/Materials/Metal"},
    })

    setup = Usd.Stage.Open(str(scene_path))
    setup.SetEditTarget(setup.GetRootLayer())
    setup.DefinePrim("/Scene/Furniture/Table_02", "Xform")
    setup.DefinePrim(
        "/Scene/Furniture/Table_02/asset", "Xform",
    ).GetReferences().AddReference(f"./{asset.name}/{asset.name}.usda")
    setup.Save()
    del setup
    variant_service_state.stage = stage_utils.open_stage(scene_path)

    variant_service.select_asset_variant_for_instance(variant_service_state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "finish",
        "variant_name": "metal",
    })

    scene_layer = Sdf.Layer.FindOrOpen(str(scene_path))
    t01 = scene_layer.GetPrimAtPath(
        Sdf.Path("/Scene/Furniture/Table_01/asset"),
    )
    t02 = scene_layer.GetPrimAtPath(
        Sdf.Path("/Scene/Furniture/Table_02/asset"),
    )
    assert t01.variantSelections.get("finish") == "metal"
    assert "finish" not in (t02.variantSelections if t02 else {})


def test_select_variant_for_instance_unknown_set_raises(tmp_path):
    asset = make_asset(tmp_path, "table")
    state, _ = place_asset_in_scene(
        tmp_path, asset, "/Scene/Furniture/Table_01",
    )
    with pytest.raises(ValueError):
        variant_service.select_asset_variant_for_instance(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "missing",
            "variant_name": "x",
        })


# ── Validation ──


def test_validation_passes_on_clean_variants(tmp_path):
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(
        asset, "finish", "wood", lambda s, p: None, set_as_default=True,
    )
    issues = validation_utils.validate_asset_variants(asset)
    assert not any(i.severity.value == "error" for i in issues)


def test_validation_flags_missing_default_selection(tmp_path):
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(asset, "finish", "wood", lambda s, p: None)
    variant_utils.clear_default_variant(asset, "finish")
    issues = validation_utils.validate_asset_variants(asset)
    assert any(
        i.severity.value == "warning" and "default selection" in i.message
        for i in issues
    )


def test_validation_flags_orphan_reference(tmp_path):
    asset = make_asset(tmp_path, "table")
    variant_utils.apply_variant(asset, "finish", "wood", lambda s, p: None)
    (asset / "variants.usda").unlink()
    issues = validation_utils.validate_asset_variants(asset)
    assert any(
        i.severity.value == "error" and "orphan" in i.message.lower()
        for i in issues
    )


# ── Cleanup respects variant-bound materials ──


def test_cleanup_keeps_materials_referenced_only_by_variants(tmp_path):
    """cleanup_unused_in_folder must not delete materials referenced by any variant."""
    asset = make_asset(tmp_path, "chair", with_materials=True)
    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Chair_01")
    for variant in ("wood", "metal"):
        variant_service.add_asset_material_variant(state, {
            "prim_path": "/Scene/Furniture/Chair_01",
            "variant_set": "finish",
            "variant_name": variant,
            "bindings": {"/Mesh": f"/Materials/{variant.title()}"},
            "set_as_default": variant == "wood",
        })

    removed = material_utils.cleanup_unused_in_folder(asset)

    assert removed == []
    mtl_layer = Sdf.Layer.FindOrOpen(str(asset / "mtl.usda"))
    materials = mtl_layer.GetPrimAtPath(Sdf.Path("/chair/Materials"))
    assert materials is not None
    names = {child.name for child in materials.nameChildren}
    assert {"Wood", "Metal"}.issubset(names)


# ── Scene-level lighting variants ──


def make_scene_with_lights(
    parent: Path, lights: dict[str, str] | None = None,
) -> tuple[SceneState, Path]:
    """Build a scene.usda with /Scene/Lighting/<name> UsdLux prims at schema defaults."""
    scene_path = make_scene(parent)
    stage = Usd.Stage.Open(str(scene_path))
    specs = lights or {"Key_01": "RectLight", "Fill_01": "DiskLight"}
    schema_map = {
        "RectLight": UsdLux.RectLight,
        "DiskLight": UsdLux.DiskLight,
        "SphereLight": UsdLux.SphereLight,
        "CylinderLight": UsdLux.CylinderLight,
    }
    for name, type_name in specs.items():
        schema_map[type_name].Define(stage, f"/Scene/Lighting/{name}")
    stage.Save()

    state = _empty_state()
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)
    return state, scene_path


def test_add_scene_lighting_attribute_variant_authors_in_scene_usda(tmp_path):
    """Lighting attribute variant authors directly on /Scene/Lighting in scene.usda."""
    state, scene_path = make_scene_with_lights(tmp_path)

    result = variant_service.add_scene_lighting_attribute_variant(state, {
        "variant_set": "lightingVariant",
        "variant_name": "warm",
        "overrides": {
            "/Scene/Lighting/Key_01": {
                "inputs:intensity": 2000.0,
                "inputs:color": [1.0, 0.8, 0.6],
            },
        },
    })
    assert result["category"] == "lighting"
    assert result["carrier_prim_path"] == "/Scene/Lighting"

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    carrier = layer.GetPrimAtPath("/Scene/Lighting")
    assert carrier is not None
    assert "lightingVariant" in carrier.variantSets
    variant_spec = layer.GetObjectAtPath(
        Sdf.Path("/Scene/Lighting{lightingVariant=warm}Key_01.inputs:intensity"),
    )
    assert variant_spec is not None
    assert abs(float(variant_spec.default) - 2000.0) < 1e-5


def test_scene_lighting_attribute_variant_swaps_value_across_variants(tmp_path):
    """Switching variants on /Scene/Lighting actually swaps the composed value."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    for name, intensity in (("warm", 2000.0), ("cool", 800.0)):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "lightingVariant",
            "variant_name": name,
            "overrides": {
                "/Scene/Lighting/Key_01": {"inputs:intensity": intensity},
            },
            "set_as_default": name == "warm",
        })

    stage = Usd.Stage.Open(str(scene_path))
    light = stage.GetPrimAtPath("/Scene/Lighting/Key_01")
    carrier = stage.GetPrimAtPath("/Scene/Lighting")
    vset = carrier.GetVariantSets().GetVariantSet("lightingVariant")
    for name, expected in (("warm", 2000.0), ("cool", 800.0)):
        vset.SetVariantSelection(name)
        actual = float(light.GetAttribute("inputs:intensity").Get())
        assert abs(actual - expected) < 1e-5


def test_add_scene_lighting_selection_variant_toggles_active(tmp_path):
    """Selection variant flips 'active' per variant on pre-placed sibling lights."""
    state, scene_path = make_scene_with_lights(
        tmp_path, {"Key_Disk": "DiskLight", "Key_Rect": "RectLight"},
    )
    for name, disk, rect in (
        ("disk", True, False), ("rect", False, True),
    ):
        variant_service.add_scene_lighting_selection_variant(state, {
            "variant_set": "lightSelection",
            "variant_name": name,
            "activations": {
                "/Scene/Lighting/Key_Disk": disk,
                "/Scene/Lighting/Key_Rect": rect,
            },
            "set_as_default": name == "disk",
        })

    stage = Usd.Stage.Open(str(scene_path))
    carrier = stage.GetPrimAtPath("/Scene/Lighting")
    vset = carrier.GetVariantSets().GetVariantSet("lightSelection")
    vset.SetVariantSelection("rect")
    assert stage.GetPrimAtPath("/Scene/Lighting/Key_Rect").IsActive()
    assert not stage.GetPrimAtPath("/Scene/Lighting/Key_Disk").IsActive()


def test_add_scene_lighting_variant_refuses_target_outside_carrier(tmp_path):
    """Targeting a non-/Scene/Lighting prim must raise."""
    state, _ = make_scene_with_lights(tmp_path)
    with pytest.raises(ValueError, match="must be under /Scene/Lighting"):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "lightingVariant",
            "variant_name": "warm",
            "overrides": {
                "/Scene/Furniture/Table_01": {"inputs:intensity": 1500.0},
            },
        })


def test_add_scene_lighting_variant_refuses_non_usdlux(tmp_path):
    """Targeting a non-UsdLux prim under /Scene/Lighting must raise."""
    state, scene_path = make_scene_with_lights(tmp_path)
    stage = Usd.Stage.Open(str(scene_path))
    stage.DefinePrim("/Scene/Lighting/NotALight", "Xform")
    stage.Save()
    state.stage = stage_utils.open_stage(scene_path)

    with pytest.raises(ValueError, match="not a UsdLux light"):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "lightingVariant",
            "variant_name": "warm",
            "overrides": {
                "/Scene/Lighting/NotALight": {"inputs:intensity": 1500.0},
            },
        })


def test_add_scene_lighting_variant_refuses_without_carrier(tmp_path):
    """No /Scene/Lighting prim means no lighting variant can be authored."""
    scene_path = make_scene(tmp_path)
    state = _empty_state()
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)

    with pytest.raises(ValueError, match="No lighting carrier"):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "lightingVariant",
            "variant_name": "warm",
            "overrides": {
                "/Scene/Lighting/Key_01": {"inputs:intensity": 1500.0},
            },
        })


def test_scene_lighting_attribute_variant_refuses_when_direct_opinion_masks(tmp_path):
    """Direct attribute opinion in scene.usda must refuse the lighting variant."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    light_spec = layer.GetPrimAtPath("/Scene/Lighting/Key_01")
    Sdf.AttributeSpec(
        light_spec, "inputs:intensity", Sdf.ValueTypeNames.Float,
    ).default = 3000.0
    layer.Save()
    state.stage = stage_utils.open_stage(scene_path)

    with pytest.raises(ValueError, match="would mask"):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "lightingVariant",
            "variant_name": "warm",
            "overrides": {
                "/Scene/Lighting/Key_01": {"inputs:intensity": 1500.0},
            },
        })


def test_scene_lighting_attribute_variant_clears_masking_when_flag_set(tmp_path):
    """clear_masking_overrides=true removes the direct opinion then authors the variant."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    light_spec = layer.GetPrimAtPath("/Scene/Lighting/Key_01")
    Sdf.AttributeSpec(
        light_spec, "inputs:intensity", Sdf.ValueTypeNames.Float,
    ).default = 3000.0
    layer.Save()
    state.stage = stage_utils.open_stage(scene_path)

    variant_service.add_scene_lighting_attribute_variant(state, {
        "variant_set": "lightingVariant",
        "variant_name": "warm",
        "overrides": {
            "/Scene/Lighting/Key_01": {"inputs:intensity": 1500.0},
        },
        "clear_masking_overrides": True,
    })

    reopened = Sdf.Layer.FindOrOpen(str(scene_path))
    direct = reopened.GetPrimAtPath("/Scene/Lighting/Key_01")
    assert direct is None or "inputs:intensity" not in direct.attributes


def test_select_scene_variant_writes_selection_on_carrier(tmp_path):
    """select_scene_variant authors variantSelections directly on the carrier prim."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    for name in ("warm", "cool"):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "lightingVariant",
            "variant_name": name,
            "overrides": {
                "/Scene/Lighting/Key_01": {
                    "inputs:intensity": 2000.0 if name == "warm" else 800.0,
                },
            },
            "set_as_default": name == "warm",
        })

    variant_service.select_scene_variant(state, {
        "prim_path": "/Scene/Lighting",
        "variant_set": "lightingVariant",
        "variant_name": "cool",
    })

    reopened = Usd.Stage.Open(str(scene_path))
    carrier = reopened.GetPrimAtPath("/Scene/Lighting")
    vset = carrier.GetVariantSets().GetVariantSet("lightingVariant")
    assert vset.GetVariantSelection() == "cool"


def test_remove_scene_variant_drops_one_variant(tmp_path):
    """remove_scene_variant removes a single variant; remaining variants survive."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    for name in ("warm", "cool"):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "lightingVariant",
            "variant_name": name,
            "overrides": {
                "/Scene/Lighting/Key_01": {"inputs:intensity": 2000.0},
            },
        })

    result = variant_service.remove_scene_variant(state, {
        "prim_path": "/Scene/Lighting",
        "variant_set": "lightingVariant",
        "variant_name": "warm",
    })
    assert result["removed"] is True

    reopened = Usd.Stage.Open(str(scene_path))
    carrier = reopened.GetPrimAtPath("/Scene/Lighting")
    vset = carrier.GetVariantSets().GetVariantSet("lightingVariant")
    assert "warm" not in vset.GetVariantNames()
    assert "cool" in vset.GetVariantNames()


def test_remove_scene_variant_set_drops_whole_set(tmp_path):
    """remove_scene_variant_set removes the variant set and its selection."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    variant_service.add_scene_lighting_attribute_variant(state, {
        "variant_set": "lightingVariant",
        "variant_name": "warm",
        "overrides": {
            "/Scene/Lighting/Key_01": {"inputs:intensity": 2000.0},
        },
        "set_as_default": True,
    })

    result = variant_service.remove_scene_variant_set(state, {
        "prim_path": "/Scene/Lighting",
        "variant_set": "lightingVariant",
    })
    assert result["removed"] is True

    reopened = Sdf.Layer.FindOrOpen(str(scene_path))
    carrier = reopened.GetPrimAtPath("/Scene/Lighting")
    assert carrier is None or "lightingVariant" not in carrier.variantSets
    assert carrier is None or "lightingVariant" not in carrier.variantSelections


def test_save_scene_snapshot_preserves_scene_variant_sets(tmp_path):
    """save_scene_snapshot keeps the variant set arc (FlattenLayerStack preserves variants)."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    for name, intensity in (("warm", 2000.0), ("cool", 800.0)):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "lightingVariant",
            "variant_name": name,
            "overrides": {
                "/Scene/Lighting/Key_01": {"inputs:intensity": intensity},
            },
            "set_as_default": name == "warm",
        })

    snapshot_path = stage_utils.save_scene_snapshot(scene_path, "look_a")
    snap = Usd.Stage.Open(str(snapshot_path))
    carrier = snap.GetPrimAtPath("/Scene/Lighting")
    vset = carrier.GetVariantSets().GetVariantSet("lightingVariant")
    assert set(vset.GetVariantNames()) == {"warm", "cool"}
    light = snap.GetPrimAtPath("/Scene/Lighting/Key_01")
    for name, expected in (("warm", 2000.0), ("cool", 800.0)):
        vset.SetVariantSelection(name)
        actual = float(light.GetAttribute("inputs:intensity").Get())
        assert abs(actual - expected) < 1e-5


# ── Scene model-selection variants ──


def _make_model_selection_state(tmp_path):
    """Set up a project + library with 3 asset folders + one placement on the table."""
    from bowerbot.project import Project, ProjectMeta

    library = tmp_path / "library"
    library.mkdir()
    for name in ("chair", "stool", "bench"):
        make_asset(library, name)

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_assets = project_dir / "assets"
    project_assets.mkdir()
    make_asset(project_assets, "table")

    scene_path = project_dir / "scene.usda"
    setup = Usd.Stage.CreateNew(str(scene_path))
    UsdGeom.SetStageMetersPerUnit(setup, 1.0)
    UsdGeom.SetStageUpAxis(setup, UsdGeom.Tokens.y)
    root = setup.DefinePrim("/Scene", "Xform")
    setup.SetDefaultPrim(root)
    setup.DefinePrim("/Scene/Furniture", "Xform")
    setup.DefinePrim("/Scene/Furniture/Table_01", "Xform")
    asset_child = setup.DefinePrim("/Scene/Furniture/Table_01/asset", "Xform")
    asset_child.GetReferences().AddReference("./assets/table/table.usda")
    setup.Save()
    del setup

    state = _empty_state()
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)
    state.project = Project(path=project_dir, meta=ProjectMeta(name="proj"))
    state.library_dir = library
    return state, scene_path, library


def test_add_scene_model_selection_variant_auto_promotes_existing_ref(tmp_path):
    """First call promotes the placement's direct ref into a variant body automatically."""
    state, scene_path, library = _make_model_selection_state(tmp_path)

    result = variant_service.add_scene_model_selection_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "modelType",
        "variant_name": "chair",
        "asset_file_path": str(library / "chair" / "chair.usda"),
    })
    assert result["promoted_existing_variant"] == "table"

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    placement = layer.GetPrimAtPath("/Scene/Furniture/Table_01/asset")
    assert not placement.HasInfo("references"), (
        "Direct references should be cleared after auto-promotion"
    )
    table_body = layer.GetObjectAtPath(
        Sdf.Path("/Scene/Furniture/Table_01{modelType=table}asset"),
    )
    assert table_body is not None, "Auto-promoted 'table' variant body must exist"
    table_refs = [r.assetPath for r in table_body.referenceList.prependedItems]
    assert any("table.usda" in p for p in table_refs)

    chair_body = layer.GetObjectAtPath(
        Sdf.Path("/Scene/Furniture/Table_01{modelType=chair}asset"),
    )
    assert chair_body is not None
    chair_refs = [r.assetPath for r in chair_body.referenceList.prependedItems]
    assert any("chair.usda" in p for p in chair_refs)

    carrier = layer.GetPrimAtPath("/Scene/Furniture/Table_01")
    assert carrier.variantSelections["modelType"] == "table", (
        "Auto-promoted variant should be the default (preserves original choice)"
    )


def test_add_scene_model_selection_variant_first_call_refuses_name_collision(tmp_path):
    """If the user picks the auto-promoted name for their new variant, refuse with guidance."""
    state, _, library = _make_model_selection_state(tmp_path)
    with pytest.raises(ValueError, match="collides with auto-promoted"):
        variant_service.add_scene_model_selection_variant(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "modelType",
            "variant_name": "table",
            "asset_file_path": str(library / "chair" / "chair.usda"),
        })


def test_add_scene_model_selection_variant_extends_existing_set(tmp_path):
    """Second call doesn't trigger promotion (direct ref already gone) — just extends the set."""
    state, scene_path, library = _make_model_selection_state(tmp_path)

    variant_service.add_scene_model_selection_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "modelType",
        "variant_name": "chair",
        "asset_file_path": str(library / "chair" / "chair.usda"),
    })
    result = variant_service.add_scene_model_selection_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "modelType",
        "variant_name": "stool",
        "asset_file_path": str(library / "stool" / "stool.usda"),
    })
    assert result["promoted_existing_variant"] is None

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    vset = layer.GetPrimAtPath("/Scene/Furniture/Table_01").variantSets["modelType"]
    assert set(vset.variants.keys()) == {"table", "chair", "stool"}


def test_remove_scene_variant_flags_collapsed_model_selection(tmp_path):
    """Auto-promotion gives us 4 variants (table+chair+stool+bench); removing 3 collapses to 1."""
    state, scene_path, library = _make_model_selection_state(tmp_path)

    for name in ("chair", "stool", "bench"):
        variant_service.add_scene_model_selection_variant(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "modelType",
            "variant_name": name,
            "asset_file_path": str(library / name / f"{name}.usda"),
        })
    # Set now has: table (auto-promoted) + chair + stool + bench

    for name in ("chair", "stool"):
        variant_service.remove_scene_variant(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "modelType",
            "variant_name": name,
        })
    result = variant_service.remove_scene_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "modelType",
        "variant_name": "bench",
    })

    suspects = result["suspect_variant_sets"]
    assert len(suspects) == 1
    assert suspects[0]["variant_set"] == "modelType"
    assert suspects[0]["carrier_prim_path"] == "/Scene/Furniture/Table_01"


def test_scene_model_selection_variant_authors_distinct_references(tmp_path):
    """Each variant body authors a different reference path on /asset."""
    state, scene_path, library = _make_model_selection_state(tmp_path)
    for i, name in enumerate(("chair", "stool")):
        variant_service.add_scene_model_selection_variant(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "modelType",
            "variant_name": name,
            "asset_file_path": str(library / name / f"{name}.usda"),
            "clear_masking_overrides": (i == 0),
        })

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    for name in ("chair", "stool"):
        body = layer.GetObjectAtPath(
            Sdf.Path(f"/Scene/Furniture/Table_01{{modelType={name}}}asset"),
        )
        assert body is not None, f"Variant body for '{name}' missing"
        refs = [r.assetPath for r in body.referenceList.prependedItems]
        assert any(f"{name}.usda" in r for r in refs), (
            f"Variant '{name}' did not author its expected reference; got {refs}"
        )


def test_add_scene_model_selection_variant_refuses_when_no_project(tmp_path):
    """Without a project bound, the tool must refuse (can't stage assets)."""
    scene_path = make_scene(tmp_path)
    setup = Usd.Stage.Open(str(scene_path))
    UsdGeom.SetStageMetersPerUnit(setup, 1.0)
    setup.DefinePrim("/Scene", "Xform")
    setup.DefinePrim("/Scene/Furniture", "Xform")
    setup.DefinePrim("/Scene/Furniture/Slot_01", "Xform")
    setup.DefinePrim("/Scene/Furniture/Slot_01/asset", "Xform")
    setup.Save()

    state = _empty_state()
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)

    with pytest.raises(ValueError, match="No project"):
        variant_service.add_scene_model_selection_variant(state, {
            "prim_path": "/Scene/Furniture/Slot_01",
            "variant_set": "modelType",
            "variant_name": "x",
            "asset_file_path": "/nonexistent.usda",
        })


def test_add_scene_model_selection_variant_refuses_wrapper_without_asset_child(tmp_path):
    """A wrapper that doesn't follow place_asset's wrapper/asset convention is rejected."""
    state, scene_path, library = _make_model_selection_state(tmp_path)
    state.stage.DefinePrim("/Scene/Furniture/Bare", "Xform")
    state.stage.Save()
    state.stage = stage_utils.open_stage(state.stage_path)

    with pytest.raises(ValueError, match="'/asset' child"):
        variant_service.add_scene_model_selection_variant(state, {
            "prim_path": "/Scene/Furniture/Bare",
            "variant_set": "modelType",
            "variant_name": "x",
            "asset_file_path": str(library / "chair" / "chair.usda"),
        })


def test_add_scene_model_selection_variant_refuses_missing_placement(tmp_path):
    """A non-existent prim_path raises clearly."""
    state, _, library = _make_model_selection_state(tmp_path)
    with pytest.raises(ValueError, match="Scene placement not found"):
        variant_service.add_scene_model_selection_variant(state, {
            "prim_path": "/Scene/Furniture/DoesNotExist",
            "variant_set": "modelType",
            "variant_name": "x",
            "asset_file_path": str(library / "chair" / "chair.usda"),
        })


def test_add_scene_model_selection_variant_overwrites_same_variant_name(tmp_path):
    """Calling with the same set+variant overwrites the reference (last write wins)."""
    state, scene_path, library = _make_model_selection_state(tmp_path)
    variant_service.add_scene_model_selection_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "modelType",
        "variant_name": "primary",
        "asset_file_path": str(library / "chair" / "chair.usda"),
        "clear_masking_overrides": True,
    })
    variant_service.add_scene_model_selection_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "modelType",
        "variant_name": "primary",
        "asset_file_path": str(library / "stool" / "stool.usda"),
    })

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    body = layer.GetObjectAtPath(
        Sdf.Path("/Scene/Furniture/Table_01{modelType=primary}asset"),
    )
    refs = [r.assetPath for r in body.referenceList.prependedItems]
    assert any("stool.usda" in r for r in refs), (
        f"Last write should have replaced chair with stool; got {refs}"
    )
    assert not any("chair.usda" in r for r in refs)


def test_add_scene_model_selection_variant_refuses_missing_asset_file(tmp_path):
    """Asset file that can't be resolved anywhere must raise."""
    state, _, _ = _make_model_selection_state(tmp_path)
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        variant_service.add_scene_model_selection_variant(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "modelType",
            "variant_name": "ghost",
            "asset_file_path": "/nonexistent/ghost.usda",
            "clear_masking_overrides": True,
        })


def test_delete_project_asset_refuses_when_referenced_by_inactive_variant(tmp_path):
    """An asset referenced ONLY by a non-selected variant body must still block deletion."""
    import shutil

    from bowerbot.services import asset_service

    state, scene_path, library = _make_model_selection_state(tmp_path)
    project_assets = state.resolve_assets_dir()
    shutil.copytree(library / "chair", project_assets / "chair")
    variant_service.add_scene_model_selection_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "modelType",
        "variant_name": "chair",
        "asset_file_path": str(project_assets / "chair" / "chair.usda"),
    })
    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    placement = layer.GetPrimAtPath("/Scene/Furniture/Table_01")
    assert placement.variantSelections["modelType"] == "table"

    with pytest.raises(ValueError, match="still referenced"):
        asset_service.delete_project_asset(state, {"name": "chair"})

    assert (project_assets / "chair").exists()


def test_remove_scene_variant_set_demotes_model_selection_to_direct_ref(tmp_path):
    """Removing a model_selection set restores the active variant's ref as a direct ref."""
    state, scene_path, library = _make_model_selection_state(tmp_path)
    variant_service.add_scene_model_selection_variant(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "modelType",
        "variant_name": "chair",
        "asset_file_path": str(library / "chair" / "chair.usda"),
    })
    result = variant_service.remove_scene_variant_set(state, {
        "prim_path": "/Scene/Furniture/Table_01",
        "variant_set": "modelType",
    })
    assert result["demoted_to_direct_ref"] == "table"

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    placement = layer.GetPrimAtPath("/Scene/Furniture/Table_01")
    assert "modelType" not in placement.variantSets
    asset = layer.GetPrimAtPath("/Scene/Furniture/Table_01/asset")
    refs = [r.assetPath for r in asset.referenceList.prependedItems]
    assert any("table.usda" in r for r in refs), (
        f"Demoted variant's reference should be back on /asset; got {refs}"
    )


def test_remove_scene_variant_set_does_not_demote_non_model_selection(tmp_path):
    """A lighting selection variant set has no /asset child; removal doesn't author phantom refs."""
    state, scene_path = make_scene_with_lights(
        tmp_path, {"Key_A": "RectLight", "Key_B": "DiskLight"},
    )
    for name, a, b in (("a", True, False), ("b", False, True)):
        variant_service.add_scene_lighting_selection_variant(state, {
            "variant_set": "lampType",
            "variant_name": name,
            "activations": {
                "/Scene/Lighting/Key_A": a,
                "/Scene/Lighting/Key_B": b,
            },
        })
    result = variant_service.remove_scene_variant_set(state, {
        "prim_path": "/Scene/Lighting",
        "variant_set": "lampType",
    })
    assert result["demoted_to_direct_ref"] is None


def test_remove_prim_cascade_cleans_model_selection_set(tmp_path):
    """Deleting the /asset child cascades through every variant body and drops the set."""
    state, scene_path, library = _make_model_selection_state(tmp_path)
    for i, name in enumerate(("chair", "stool")):
        variant_service.add_scene_model_selection_variant(state, {
            "prim_path": "/Scene/Furniture/Table_01",
            "variant_set": "modelType",
            "variant_name": name,
            "asset_file_path": str(library / name / f"{name}.usda"),
            "clear_masking_overrides": (i == 0),
        })

    stage_utils.remove_prim(state.stage, "/Scene/Furniture/Table_01/asset")

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    wrapper = layer.GetPrimAtPath("/Scene/Furniture/Table_01")
    assert wrapper is None or "modelType" not in wrapper.variantSets


# ── Orphan-over cleanup invariant ──


def test_remove_prim_clears_orphan_scene_variant_overs(tmp_path):
    """Deleting a scene light removes its over-specs from every scene variant body."""
    state, scene_path = make_scene_with_lights(
        tmp_path, {"Key_Disk": "DiskLight", "Key_Rect": "RectLight"},
    )
    for name, disk, rect in (("disk", True, False), ("rect", False, True)):
        variant_service.add_scene_lighting_selection_variant(state, {
            "variant_set": "lampType",
            "variant_name": name,
            "activations": {
                "/Scene/Lighting/Key_Disk": disk,
                "/Scene/Lighting/Key_Rect": rect,
            },
        })

    stage_utils.remove_prim(state.stage, "/Scene/Lighting/Key_Rect")

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    carrier = layer.GetPrimAtPath("/Scene/Lighting")
    vset = carrier.variantSets["lampType"]
    for variant_name in vset.variants.keys():
        body = vset.variants[variant_name].primSpec
        assert "Key_Rect" not in body.nameChildren, (
            f"Orphan over-spec for Key_Rect still present in lampType={variant_name}"
        )


def test_remove_light_from_folder_clears_orphan_asset_variant_overs(tmp_path):
    """Removing an asset light cleans variant body opinions in the asset's variants.usda."""
    from bowerbot.schemas import LightParams, LightType
    from bowerbot.utils import light_utils

    asset = make_asset(tmp_path, "lamp")
    light_utils.add_light_to_folder(
        asset, "Bulb",
        LightParams(light_type=LightType.SPHERE, intensity=1000.0),
    )
    light_utils.add_light_to_folder(
        asset, "Disk",
        LightParams(light_type=LightType.DISK, intensity=1000.0),
    )

    variant_utils.apply_variant(
        asset, "lampSelect", "bulb",
        lambda stage, prim_path: (
            stage.OverridePrim(f"{prim_path}/lgt/Bulb").SetActive(True),
            stage.OverridePrim(f"{prim_path}/lgt/Disk").SetActive(False),
        ),
    )
    variant_utils.apply_variant(
        asset, "lampSelect", "disk",
        lambda stage, prim_path: (
            stage.OverridePrim(f"{prim_path}/lgt/Bulb").SetActive(False),
            stage.OverridePrim(f"{prim_path}/lgt/Disk").SetActive(True),
        ),
    )

    light_utils.remove_light_from_folder(asset, "Bulb")

    variants_layer = Sdf.Layer.FindOrOpen(str(asset / "variants.usda"))
    root_spec = variants_layer.GetPrimAtPath("/lamp")
    vset = root_spec.variantSets["lampSelect"]
    for variant_name in vset.variants.keys():
        body = vset.variants[variant_name].primSpec
        lgt = body.nameChildren.get("lgt") if body else None
        if lgt is not None:
            assert "Bulb" not in lgt.nameChildren, (
                f"Orphan over for Bulb in variant {variant_name}"
            )


def test_material_cleanup_clears_orphan_asset_variant_overs(tmp_path):
    """Unused-material cleanup removes variant body opinions on the dropped material."""
    asset = make_asset(tmp_path, "table")
    mtl_path = asset / "mtl.usda"
    mtl_stage = Usd.Stage.CreateNew(str(mtl_path))
    UsdGeom.SetStageMetersPerUnit(mtl_stage, 1.0)
    UsdGeom.SetStageUpAxis(mtl_stage, UsdGeom.Tokens.y)
    mtl_root = mtl_stage.DefinePrim("/table", "Xform")
    mtl_stage.SetDefaultPrim(mtl_root)
    mtl_stage.DefinePrim("/table/mtl", "Scope")
    UsdShade.Material.Define(mtl_stage, "/table/mtl/Wood")
    UsdShade.Material.Define(mtl_stage, "/table/mtl/Metal")
    mtl_stage.Save()
    from bowerbot.utils.asset_folder_utils import ensure_root_reference
    ensure_root_reference(asset, "mtl.usda")

    variant_utils.apply_variant(
        asset, "finish", "wood",
        lambda stage, _p: stage.OverridePrim("/table/mtl/Wood").SetActive(True),
    )
    variant_utils.apply_variant(
        asset, "finish", "metal",
        lambda stage, _p: stage.OverridePrim("/table/mtl/Metal").SetActive(True),
    )
    pre = Sdf.Layer.FindOrOpen(str(asset / "variants.usda"))
    assert pre.GetObjectAtPath(Sdf.Path("/table{finish=wood}mtl/Wood")) is not None

    material_utils.cleanup_unused_in_folder(asset)

    reopened = Sdf.Layer.FindOrOpen(str(asset / "variants.usda"))
    assert reopened.GetObjectAtPath(
        Sdf.Path("/table{finish=wood}mtl/Wood"),
    ) is None
    assert reopened.GetObjectAtPath(
        Sdf.Path("/table{finish=metal}mtl/Metal"),
    ) is None


# ── Suspect-variant-set detection ──


def test_find_suspect_variant_sets_flags_collapsed_selection(tmp_path):
    """Selection variant collapsed to a single prim after cleanup is flagged."""
    state, scene_path = make_scene_with_lights(
        tmp_path, {"Key_Disk": "DiskLight", "Key_Rect": "RectLight"},
    )
    for name, disk, rect in (("disk", True, False), ("rect", False, True)):
        variant_service.add_scene_lighting_selection_variant(state, {
            "variant_set": "lampType",
            "variant_name": name,
            "activations": {
                "/Scene/Lighting/Key_Disk": disk,
                "/Scene/Lighting/Key_Rect": rect,
            },
        })
    stage_utils.remove_prim(state.stage, "/Scene/Lighting/Key_Rect")

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    suspects = variant_utils.find_suspect_variant_sets(layer, "/Scene/Lighting")
    assert suspects == [("/Scene/Lighting", "lampType")]


def test_find_suspect_variant_sets_ignores_attribute_value_variants(tmp_path):
    """Attribute-value variants on a single prim are NOT flagged (they're legitimate)."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    for name, value in (("blue", [0.2, 0.4, 1.0]), ("red", [1.0, 0.2, 0.2])):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "lampColor",
            "variant_name": name,
            "overrides": {"/Scene/Lighting/Key_01": {"inputs:color": value}},
        })

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    suspects = variant_utils.find_suspect_variant_sets(layer, "/Scene/Lighting")
    assert suspects == []


def test_find_suspect_variant_sets_ignores_single_variant_set(tmp_path):
    """A set with only one variant is not 'suspect' — there was no choice to lose."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    variant_service.add_scene_lighting_selection_variant(state, {
        "variant_set": "lampType",
        "variant_name": "only",
        "activations": {"/Scene/Lighting/Key_01": True},
    })

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    suspects = variant_utils.find_suspect_variant_sets(layer, "/Scene/Lighting")
    assert suspects == []


def test_rename_prim_relabels_variant_body_overs(tmp_path):
    """Renaming a prim updates every variant body over-spec to the new name."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    for name, value in (("warm", 2000.0), ("cool", 800.0)):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "mood",
            "variant_name": name,
            "overrides": {"/Scene/Lighting/Key_01": {"inputs:intensity": value}},
        })

    stage_utils.rename_prim(
        state.stage, "/Scene/Lighting/Key_01", "/Scene/Lighting/Hero",
    )

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    vset = layer.GetPrimAtPath("/Scene/Lighting").variantSets["mood"]
    for variant_name in vset.variants.keys():
        body = vset.variants[variant_name].primSpec
        assert "Key_01" not in body.nameChildren, (
            f"Stale over for Key_01 in mood={variant_name}"
        )
        assert "Hero" in body.nameChildren, (
            f"Renamed over for Hero missing in mood={variant_name}"
        )


def test_rename_prim_preserves_variant_body_attribute_values(tmp_path):
    """Renaming preserves the authored attribute values inside variant bodies."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    for name, value in (("warm", 2000.0), ("cool", 800.0)):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "mood",
            "variant_name": name,
            "overrides": {"/Scene/Lighting/Key_01": {"inputs:intensity": value}},
        })

    stage_utils.rename_prim(
        state.stage, "/Scene/Lighting/Key_01", "/Scene/Lighting/Hero",
    )

    reopened = Usd.Stage.Open(str(scene_path))
    carrier = reopened.GetPrimAtPath("/Scene/Lighting")
    vset = carrier.GetVariantSets().GetVariantSet("mood")
    light = reopened.GetPrimAtPath("/Scene/Lighting/Hero")
    for name, expected in (("warm", 2000.0), ("cool", 800.0)):
        vset.SetVariantSelection(name)
        actual = float(light.GetAttribute("inputs:intensity").Get())
        assert abs(actual - expected) < 1e-5


def test_remove_prim_cascade_drops_empty_variants_and_sets(tmp_path):
    """When orphan cleanup empties every variant body, the variant set is auto-removed."""
    state, scene_path = make_scene_with_lights(tmp_path, {"Key_01": "RectLight"})
    for name, value in (("warm", 2000.0), ("cool", 800.0)):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "brightness",
            "variant_name": name,
            "overrides": {"/Scene/Lighting/Key_01": {"inputs:intensity": value}},
            "set_as_default": name == "warm",
        })

    stage_utils.remove_prim(state.stage, "/Scene/Lighting/Key_01")

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    carrier = layer.GetPrimAtPath("/Scene/Lighting")
    assert carrier is None or "brightness" not in carrier.variantSets
    assert carrier is None or "brightness" not in carrier.variantSelections
    if carrier is not None:
        name_list = carrier.variantSetNameList
        for items in (
            name_list.prependedItems, name_list.appendedItems,
            name_list.addedItems, name_list.explicitItems,
            name_list.orderedItems,
        ):
            assert "brightness" not in items


def test_remove_prim_cascade_keeps_set_with_surviving_targets(tmp_path):
    """When some variant bodies still have opinions, the set survives (cleanup is non-greedy)."""
    state, scene_path = make_scene_with_lights(
        tmp_path, {"Key_A": "RectLight", "Key_B": "DiskLight"},
    )
    for name, a, b in (("a", True, False), ("b", False, True)):
        variant_service.add_scene_lighting_selection_variant(state, {
            "variant_set": "lampType",
            "variant_name": name,
            "activations": {
                "/Scene/Lighting/Key_A": a,
                "/Scene/Lighting/Key_B": b,
            },
        })

    stage_utils.remove_prim(state.stage, "/Scene/Lighting/Key_B")

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    carrier = layer.GetPrimAtPath("/Scene/Lighting")
    assert "lampType" in carrier.variantSets
    vset = carrier.variantSets["lampType"]
    assert set(vset.variants.keys()) == {"a", "b"}


def test_remove_light_returns_suspect_variant_sets_for_scene_lamp(tmp_path):
    """remove_light surfaces suspect scene variant sets in its return data."""
    from bowerbot.services import light_service

    state, scene_path = make_scene_with_lights(
        tmp_path, {"Key_Disk": "DiskLight", "Key_Rect": "RectLight"},
    )
    for name, disk, rect in (("disk", True, False), ("rect", False, True)):
        variant_service.add_scene_lighting_selection_variant(state, {
            "variant_set": "lampType",
            "variant_name": name,
            "activations": {
                "/Scene/Lighting/Key_Disk": disk,
                "/Scene/Lighting/Key_Rect": rect,
            },
        })

    result = light_service.remove_light(state, {
        "prim_path": "/Scene/Lighting/Key_Rect",
    })

    suspects = result.get("suspect_variant_sets", [])
    assert len(suspects) == 1
    assert suspects[0]["variant_set"] == "lampType"
    assert suspects[0]["scope"] == "scene"
    assert suspects[0]["carrier_prim_path"] == "/Scene/Lighting"


def test_remove_light_returns_suspect_variant_sets_for_asset_light(tmp_path):
    """Asset-side remove_light surfaces suspect asset variant sets in return data."""
    from bowerbot.schemas import LightParams, LightType
    from bowerbot.services import light_service
    from bowerbot.utils import light_utils

    asset = make_asset(tmp_path, "lamp")
    light_utils.add_light_to_folder(
        asset, "Bulb", LightParams(light_type=LightType.SPHERE),
    )
    light_utils.add_light_to_folder(
        asset, "Disk", LightParams(light_type=LightType.DISK),
    )

    for name, bulb, disk in (("bulb", True, False), ("disk", False, True)):
        variant_utils.apply_variant(
            asset, "lampSelect", name,
            lambda stage, prim_path, b=bulb, d=disk: (
                stage.OverridePrim(f"{prim_path}/lgt/Bulb").SetActive(b),
                stage.OverridePrim(f"{prim_path}/lgt/Disk").SetActive(d),
            ),
        )

    state, _ = place_asset_in_scene(tmp_path, asset, "/Scene/Furniture/Lamp_01")
    result = light_service.remove_light(state, {
        "prim_path": "/Scene/Furniture/Lamp_01/asset/lgt/Disk",
    })

    suspects = result.get("suspect_variant_sets", [])
    assert len(suspects) == 1
    assert suspects[0]["variant_set"] == "lampSelect"
    assert suspects[0]["scope"] == "asset"
    assert suspects[0]["asset_path"] == str(asset)


def test_scene_lighting_variant_stages_hdri_when_passed_with_textures_prefix(tmp_path):
    """LLM passing './textures/foo.hdr' for a file not yet in project must stage from library."""
    from bowerbot.project import Project, ProjectMeta

    library = tmp_path / "library" / "hdris"
    library.mkdir(parents=True)
    (library / "sunflowers_4k.hdr").write_bytes(b"fake hdr")

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    scene_path = make_scene(project_dir)
    stage = stage_utils.open_stage(scene_path)
    UsdLux.DomeLight.Define(stage, "/Scene/Lighting/Dome_01")
    stage.Save()

    state = _empty_state()
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)
    state.project = Project(path=project_dir, meta=ProjectMeta(name="project"))
    state.library_dir = library.parent

    variant_service.add_scene_lighting_attribute_variant(state, {
        "variant_set": "domeTexture",
        "variant_name": "sunflowers",
        "overrides": {
            "/Scene/Lighting/Dome_01": {
                "inputs:texture:file": "./textures/sunflowers_4k.hdr",
            },
        },
    })

    assert (project_dir / "textures" / "sunflowers_4k.hdr").exists()


def test_scene_lighting_variant_refuses_unresolvable_texture(tmp_path):
    """Authoring a texture variant with a file that isn't anywhere must raise."""
    from bowerbot.project import Project, ProjectMeta

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    scene_path = make_scene(project_dir)
    stage = stage_utils.open_stage(scene_path)
    UsdLux.DomeLight.Define(stage, "/Scene/Lighting/Dome_01")
    stage.Save()

    state = _empty_state()
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)
    state.project = Project(path=project_dir, meta=ProjectMeta(name="project"))
    state.library_dir = tmp_path / "empty_library"

    with pytest.raises(ValueError, match="Cannot stage texture"):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "domeTexture",
            "variant_name": "nonexistent",
            "overrides": {
                "/Scene/Lighting/Dome_01": {
                    "inputs:texture:file": "nonexistent_hdri.hdr",
                },
            },
        })


def test_scene_lighting_variant_stages_hdri_textures(tmp_path):
    """HDRI variant authoring stages library files into project/textures/ + writes rel paths."""
    from bowerbot.project import Project, ProjectMeta

    library = tmp_path / "library" / "hdris"
    library.mkdir(parents=True)
    for name in ("studio_garden_4k.hdr", "lake_pier_4k.hdr"):
        (library / name).write_bytes(b"fake hdr")

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    scene_path = make_scene(project_dir)
    stage = stage_utils.open_stage(scene_path)
    UsdLux.DomeLight.Define(stage, "/Scene/Lighting/Dome_01")
    stage.Save()

    state = _empty_state()
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)
    state.project = Project(path=project_dir, meta=ProjectMeta(name="project"))
    state.library_dir = library.parent

    for name in ("studio_garden_4k.hdr", "lake_pier_4k.hdr"):
        variant_service.add_scene_lighting_attribute_variant(state, {
            "variant_set": "domeTexture",
            "variant_name": name.removesuffix(".hdr"),
            "overrides": {
                "/Scene/Lighting/Dome_01": {"inputs:texture:file": name},
            },
        })

    assert (project_dir / "textures" / "studio_garden_4k.hdr").exists()
    assert (project_dir / "textures" / "lake_pier_4k.hdr").exists()

    layer = Sdf.Layer.FindOrOpen(str(scene_path))
    body = layer.GetObjectAtPath(
        Sdf.Path("/Scene/Lighting{domeTexture=studio_garden_4k}Dome_01"),
    )
    attr = body.attributes.get("inputs:texture:file")
    assert attr is not None
    assert str(attr.default.path) == "./textures/studio_garden_4k.hdr"


def test_remove_light_from_folder_cleans_up_empty_variants_layer(tmp_path):
    """When orphan cascade empties variants.usda, the file is auto-deleted."""
    from bowerbot.schemas import LightParams, LightType
    from bowerbot.utils import light_utils

    asset = make_asset(tmp_path, "lamp")
    light_utils.add_light_to_folder(
        asset, "Bulb", LightParams(light_type=LightType.SPHERE),
    )

    variant_utils.apply_variant(
        asset, "brightness", "high",
        lambda stage, prim_path: stage.OverridePrim(
            f"{prim_path}/lgt/Bulb",
        ).CreateAttribute(
            "inputs:intensity", Sdf.ValueTypeNames.Float,
        ).Set(2000.0),
    )
    variant_utils.apply_variant(
        asset, "brightness", "low",
        lambda stage, prim_path: stage.OverridePrim(
            f"{prim_path}/lgt/Bulb",
        ).CreateAttribute(
            "inputs:intensity", Sdf.ValueTypeNames.Float,
        ).Set(500.0),
    )
    assert (asset / "variants.usda").exists()

    light_utils.remove_light_from_folder(asset, "Bulb")

    assert not (asset / "variants.usda").exists(), (
        "Empty variants.usda should be auto-deleted after cascade"
    )
