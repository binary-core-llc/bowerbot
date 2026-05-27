# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Cross-tool integrity matrix: destructive op x rel-bearing schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from pxr import Usd, UsdGeom, UsdPhysics

from bowerbot.config import SceneDefaults
from bowerbot.schemas import ASWFLayerNames, PhysicsApiName, PhysicsJointType
from bowerbot.services import physics_service, stage_service
from bowerbot.state import SceneState
from bowerbot.utils import stage_utils

_JOINT_TYPES: tuple[PhysicsJointType, ...] = tuple(PhysicsJointType)


def _make_asset(parent: Path, name: str) -> Path:
    asset_dir = parent / name
    asset_dir.mkdir()
    geo = Usd.Stage.CreateNew(str(asset_dir / ASWFLayerNames.GEO))
    UsdGeom.SetStageMetersPerUnit(geo, 1.0)
    UsdGeom.SetStageUpAxis(geo, UsdGeom.Tokens.y)
    root = geo.DefinePrim(f"/{name}", "Xform")
    geo.SetDefaultPrim(root)
    UsdGeom.Cube.Define(geo, f"/{name}/Block")
    geo.Save()
    root_stage = Usd.Stage.CreateNew(str(asset_dir / f"{name}.usda"))
    UsdGeom.SetStageMetersPerUnit(root_stage, 1.0)
    UsdGeom.SetStageUpAxis(root_stage, UsdGeom.Tokens.y)
    root_prim = root_stage.DefinePrim(f"/{name}", "Xform")
    root_stage.SetDefaultPrim(root_prim)
    root_prim.GetPayloads().AddPayload(f"./{ASWFLayerNames.GEO}")
    root_stage.Save()
    return asset_dir


def _scene_with_two_assets(tmp_path: Path) -> SceneState:
    a = _make_asset(tmp_path, "BoxA")
    b = _make_asset(tmp_path, "BoxB")
    scene_path = tmp_path / "scene.usda"
    scene = Usd.Stage.CreateNew(str(scene_path))
    UsdGeom.SetStageMetersPerUnit(scene, 1.0)
    UsdGeom.SetStageUpAxis(scene, UsdGeom.Tokens.y)
    root = scene.DefinePrim("/Scene", "Xform")
    scene.SetDefaultPrim(root)
    for placement, asset_dir in (
        ("/Scene/Things/Box_A", a), ("/Scene/Things/Box_B", b),
    ):
        scene.DefinePrim(placement, "Xform")
        child = scene.DefinePrim(f"{placement}/asset", "Xform")
        child.GetReferences().AddReference(
            f"./{asset_dir.name}/{asset_dir.name}.usda",
        )
    scene.Save()
    del scene
    state = SceneState(scene_defaults=SceneDefaults())
    state.stage_path = scene_path
    state.stage = stage_utils.open_stage(scene_path)
    state.object_count = 2
    return state


def _apply_rigid_body(state: SceneState, prim_path: str) -> None:
    physics_service.apply_physics_api(state, {
        "api_name": PhysicsApiName.RIGID_BODY.value,
        "prim_path": prim_path,
        "scope": "scene",
    })


