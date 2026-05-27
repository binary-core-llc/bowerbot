# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""apply_physics_api / remove_physics_api auto-detect scope from the prim path."""

from __future__ import annotations

from pathlib import Path

from pxr import Usd, UsdGeom

from bowerbot.config import SceneDefaults
from bowerbot.schemas import ASWFLayerNames, PhysicsApiName
from bowerbot.services import physics_service
from bowerbot.state import SceneState
from bowerbot.utils import physics_utils, stage_utils


def _scene_with_scene_authored_cubes(tmp_path: Path) -> SceneState:
    scene_path = tmp_path / "scene.usda"
    stage = Usd.Stage.CreateNew(str(scene_path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim("/Scene", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, "/Scene/Cube_Anchor").AddTranslateOp().Set(
        (0.0, 5.0, 0.0),
    )
    UsdGeom.Cube.Define(stage, "/Scene/Cube_Bob").AddTranslateOp().Set(
        (0.0, 3.0, 0.0),
    )
    stage.Save()
    del stage
    state = SceneState(scene_defaults=SceneDefaults())
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)
    return state


def _make_asset(parent: Path, name: str) -> Path:
    asset_dir = parent / name
    asset_dir.mkdir()
    geo = Usd.Stage.CreateNew(str(asset_dir / ASWFLayerNames.GEO))
    UsdGeom.SetStageMetersPerUnit(geo, 1.0)
    UsdGeom.SetStageUpAxis(geo, UsdGeom.Tokens.y)
    root = geo.DefinePrim(f"/{name}", "Xform")
    geo.SetDefaultPrim(root)
    UsdGeom.Cube.Define(geo, f"/{name}/Body")
    geo.Save()
    root_stage = Usd.Stage.CreateNew(str(asset_dir / f"{name}.usda"))
    UsdGeom.SetStageMetersPerUnit(root_stage, 1.0)
    UsdGeom.SetStageUpAxis(root_stage, UsdGeom.Tokens.y)
    root_prim = root_stage.DefinePrim(f"/{name}", "Xform")
    root_stage.SetDefaultPrim(root_prim)
    root_prim.GetPayloads().AddPayload(f"./{ASWFLayerNames.GEO}")
    root_stage.Save()
    return asset_dir


def _scene_with_placed_asset(tmp_path: Path) -> SceneState:
    asset_dir = _make_asset(tmp_path, "BoxA")
    scene_path = tmp_path / "scene.usda"
    stage = Usd.Stage.CreateNew(str(scene_path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim("/Scene", "Xform")
    stage.SetDefaultPrim(root)
    stage.DefinePrim("/Scene/Things/Box_A", "Xform")
    child = stage.DefinePrim("/Scene/Things/Box_A/asset", "Xform")
    child.GetReferences().AddReference(
        f"./{asset_dir.name}/{asset_dir.name}.usda",
    )
    stage.Save()
    del stage
    state = SceneState(scene_defaults=SceneDefaults())
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)
    return state


def test_autodetect_scope_returns_scene_for_raw_cube(tmp_path: Path) -> None:
    state = _scene_with_scene_authored_cubes(tmp_path)

    assert physics_utils.autodetect_scope(
        state.stage, "/Scene/Cube_Anchor",
    ) == "scene"


def test_autodetect_scope_returns_asset_for_asset_internal_prim(
    tmp_path: Path,
) -> None:
    state = _scene_with_placed_asset(tmp_path)

    assert physics_utils.autodetect_scope(
        state.stage, "/Scene/Things/Box_A/asset/Body",
    ) == "asset"


def test_apply_api_on_scene_only_prim_without_scope_succeeds(
    tmp_path: Path,
) -> None:
    """The exact pendulum failure: raw Cubes + omitted scope used to raise."""
    state = _scene_with_scene_authored_cubes(tmp_path)

    result = physics_service.apply_physics_api(state, {
        "api_name": PhysicsApiName.RIGID_BODY.value,
        "prim_path": "/Scene/Cube_Anchor",
    })

    assert result["scope"] == "scene"
    state.stage = stage_utils.open_stage(state.stage_path)
    prim = state.stage.GetPrimAtPath("/Scene/Cube_Anchor")
    assert "PhysicsRigidBodyAPI" in prim.GetAppliedSchemas()


def test_apply_api_explicit_scene_overrides_autodetect_on_placement(
    tmp_path: Path,
) -> None:
    state = _scene_with_placed_asset(tmp_path)

    result = physics_service.apply_physics_api(state, {
        "api_name": PhysicsApiName.RIGID_BODY.value,
        "prim_path": "/Scene/Things/Box_A",
        "scope": "scene",
    })

    assert result["scope"] == "scene"
