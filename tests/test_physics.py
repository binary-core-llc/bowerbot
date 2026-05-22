# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""UsdPhysics applied-API authoring: introspection, apply, remove, summary."""

from __future__ import annotations

from pathlib import Path

import pytest
from pxr import Sdf, Usd, UsdGeom

from bowerbot.config import SceneDefaults
from bowerbot.schemas import ASWFLayerNames, PhysicsApiName
from bowerbot.services import physics_service
from bowerbot.state import SceneState
from bowerbot.utils import physics_utils, stage_utils


# ── Fixtures ──


def _make_asset(parent: Path, name: str) -> Path:
    """Minimal ASWF asset: root + geo.usda with a Mesh and a Cube under Xform."""
    asset_dir = parent / name
    asset_dir.mkdir()

    geo_stage = Usd.Stage.CreateNew(str(asset_dir / ASWFLayerNames.GEO))
    UsdGeom.SetStageMetersPerUnit(geo_stage, 1.0)
    UsdGeom.SetStageUpAxis(geo_stage, UsdGeom.Tokens.y)
    root = geo_stage.DefinePrim(f"/{name}", "Xform")
    geo_stage.SetDefaultPrim(root)
    UsdGeom.Mesh.Define(geo_stage, f"/{name}/Body")
    UsdGeom.Cube.Define(geo_stage, f"/{name}/Block")
    geo_stage.DefinePrim(f"/{name}/Group", "Xform")
    geo_stage.Save()

    root_stage = Usd.Stage.CreateNew(str(asset_dir / f"{name}.usda"))
    UsdGeom.SetStageMetersPerUnit(root_stage, 1.0)
    UsdGeom.SetStageUpAxis(root_stage, UsdGeom.Tokens.y)
    root_prim = root_stage.DefinePrim(f"/{name}", "Xform")
    root_stage.SetDefaultPrim(root_prim)
    root_prim.GetPayloads().AddPayload(f"./{ASWFLayerNames.GEO}")
    root_stage.Save()
    return asset_dir


def _place_asset(parent: Path, asset_dir: Path) -> SceneState:
    """Create scene.usda placing the asset, return a SceneState bound to it."""
    scene_path = parent / "scene.usda"
    scene = Usd.Stage.CreateNew(str(scene_path))
    UsdGeom.SetStageMetersPerUnit(scene, 1.0)
    UsdGeom.SetStageUpAxis(scene, UsdGeom.Tokens.y)
    scene_root = scene.DefinePrim("/Scene", "Xform")
    scene.SetDefaultPrim(scene_root)
    scene.DefinePrim("/Scene/Models/Item_01", "Xform")
    asset_child = scene.DefinePrim("/Scene/Models/Item_01/asset", "Xform")
    asset_child.GetReferences().AddReference(
        f"./{asset_dir.name}/{asset_dir.name}.usda",
    )
    scene.Save()
    del scene

    state = SceneState(scene_defaults=SceneDefaults())
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)
    return state


# ── Schema introspection ──


def test_list_api_properties_rigid_body():
    info = physics_utils.list_api_properties(PhysicsApiName.RIGID_BODY)
    assert info.api_name == "PhysicsRigidBodyAPI"
    assert info.target_requirement == "UsdGeom.Xformable"
    assert info.requires_companion_api is None

    attr_names = {p.name for p in info.properties if p.kind == "attribute"}
    assert "physics:rigidBodyEnabled" in attr_names
    assert "physics:kinematicEnabled" in attr_names
    assert "physics:velocity" in attr_names

    rel_names = {p.name for p in info.properties if p.kind == "relationship"}
    assert "physics:simulationOwner" in rel_names


def test_list_api_properties_mesh_collision_exposes_approximation_tokens():
    info = physics_utils.list_api_properties(PhysicsApiName.MESH_COLLISION)
    assert info.target_requirement == "UsdGeom.Mesh"
    assert info.requires_companion_api == "PhysicsCollisionAPI"

    approx = next(
        p for p in info.properties if p.name == "physics:approximation"
    )
    assert approx.kind == "attribute"
    assert "convexHull" in approx.allowed_tokens
    assert "none" in approx.allowed_tokens


def test_list_api_properties_collision_targets_gprim():
    info = physics_utils.list_api_properties(PhysicsApiName.COLLISION)
    assert info.target_requirement == "UsdGeom.Gprim"

    attr_names = {p.name for p in info.properties if p.kind == "attribute"}
    assert "physics:collisionEnabled" in attr_names


