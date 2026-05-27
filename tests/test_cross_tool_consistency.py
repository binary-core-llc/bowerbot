# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scene-integrity invariant: destructive ops never leave dangling rels."""

from __future__ import annotations

from pathlib import Path

from pxr import Usd, UsdGeom, UsdPhysics

from bowerbot.config import SceneDefaults
from bowerbot.schemas import ASWFLayerNames, PhysicsApiName, PhysicsJointType
from bowerbot.services import physics_service, stage_service
from bowerbot.state import SceneState
from bowerbot.utils import stage_utils


def _apply_rigid_body(state: SceneState, prim_path: str) -> None:
    physics_service.apply_physics_api(state, {
        "api_name": PhysicsApiName.RIGID_BODY.value,
        "prim_path": prim_path,
        "scope": "scene",
    })


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
    asset_a = _make_asset(tmp_path, "BoxA")
    asset_b = _make_asset(tmp_path, "BoxB")
    scene_path = tmp_path / "scene.usda"
    scene = Usd.Stage.CreateNew(str(scene_path))
    UsdGeom.SetStageMetersPerUnit(scene, 1.0)
    UsdGeom.SetStageUpAxis(scene, UsdGeom.Tokens.y)
    scene_root = scene.DefinePrim("/Scene", "Xform")
    scene.SetDefaultPrim(scene_root)
    for placement, asset_dir in (
        ("/Scene/Things/Box_A", asset_a),
        ("/Scene/Things/Box_B", asset_b),
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


def test_remove_prim_scrubs_collision_group_includes(tmp_path: Path) -> None:
    state = _scene_with_two_assets(tmp_path)
    physics_service.setup_physics_scene(state, {})
    physics_service.create_or_update_collision_group(state, {
        "name": "Movable",
        "includes": ["/Scene/Things/Box_A", "/Scene/Things/Box_B"],
    })

    result = stage_service.remove_prim(state, {
        "prim_path": "/Scene/Things/Box_A",
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    group = UsdPhysics.CollisionGroup(
        state.stage.GetPrimAtPath("/Scene/Physics/Movable"),
    )
    targets = [str(t) for t in group.GetCollidersCollectionAPI()
               .GetIncludesRel().GetTargets()]
    assert "/Scene/Things/Box_A" not in targets
    assert "/Scene/Things/Box_B" in targets
    touched = result["scrubbed_dangling_refs"]["rels_touched"]
    assert any(
        t["relationship"] == "collection:colliders:includes"
        for t in touched
    )


def test_remove_prim_scrubs_joint_body_rels(tmp_path: Path) -> None:
    state = _scene_with_two_assets(tmp_path)
    physics_service.setup_physics_scene(state, {})
    _apply_rigid_body(state, "/Scene/Things/Box_A")
    _apply_rigid_body(state, "/Scene/Things/Box_B")
    physics_service.create_joint(state, {
        "joint_type": PhysicsJointType.FIXED.value,
        "name": "AB_link",
        "body0": "/Scene/Things/Box_A",
        "body1": "/Scene/Things/Box_B",
        "scope": "scene",
    })

    result = stage_service.remove_prim(state, {
        "prim_path": "/Scene/Things/Box_A",
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    joint = state.stage.GetPrimAtPath("/Scene/Physics/AB_link")
    body0 = [str(t) for t in joint.GetRelationship("physics:body0").GetTargets()]
    body1 = [str(t) for t in joint.GetRelationship("physics:body1").GetTargets()]
    assert body0 == []
    assert body1 == ["/Scene/Things/Box_B"]
    rel_names = {t["relationship"]
                 for t in result["scrubbed_dangling_refs"]["rels_touched"]}
    assert "physics:body0" in rel_names


def test_rename_prim_rewrites_collision_group_and_joint(tmp_path: Path) -> None:
    state = _scene_with_two_assets(tmp_path)
    physics_service.setup_physics_scene(state, {})
    _apply_rigid_body(state, "/Scene/Things/Box_A")
    _apply_rigid_body(state, "/Scene/Things/Box_B")
    physics_service.create_or_update_collision_group(state, {
        "name": "Movable",
        "includes": ["/Scene/Things/Box_A"],
    })
    physics_service.create_joint(state, {
        "joint_type": PhysicsJointType.FIXED.value,
        "name": "AB_link",
        "body0": "/Scene/Things/Box_A",
        "body1": "/Scene/Things/Box_B",
        "scope": "scene",
    })

    result = stage_service.rename_prim(state, {
        "old_path": "/Scene/Things/Box_A",
        "new_path": "/Scene/Things/Renamed_A",
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    group = UsdPhysics.CollisionGroup(
        state.stage.GetPrimAtPath("/Scene/Physics/Movable"),
    )
    targets = [str(t) for t in group.GetCollidersCollectionAPI()
               .GetIncludesRel().GetTargets()]
    assert targets == ["/Scene/Things/Renamed_A"]
    joint = state.stage.GetPrimAtPath("/Scene/Physics/AB_link")
    body0 = [str(t) for t in joint.GetRelationship("physics:body0").GetTargets()]
    assert body0 == ["/Scene/Things/Renamed_A"]
    assert result["rewritten_refs"]["rels_touched"]


def test_remove_collision_group_force_scrubs_filtered_groups(tmp_path: Path) -> None:
    state = _scene_with_two_assets(tmp_path)
    physics_service.setup_physics_scene(state, {})
    physics_service.create_or_update_collision_group(state, {
        "name": "Statics",
        "includes": ["/Scene/Things/Box_A"],
    })
    physics_service.create_or_update_collision_group(state, {
        "name": "Movables",
        "includes": ["/Scene/Things/Box_B"],
        "filtered_groups": ["Statics"],
    })

    result = physics_service.remove_collision_group(state, {
        "name": "Statics", "force": True,
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    movables = UsdPhysics.CollisionGroup(
        state.stage.GetPrimAtPath("/Scene/Physics/Movables"),
    )
    filtered = [str(t) for t in movables.GetFilteredGroupsRel().GetTargets()]
    assert filtered == []
    assert result["removed"] is True
    rels = {t["relationship"]
            for t in result["scrubbed_dangling_refs"]["rels_touched"]}
    assert "physics:filteredGroups" in rels


def test_remove_prim_with_no_physics_refs_is_a_noop_for_integrity(
    tmp_path: Path,
) -> None:
    state = _scene_with_two_assets(tmp_path)

    result = stage_service.remove_prim(state, {
        "prim_path": "/Scene/Things/Box_A",
    })

    assert result["scrubbed_dangling_refs"]["rels_touched"] == []


def test_set_prim_attribute_authors_missing_rotate_z(tmp_path: Path) -> None:
    state = _scene_with_two_assets(tmp_path)

    stage_service.set_prim_attribute(state, {
        "prim_path": "/Scene/Things/Box_A",
        "attribute_name": "xformOp:rotateZ",
        "value": 47.5,
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    prim = state.stage.GetPrimAtPath("/Scene/Things/Box_A")
    xformable = UsdGeom.Xformable(prim)
    op_names = [op.GetOpName() for op in xformable.GetOrderedXformOps()]
    assert "xformOp:rotateZ" in op_names
    rotate_z = prim.GetAttribute("xformOp:rotateZ").Get()
    assert float(rotate_z) == 47.5


async def test_dispatcher_rejects_unknown_params(tmp_path: Path) -> None:
    from bowerbot import dispatcher
    state = _scene_with_two_assets(tmp_path)

    result = await dispatcher.execute(state, "move_asset", {
        "prim_path": "/Scene/Things/Box_A",
        "rotate_x": -23.7,
        "rotate_z": 12.5,
    })

    assert result.success is False
    assert "rotate_x" in (result.error or "")
    assert "rotate_z" in (result.error or "")
    assert "set_prim_attribute" in (result.error or "")


def test_set_prim_attribute_authors_missing_scale(tmp_path: Path) -> None:
    state = _scene_with_two_assets(tmp_path)

    stage_service.set_prim_attribute(state, {
        "prim_path": "/Scene/Things/Box_A",
        "attribute_name": "xformOp:scale",
        "value": [2.0, 2.0, 2.0],
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    prim = state.stage.GetPrimAtPath("/Scene/Things/Box_A")
    xformable = UsdGeom.Xformable(prim)
    op_names = [op.GetOpName() for op in xformable.GetOrderedXformOps()]
    assert "xformOp:scale" in op_names
    scale = prim.GetAttribute("xformOp:scale").Get()
    assert [float(v) for v in scale] == [2.0, 2.0, 2.0]


def test_set_prim_attribute_xform_op_when_order_already_present(
    tmp_path: Path,
) -> None:
    state = _scene_with_two_assets(tmp_path)

    stage_service.set_prim_attribute(state, {
        "prim_path": "/Scene/Things/Box_A",
        "attribute_name": "xformOpOrder",
        "value": ["xformOp:rotateX", "xformOp:rotateY", "xformOp:rotateZ"],
    })
    stage_service.set_prim_attribute(state, {
        "prim_path": "/Scene/Things/Box_A",
        "attribute_name": "xformOp:rotateX",
        "value": -17.3,
    })

    import pytest
    state.stage = stage_utils.open_stage(state.stage_path)
    prim = state.stage.GetPrimAtPath("/Scene/Things/Box_A")
    assert float(prim.GetAttribute("xformOp:rotateX").Get()) == pytest.approx(
        -17.3, abs=1e-4,
    )
    order = list(UsdGeom.Xformable(prim).GetXformOpOrderAttr().Get() or ())
    assert order.count("xformOp:rotateX") == 1


def test_create_light_uses_requested_name_when_free(tmp_path: Path) -> None:
    from bowerbot.services import light_service
    state = _scene_with_two_assets(tmp_path)
    state.stage.DefinePrim("/Scene/Lighting", "Xform")

    result = light_service.create_light(state, {
        "light_type": "DistantLight",
        "light_name": "Sun",
        "translate_x": 0.0, "translate_y": 5.0, "translate_z": 0.0,
        "intensity": 500.0,
    })

    assert result["prim_path"] == "/Scene/Lighting/Sun"


def test_create_light_suffixes_on_collision(tmp_path: Path) -> None:
    from bowerbot.services import light_service
    state = _scene_with_two_assets(tmp_path)
    state.stage.DefinePrim("/Scene/Lighting", "Xform")
    state.stage.DefinePrim("/Scene/Lighting/Sun", "DistantLight")

    result = light_service.create_light(state, {
        "light_type": "DistantLight",
        "light_name": "Sun",
        "translate_x": 0.0, "translate_y": 5.0, "translate_z": 0.0,
        "intensity": 500.0,
    })

    assert result["prim_path"] == "/Scene/Lighting/Sun_02"


def test_create_light_does_not_author_empty_light_link(tmp_path: Path) -> None:
    from bowerbot.services import light_service
    state = _scene_with_two_assets(tmp_path)
    state.stage.DefinePrim("/Scene/Lighting", "Xform")

    light_service.create_light(state, {
        "light_type": "DistantLight",
        "light_name": "Sun",
        "translate_x": 0.0, "translate_y": 5.0, "translate_z": 0.0,
        "intensity": 500.0,
    })

    state.stage = stage_utils.open_stage(state.stage_path)
    sun = state.stage.GetPrimAtPath("/Scene/Lighting/Sun")
    rel = sun.GetRelationship("collection:lightLink:includes")
    assert not (rel and rel.IsAuthored()), (
        "create_light authored a lightLink:includes rel with no targets; "
        "should leave the rel un-authored when no link list is provided."
    )