@pytest.mark.parametrize("joint_type", _JOINT_TYPES, ids=lambda j: j.name)
def test_remove_prim_scrubs_body_rels_for_every_joint_type(
    joint_type: PhysicsJointType, tmp_path: Path,
) -> None:
    state = _scene_with_two_assets(tmp_path)
    _apply_rigid_body(state, "/Scene/Things/Box_A")
    _apply_rigid_body(state, "/Scene/Things/Box_B")
    physics_service.create_joint(state, {
        "joint_type": joint_type.value,
        "name": f"link_{joint_type.name.lower()}",
        "body0": "/Scene/Things/Box_A",
        "body1": "/Scene/Things/Box_B",
        "scope": "scene",
    })

    stage_service.remove_prim(state, {
        "prim_path": "/Scene/Things/Box_A",
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    joint = state.stage.GetPrimAtPath(
        f"/Scene/Physics/link_{joint_type.name.lower()}",
    )
    body0 = [str(t) for t in joint.GetRelationship("physics:body0").GetTargets()]
    body1 = [str(t) for t in joint.GetRelationship("physics:body1").GetTargets()]
    assert "/Scene/Things/Box_A" not in body0
    assert "/Scene/Things/Box_A" not in body1


@pytest.mark.parametrize("joint_type", _JOINT_TYPES, ids=lambda j: j.name)
def test_rename_prim_rewrites_body_rels_for_every_joint_type(
    joint_type: PhysicsJointType, tmp_path: Path,
) -> None:
    state = _scene_with_two_assets(tmp_path)
    _apply_rigid_body(state, "/Scene/Things/Box_A")
    _apply_rigid_body(state, "/Scene/Things/Box_B")
    physics_service.create_joint(state, {
        "joint_type": joint_type.value,
        "name": f"link_{joint_type.name.lower()}",
        "body0": "/Scene/Things/Box_A",
        "body1": "/Scene/Things/Box_B",
        "scope": "scene",
    })

    stage_service.rename_prim(state, {
        "old_path": "/Scene/Things/Box_A",
        "new_path": "/Scene/Things/Renamed_A",
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    joint = state.stage.GetPrimAtPath(
        f"/Scene/Physics/link_{joint_type.name.lower()}",
    )
    body0 = [str(t) for t in joint.GetRelationship("physics:body0").GetTargets()]
    assert body0 == ["/Scene/Things/Renamed_A"]


@pytest.mark.parametrize("op", ["includes", "excludes"], ids=lambda o: o)
def test_remove_prim_scrubs_collision_group_each_slot(
    op: str, tmp_path: Path,
) -> None:
    state = _scene_with_two_assets(tmp_path)
    physics_service.setup_physics_scene(state, {})
    physics_service.create_or_update_collision_group(state, {
        "name": "Movables",
        op: ["/Scene/Things/Box_A", "/Scene/Things/Box_B"],
    })

    stage_service.remove_prim(state, {
        "prim_path": "/Scene/Things/Box_A",
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    group = UsdPhysics.CollisionGroup(
        state.stage.GetPrimAtPath("/Scene/Physics/Movables"),
    )
    collection = group.GetCollidersCollectionAPI()
    rel = (
        collection.GetIncludesRel() if op == "includes"
        else collection.GetExcludesRel()
    )
    targets = [str(t) for t in rel.GetTargets()]
    assert targets == ["/Scene/Things/Box_B"]


@pytest.mark.parametrize("op", ["includes", "excludes"], ids=lambda o: o)
def test_rename_prim_rewrites_collision_group_each_slot(
    op: str, tmp_path: Path,
) -> None:
    state = _scene_with_two_assets(tmp_path)
    physics_service.setup_physics_scene(state, {})
    physics_service.create_or_update_collision_group(state, {
        "name": "Movables",
        op: ["/Scene/Things/Box_A"],
    })

    stage_service.rename_prim(state, {
        "old_path": "/Scene/Things/Box_A",
        "new_path": "/Scene/Things/Renamed_A",
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    group = UsdPhysics.CollisionGroup(
        state.stage.GetPrimAtPath("/Scene/Physics/Movables"),
    )
    collection = group.GetCollidersCollectionAPI()
    rel = (
        collection.GetIncludesRel() if op == "includes"
        else collection.GetExcludesRel()
    )
    targets = [str(t) for t in rel.GetTargets()]
    assert targets == ["/Scene/Things/Renamed_A"]


def test_remove_prim_scrubs_descendant_paths_too(tmp_path: Path) -> None:
    state = _scene_with_two_assets(tmp_path)
    physics_service.setup_physics_scene(state, {})
    physics_service.create_or_update_collision_group(state, {
        "name": "Movables",
        "includes": [
            "/Scene/Things/Box_A",
            "/Scene/Things/Box_A/asset",
            "/Scene/Things/Box_B",
        ],
    })

    stage_service.remove_prim(state, {
        "prim_path": "/Scene/Things/Box_A",
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    group = UsdPhysics.CollisionGroup(
        state.stage.GetPrimAtPath("/Scene/Physics/Movables"),
    )
    targets = [str(t) for t in group.GetCollidersCollectionAPI()
               .GetIncludesRel().GetTargets()]
    assert targets == ["/Scene/Things/Box_B"]


def test_rename_prim_rewrites_descendant_paths_too(tmp_path: Path) -> None:
    state = _scene_with_two_assets(tmp_path)
    physics_service.setup_physics_scene(state, {})
    physics_service.create_or_update_collision_group(state, {
        "name": "Movables",
        "includes": [
            "/Scene/Things/Box_A/asset",
            "/Scene/Things/Box_B",
        ],
    })

    stage_service.rename_prim(state, {
        "old_path": "/Scene/Things/Box_A",
        "new_path": "/Scene/Things/Renamed_A",
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    group = UsdPhysics.CollisionGroup(
        state.stage.GetPrimAtPath("/Scene/Physics/Movables"),
    )
    targets = sorted(
        str(t) for t in group.GetCollidersCollectionAPI()
        .GetIncludesRel().GetTargets()
    )
    assert targets == [
        "/Scene/Things/Box_B",
        "/Scene/Things/Renamed_A/asset",
    ]


@pytest.mark.parametrize("dependent_count", [1, 3], ids=["one_dep", "many_deps"])
def test_remove_collision_group_force_scrubs_every_dependent(
    dependent_count: int, tmp_path: Path,
) -> None:
    state = _scene_with_two_assets(tmp_path)
    physics_service.setup_physics_scene(state, {})
    physics_service.create_or_update_collision_group(state, {
        "name": "Statics",
        "includes": ["/Scene/Things/Box_A"],
    })
    for i in range(dependent_count):
        physics_service.create_or_update_collision_group(state, {
            "name": f"Dep_{i:02d}",
            "includes": ["/Scene/Things/Box_B"],
            "filtered_groups": ["Statics"],
        })

    physics_service.remove_collision_group(state, {
        "name": "Statics", "force": True,
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    for i in range(dependent_count):
        dep = UsdPhysics.CollisionGroup(
            state.stage.GetPrimAtPath(f"/Scene/Physics/Dep_{i:02d}"),
        )
        filtered = [str(t) for t in dep.GetFilteredGroupsRel().GetTargets()]
        assert filtered == []