# ── Layer lifecycle ──


def test_ensure_physics_layer_creates_phy_usda(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    path = physics_utils.ensure_physics_layer(asset)
    assert path == asset / ASWFLayerNames.PHY
    assert path.exists()
    layer = Sdf.Layer.FindOrOpen(str(path))
    assert layer.defaultPrim == "chair"


def test_ensure_physics_referenced_adds_phy_to_root(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    physics_utils.ensure_physics_layer(asset)
    physics_utils.ensure_physics_referenced(asset)

    root_stage = Usd.Stage.Open(str(asset / "chair.usda"))
    root_prim = root_stage.GetDefaultPrim()
    refs = stage_utils.get_prim_ref_paths(root_prim)
    assert f"./{ASWFLayerNames.PHY}" in refs


# ── Apply ──


def test_apply_rigid_body_on_root_xform(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    result = physics_utils.apply_api(
        asset, "/chair", PhysicsApiName.RIGID_BODY,
        attributes={"physics:kinematicEnabled": True},
    )
    assert result["api_name"] == "PhysicsRigidBodyAPI"
    assert result["companion_api"] is None
    assert "physics:kinematicEnabled" in result["attributes_set"]

    layer = Sdf.Layer.FindOrOpen(str(asset / ASWFLayerNames.PHY))
    prim_spec = layer.GetPrimAtPath("/chair")
    apis = physics_utils._read_api_schemas(prim_spec)
    assert "PhysicsRigidBodyAPI" in apis
    assert prim_spec.attributes["physics:kinematicEnabled"].default is True


def test_apply_collision_on_mesh(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    result = physics_utils.apply_api(
        asset, "/chair/Body", PhysicsApiName.COLLISION,
    )
    assert result["api_name"] == "PhysicsCollisionAPI"

    layer = Sdf.Layer.FindOrOpen(str(asset / ASWFLayerNames.PHY))
    apis = physics_utils._read_api_schemas(layer.GetPrimAtPath("/chair/Body"))
    assert "PhysicsCollisionAPI" in apis


def test_apply_collision_on_xform_refused(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    with pytest.raises(ValueError, match="requires UsdGeom.Gprim"):
        physics_utils.apply_api(
            asset, "/chair/Group", PhysicsApiName.COLLISION,
        )
    # No phy.usda should have been created since validation failed first.
    assert not (asset / ASWFLayerNames.PHY).exists()


def test_apply_mesh_collision_auto_applies_collision(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    result = physics_utils.apply_api(
        asset, "/chair/Body", PhysicsApiName.MESH_COLLISION,
        attributes={"physics:approximation": "convexHull"},
    )
    assert result["companion_api"] == "PhysicsCollisionAPI"

    layer = Sdf.Layer.FindOrOpen(str(asset / ASWFLayerNames.PHY))
    apis = physics_utils._read_api_schemas(layer.GetPrimAtPath("/chair/Body"))
    assert "PhysicsCollisionAPI" in apis
    assert "PhysicsMeshCollisionAPI" in apis


def test_apply_mesh_collision_on_cube_refused(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    with pytest.raises(ValueError, match="requires UsdGeom.Mesh"):
        physics_utils.apply_api(
            asset, "/chair/Block", PhysicsApiName.MESH_COLLISION,
        )


def test_apply_refuses_unknown_attribute(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    with pytest.raises(ValueError, match="does not declare attribute"):
        physics_utils.apply_api(
            asset, "/chair", PhysicsApiName.RIGID_BODY,
            attributes={"physics:bogus": 1.0},
        )


# ── Remove ──


def test_remove_api_drops_authored_attributes(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    physics_utils.apply_api(
        asset, "/chair", PhysicsApiName.RIGID_BODY,
        attributes={"physics:kinematicEnabled": True},
    )

    changed = physics_utils.remove_api(
        asset, "/chair", PhysicsApiName.RIGID_BODY,
    )
    assert changed is True

    layer = Sdf.Layer.FindOrOpen(str(asset / ASWFLayerNames.PHY))
    prim_spec = layer.GetPrimAtPath("/chair")
    if prim_spec is not None:
        assert "PhysicsRigidBodyAPI" not in physics_utils._read_api_schemas(prim_spec)
        assert "physics:kinematicEnabled" not in prim_spec.attributes


def test_remove_collision_drops_mesh_collision(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    physics_utils.apply_api(
        asset, "/chair/Body", PhysicsApiName.MESH_COLLISION,
        attributes={"physics:approximation": "convexHull"},
    )

    physics_utils.remove_api(
        asset, "/chair/Body", PhysicsApiName.COLLISION,
    )

    layer = Sdf.Layer.FindOrOpen(str(asset / ASWFLayerNames.PHY))
    prim_spec = layer.GetPrimAtPath("/chair/Body")
    apis = (
        physics_utils._read_api_schemas(prim_spec) if prim_spec else []
    )
    assert "PhysicsCollisionAPI" not in apis
    assert "PhysicsMeshCollisionAPI" not in apis


# ── Summary + cleanup ──


def test_summary_reports_authored_opinions(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    physics_utils.apply_api(
        asset, "/chair", PhysicsApiName.RIGID_BODY,
        attributes={"physics:kinematicEnabled": True},
    )
    physics_utils.apply_api(
        asset, "/chair/Body", PhysicsApiName.MESH_COLLISION,
        attributes={"physics:approximation": "convexHull"},
    )

    summary = physics_utils.get_physics_summary(asset)
    assert summary.has_physics_layer is True
    paths = {p.prim_path for p in summary.prims}
    assert "/chair" in paths
    assert "/chair/Body" in paths

    body_entry = next(p for p in summary.prims if p.prim_path == "/chair/Body")
    assert "PhysicsCollisionAPI" in body_entry.applied_apis
    assert "PhysicsMeshCollisionAPI" in body_entry.applied_apis


def test_cleanup_if_empty_deletes_phy_usda(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    physics_utils.apply_api(
        asset, "/chair", PhysicsApiName.RIGID_BODY,
    )
    physics_utils.remove_api(
        asset, "/chair", PhysicsApiName.RIGID_BODY,
    )

    cleaned = physics_utils.cleanup_if_empty(asset)
    assert cleaned is True
    assert not (asset / ASWFLayerNames.PHY).exists()

    root_stage = Usd.Stage.Open(str(asset / "chair.usda"))
    root_prim = root_stage.GetDefaultPrim()
    refs = stage_utils.get_prim_ref_paths(root_prim)
    assert f"./{ASWFLayerNames.PHY}" not in refs


# ── Service integration (asset routed through scene placement) ──


def test_service_applies_via_scene_placement(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    state = _place_asset(tmp_path, asset)

    result = physics_service.apply_api(state, {
        "api_name": "PhysicsCollisionAPI",
        "prim_path": "/Scene/Models/Item_01/asset/Body",
        "attributes": {"physics:collisionEnabled": True},
    })

    assert result["api_name"] == "PhysicsCollisionAPI"
    assert result["asset_folder"] == "chair"
    assert result["asset_prim_path"] == "/chair/Body"

    layer = Sdf.Layer.FindOrOpen(str(asset / ASWFLayerNames.PHY))
    apis = physics_utils._read_api_schemas(layer.GetPrimAtPath("/chair/Body"))
    assert "PhysicsCollisionAPI" in apis


def test_service_summary_returns_authored_apis(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    state = _place_asset(tmp_path, asset)

    physics_service.apply_api(state, {
        "api_name": "PhysicsRigidBodyAPI",
        "prim_path": "/Scene/Models/Item_01/asset",
        "attributes": {"physics:kinematicEnabled": True},
    })

    summary = physics_service.get_physics_summary(state, {
        "prim_path": "/Scene/Models/Item_01/asset",
    })
    assert summary["has_physics_layer"] is True
    paths = {p["prim_path"] for p in summary["prims"]}
    assert "/chair" in paths


def test_service_list_api_properties():
    state = SceneState(scene_defaults=SceneDefaults())
    info = physics_service.list_api_properties(state, {
        "api_name": "PhysicsRigidBodyAPI",
    })
    assert info["api_name"] == "PhysicsRigidBodyAPI"
    attr_names = {p["name"] for p in info["properties"] if p["kind"] == "attribute"}
    assert "physics:rigidBodyEnabled" in attr_names


# ── Masking policy ──


def _author_scene_override(
    state: SceneState, placement_attr_path: str, attr_name: str, value,
    *, attr_type=None,
) -> None:
    """Author an attribute opinion on a placement to simulate a DCC override."""
    stage_utils.set_prim_attribute(
        state.stage, placement_attr_path, attr_name, value,
        expected_type=attr_type,
    )
    state.stage.GetRootLayer().Save()


def test_apply_refuses_when_scene_has_masking_attribute(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    state = _place_asset(tmp_path, asset)

    physics_service.apply_api(state, {
        "api_name": "PhysicsCollisionAPI",
        "prim_path": "/Scene/Models/Item_01/asset/Body",
        "attributes": {"physics:collisionEnabled": True},
    })

    _author_scene_override(
        state, "/Scene/Models/Item_01/asset/Body",
        "physics:collisionEnabled", False, attr_type=Sdf.ValueTypeNames.Bool,
    )
    state.stage = stage_utils.open_stage(state.stage_path)

    with pytest.raises(ValueError, match="scene.usda opinion"):
        physics_service.apply_api(state, {
            "api_name": "PhysicsCollisionAPI",
            "prim_path": "/Scene/Models/Item_01/asset/Body",
            "attributes": {"physics:collisionEnabled": True},
        })


def test_apply_clear_masking_overrides_removes_scene_opinion(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    state = _place_asset(tmp_path, asset)

    physics_service.apply_api(state, {
        "api_name": "PhysicsCollisionAPI",
        "prim_path": "/Scene/Models/Item_01/asset/Body",
        "attributes": {"physics:collisionEnabled": True},
    })

    _author_scene_override(
        state, "/Scene/Models/Item_01/asset/Body",
        "physics:collisionEnabled", False, attr_type=Sdf.ValueTypeNames.Bool,
    )
    state.stage = stage_utils.open_stage(state.stage_path)

    result = physics_service.apply_api(state, {
        "api_name": "PhysicsCollisionAPI",
        "prim_path": "/Scene/Models/Item_01/asset/Body",
        "attributes": {"physics:collisionEnabled": True},
        "clear_masking_overrides": True,
    })

    cleared = result["cleared_masking_opinions"]
    assert len(cleared) == 1
    assert cleared[0]["key"] == "physics:collisionEnabled"

    scene_layer = state.stage.GetRootLayer()
    placement_spec = scene_layer.GetPrimAtPath(
        "/Scene/Models/Item_01/asset/Body",
    )
    if placement_spec is not None:
        assert "physics:collisionEnabled" not in placement_spec.attributes


def test_apply_confirm_masked_writes_phy_despite_scene_override(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    state = _place_asset(tmp_path, asset)

    physics_service.apply_api(state, {
        "api_name": "PhysicsCollisionAPI",
        "prim_path": "/Scene/Models/Item_01/asset/Body",
        "attributes": {"physics:collisionEnabled": True},
    })

    _author_scene_override(
        state, "/Scene/Models/Item_01/asset/Body",
        "physics:collisionEnabled", False, attr_type=Sdf.ValueTypeNames.Bool,
    )
    state.stage = stage_utils.open_stage(state.stage_path)

    result = physics_service.apply_api(state, {
        "api_name": "PhysicsCollisionAPI",
        "prim_path": "/Scene/Models/Item_01/asset/Body",
        "attributes": {"physics:collisionEnabled": True},
        "confirm_masked": True,
    })

    assert result["cleared_masking_opinions"] == []
    scene_layer = state.stage.GetRootLayer()
    placement_spec = scene_layer.GetPrimAtPath(
        "/Scene/Models/Item_01/asset/Body",
    )
    assert "physics:collisionEnabled" in placement_spec.attributes


def test_remove_api_refuses_with_scene_masking(tmp_path):
    asset = _make_asset(tmp_path, "chair")
    state = _place_asset(tmp_path, asset)

    physics_service.apply_api(state, {
        "api_name": "PhysicsCollisionAPI",
        "prim_path": "/Scene/Models/Item_01/asset/Body",
        "attributes": {"physics:collisionEnabled": True},
    })
    _author_scene_override(
        state, "/Scene/Models/Item_01/asset/Body",
        "physics:collisionEnabled", False, attr_type=Sdf.ValueTypeNames.Bool,
    )
    state.stage = stage_utils.open_stage(state.stage_path)

    with pytest.raises(ValueError, match="scene.usda opinion"):
        physics_service.remove_api(state, {
            "api_name": "PhysicsCollisionAPI",
            "prim_path": "/Scene/Models/Item_01/asset/Body",
        })
