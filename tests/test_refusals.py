# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Refusals: a call a tool refuses changes nothing, on disk or in the open stage.

Every tool that changes the project is called with inputs it must refuse,
in a scene holding one of everything. Each refusal must fail, leave every
project and library file byte-identical, and leave the open stage as it was
(a refused call that edits the in-memory stage is written by the next save).
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from pxr import Usd, UsdGeom, UsdUtils

from bowerbot import dispatcher
from bowerbot.state import SceneState
from tests._helpers import exec_tool, library_state

T = "/Scene/Furniture/Table_01"
C = "/Scene/Furniture/Chair_02"
L = "/Scene/Props/Lamp_03"
G = "/Scene/Architecture/Ground_04"

# Tools with no input they refuse: they only read, reopen or report.
NO_REFUSAL = {
    "create_stage": "reopens the project's scene.usda; the filename is informational",
    "remove_scene_variant": "idempotent: an absent variant is reported not found (removed false)",
    "remove_scene_variant_set": "idempotent: an absent set is reported not found (removed false)",
}

AT = {"translate_x": 0, "translate_y": 0, "translate_z": 0}
NEST = {"asset": "crate", "asset_name": "X", "group": "Props", **AT}

REFUSALS: list[tuple[str, dict[str, Any]]] = [
    # ── projects, stage, snapshots ──
    ("create_project", {"name": "test", "up_axis": "Y", "meters_per_unit": 1.0}),
    ("create_project", {"name": "other", "up_axis": "X", "meters_per_unit": 1.0}),
    ("open_project", {"name": "no_such_project"}),
    ("save_scene_snapshot", {"name": "v1"}),
    ("save_scene_snapshot", {"name": "scene"}),
    ("delete_scene_snapshot", {"name": "no_such_snapshot"}),
    ("delete_scene_snapshot", {"name": "scene"}),
    ("package_scene", {"for_apple_ar_quick_look": "yes"}),
    # ── placing and editing the scene ──
    ("place_asset", {"asset": "no_such_asset", "asset_name": "X", "group": "Props",
                     "translate_x": 0, "translate_y": 0, "translate_z": 0}),
    ("place_asset", {"asset": "/abs/path/chair.usda", "asset_name": "X", "group": "Props",
                     "translate_x": 0, "translate_y": 0, "translate_z": 0}),
    ("place_asset_inside", {**NEST, "container_prim_path": "/Scene/Nope"}),
    ("place_asset_inside", {**NEST, "container_prim_path": f"{T}/asset/contents/Props/Box_05"}),
    ("place_asset_inside", {**NEST, "container_prim_path": f"{T}/asset/Top"}),
    ("place_layout", {"placements": [
        {"asset": "crate", "group": "Good", "transforms": [{"translate": [0, 0, 0]}]},
        {"asset": "no_such_asset", "group": "Bad", "transforms": [{"translate": [1, 0, 0]}]},
    ]}),
    ("place_layout", {"layout_file": "/abs/layout.json"}),
    ("move_asset", {"prim_path": "/Scene/Nope", "translate_x": 1}),
    ("move_asset", {"prim_path": f"{T}/asset/Top", "translate_x": 1}),
    ("rename_prim", {"old_path": C, "new_path": T}),
    ("rename_prim", {"old_path": "/Scene", "new_path": "/Scene2"}),
    ("rename_prim", {"old_path": "/Scene/Furniture", "new_path": "/Scene/Furniture/Inner"}),
    ("rename_prim", {"old_path": C, "new_path": "/Elsewhere/Chair"}),
    ("remove_prim", {"prim_path": "/Scene/Nope"}),
    ("remove_prim", {"prim_path": f"{T}/asset/Top"}),
    ("drop_to_surface", {"prim_paths": ["/Scene/Nope"]}),
    ("drop_to_surface", {"prim_paths": [C], "surfaces": ["/Scene/Nope"]}),
    ("drop_to_surface", {"prim_paths": [C], "align": "sideways"}),
    ("set_prim_attribute", {"prim_path": f"{T}/asset/Top", "attribute_name": "no:such:attr",
                            "value": 1.0}),
    ("set_prim_attribute", {"prim_path": "/Scene/Lighting/Key",
                            "attribute_name": "inputs:intensity", "value": "bright"}),
    ("set_prim_attribute", {"prim_path": "/Scene/Nope", "attribute_name": "visibility",
                            "value": "invisible"}),
    ("set_prim_attribute", {"prim_path": "/Scene/Lighting/Key", "attribute_name": "inputs:intensty",
                            "value": 5.0}),
    ("set_prim_attribute", {"prim_path": "/Scene/Nature/Stones", "attribute_name": "positions",
                            "value": [[0, 0, 0]]}),
    ("set_prim_attribute", {"prim_path": "/Scene/Nature/Stones", "attribute_name": "protoIndices",
                            "value": [3, 0, 0, 0]}),
    ("set_prim_attribute", {"prim_path": "/Scene/Nature/Stones", "attribute_name": "invisibleIds",
                            "value": [99]}),
    # ── assets on disk ──
    ("delete_project_asset", {"name": "table"}),
    ("delete_project_asset", {"name": "no_such_asset"}),
    ("delete_project_asset", {"name": "../library"}),
    ("delete_project_file", {"file_name": "assets/lamp/lamp.usda"}),
    ("delete_project_file", {"file_name": "assets/lamp/maps/shade.png"}),
    ("delete_project_file", {"file_name": "../library/chair.usda"}),
    ("delete_project_file", {"file_name": "textures/nope.png"}),
    ("freeze_asset", {"name": "no_such_asset"}),
    ("freeze_asset", {"name": "../library"}),
    ("cleanup_unused_materials", {"asset_prim_path": "/Scene/Nope"}),
    ("cleanup_unused_contents", {"asset_prim_path": "/Scene/Nope"}),
    # ── lights and cameras ──
    ("create_light", {"light_type": "DomeLight", "light_name": "Sky2", "asset_prim_path": L}),
    ("create_light", {"light_type": "SphereLight", "light_name": "Bad",
                      "attributes": {"inputs:no_such_input": 1.0}}),
    ("create_light", {"light_type": "SphereLight", "light_name": "Bad",
                      "asset_prim_path": "/Scene/Nope"}),
    ("create_light", {"light_type": "DomeLight", "light_name": "Bad", "texture": "hdri/nope.exr"}),
    ("create_light", {"light_type": "Torch", "light_name": "Bad"}),
    ("update_light", {"prim_path": "/Scene/Lighting/Nope", "translate_x": 1}),
    ("update_light", {"prim_path": "/Scene/Cameras/Hero", "translate_x": 1}),
    ("update_light", {"prim_path": f"{L}/asset/lgt/Bulb", "translate_x": 1}),
    ("remove_light", {"prim_path": "/Scene/Cameras/Hero"}),
    ("remove_light", {"prim_path": "/Scene/Lighting/Nope"}),
    ("create_camera", {"camera_name": "Bad", "look_at": [0, 0, 0], "rotate_x": 10}),
    ("create_camera", {"camera_name": "Bad", "attributes": {"no:such": 1}}),
    ("update_camera", {"prim_path": "/Scene/Cameras/Nope", "translate_x": 1}),
    ("update_camera", {"prim_path": "/Scene/Cameras/Hero", "look_at": [0, 0, 0], "rotate_y": 5}),
    ("update_camera", {"prim_path": "/Scene/Lighting/Key", "translate_x": 1}),
    ("remove_camera", {"prim_path": "/Scene/Lighting/Key"}),
    ("remove_camera", {"prim_path": "/Scene/Cameras/Nope"}),
    # ── materials ──
    ("create_material", {"prim_path": "/Scene/Nope", "material_name": "oak"}),
    ("create_material", {"prim_path": f"{T}/asset/Top", "material_name": "oak", "roughness": 7}),
    ("create_material", {"prim_path": f"{T}/asset/Top", "material_name": "glass",
                         "metalness": -1.0, "opacity": 3.0, "base_color_r": 2.0}),
    ("bind_material", {"prim_path": f"{T}/asset/Top", "material_asset": "no_such_material"}),
    ("bind_material", {"prim_path": "/Scene/Nope", "material_asset": "woodmat"}),
    ("remove_material", {"prim_path": f"{C}/asset/Mesh"}),
    ("remove_material", {"prim_path": "/Scene/Nope"}),
    # ── asset variants ──
    ("add_asset_material_variant", {"prim_path": T, "variant_set": "look", "variant_name": "x",
                                    "bindings": {"/Top": "/table/mtl/nope"}}),
    ("add_asset_material_variant", {"prim_path": f"{T}/asset/Top", "variant_set": "look",
                                    "variant_name": "x", "bindings": {}}),
    ("add_asset_attribute_variant", {"prim_path": T, "variant_set": "size", "variant_name": "x",
                                     "overrides": {"/Top": {"no:such": 1}}}),
    ("add_asset_configuration_variant", {"prim_path": T, "variant_set": "config",
                                         "variant_name": "x", "activations": {"/Nope": False}}),
    ("add_asset_configuration_variant", {"prim_path": T, "variant_set": "config",
                                         "variant_name": "x", "activations": {T: False}}),
    ("add_asset_geometry_variant", {"prim_path": L, "variant_set": "lod", "variant_name": "x",
                                    "payloads": {L: "./nope.usda"}}),
    ("add_asset_geometry_variant", {"prim_path": L, "variant_set": "no_such_set",
                                    "variant_name": "x", "payloads": {L: "./geo.usda"}}),
    ("setup_asset_geometry_variants", {"prim_path": T, "variant_set": "lod",
                                       "variants": {"high": "./geo.usda"},
                                       "default_variant": "low"}),
    ("setup_asset_geometry_variants", {"prim_path": T, "variant_set": "lod2",
                                       "variants": {"high": "./geo.usda", "low": "chair"},
                                       "default_variant": "high"}),
    ("select_asset_variant", {"prim_path": T, "variant_set": "look", "variant_name": "nope"}),
    ("select_asset_variant", {"prim_path": T, "variant_set": "nope", "variant_name": "oak"}),
    ("select_asset_variant_for_instance", {"prim_path": T, "variant_set": "look",
                                           "variant_name": "nope"}),
    ("remove_asset_variant", {"prim_path": "/Scene/Nope", "variant_set": "look",
                              "variant_name": "oak"}),
    ("remove_asset_variant_set", {"prim_path": f"{T}/asset/Top", "variant_set": "look"}),
    # ── scene variants ──
    ("add_scene_lighting_attribute_variant", {"variant_set": "mood", "variant_name": "x",
                                              "overrides": {f"{T}/asset/Top": {"size": 2.0}}}),
    ("add_scene_lighting_attribute_variant", {
        "variant_set": "mood", "variant_name": "x",
        "overrides": {"/Scene/Lighting/Key": {"no:such": 1}}}),
    ("add_scene_lighting_selection_variant", {"variant_set": "rig", "variant_name": "x",
                                              "activations": {"/Scene/Cameras/Hero": False}}),
    ("add_scene_model_selection_variant", {"prim_path": C, "variant_set": "model",
                                           "variant_name": "x", "asset": "no_such_asset"}),
    ("add_scene_model_selection_variant", {"prim_path": f"{C}/asset/Mesh", "variant_set": "model",
                                           "variant_name": "x", "asset": "crate"}),
    ("select_scene_variant", {"prim_path": "/Scene/Lighting", "variant_set": "mood",
                              "variant_name": "nope"}),
    # ── physics ──
    ("setup_physics_scene", {"gravity_direction": [0, 0, 0]}),
    ("setup_physics_scene", {"gravity_magnitude": -3}),
    ("apply_physics_api", {"prim_path": C, "api_name": "PhysicsNoSuchAPI", "scope": "scene"}),
    ("apply_physics_api", {"prim_path": "/Scene/Nope", "api_name": "PhysicsRigidBodyAPI",
                           "scope": "scene"}),
    ("apply_physics_api", {"prim_path": f"{T}/asset/Top", "api_name": "PhysicsFilteredPairsAPI",
                           "relationships": {"physics:filteredPairs": [f"{L}/asset/Base"]}}),
    ("apply_physics_api", {"prim_path": f"{C}/asset/Mesh", "api_name": "PhysicsMeshCollisionAPI"}),
    ("create_joint", {"joint_type": "PhysicsFixedJoint", "name": "bad", "body0": "/Scene/Nope",
                      "body1": C, "scope": "scene"}),
    ("create_joint", {"joint_type": "PhysicsWeldJoint", "name": "bad", "body0": C, "body1": T,
                      "scope": "scene"}),
    ("remove_physics_api", {"prim_path": C, "api_name": "PhysicsNoSuchAPI", "scope": "scene"}),
    ("remove_physics_scene", {"name": ""}),
    ("remove_joint", {"scope": "asset", "asset_anchor_prim_path": T}),
    ("remove_joint", {"scope": "sideways", "prim_path": "/Scene/Physics/bolt"}),
    ("remove_collision_group", {"name": "Furniture"}),
    ("create_or_update_collision_group", {"name": "PhysicsScene", "includes": [C]}),
    ("setup_physics_scene", {"name": "bolt"}),
    ("remove_collision_group", {"name": "PhysicsScene"}),
    ("remove_joint", {"scope": "scene", "prim_path": "/Scene/Physics/PhysicsScene"}),
    ("remove_physics_scene", {"name": "Furniture"}),
    ("create_or_update_collision_group", {"name": "Bad", "includes": ["/Scene/Nope"]}),
    ("create_or_update_collision_group", {"name": "Bad", "includes": [C],
                                          "filtered_groups": ["NoSuchGroup"]}),
    # ── scatters ──
    ("scatter_on_surface", {"name": "Bad", "assets": [{"asset": "stone"}],
                            "surfaces": ["/Scene/Nope"], "count": 3}),
    ("scatter_on_surface", {"name": "Bad", "assets": [{"asset": "stone"},
                                                      {"asset": "no_such_asset"}],
                            "surfaces": [G], "count": 3}),
    ("scatter_on_surface", {"name": "Stones", "assets": [{"asset": "stone"}], "group": "Nature",
                            "surfaces": [G], "count": 3}),
    ("scatter_on_surface", {"name": "Bad", "assets": [{"asset": "stone"}], "surfaces": [G],
                            "arrangement": "pile", "count": 3}),
    ("scatter_along_path", {"name": "Bad", "assets": [{"asset": "crate"}], "points": [[0, 0, 0]],
                            "count": 3}),
    ("scatter_along_path", {"name": "Bad", "assets": [{"asset": "no_such_asset"}],
                            "points": [[0, 0, 0], [1, 0, 0]], "count": 3}),
    ("scatter_along_path", {"name": "Bad", "assets": [{"asset": "crate"}],
                            "curve_prim": "/Scene/Nope", "count": 3}),
]

# Idempotent removals of something absent: they succeed and change nothing.
NO_OPS: list[tuple[str, dict[str, Any]]] = [
    ("remove_scene_variant", {"prim_path": "/Scene/Nope", "variant_set": "mood",
                              "variant_name": "dim"}),
    ("remove_scene_variant_set", {"prim_path": "/Scene/Nope", "variant_set": "mood"}),
    ("remove_physics_api", {"prim_path": C, "api_name": "PhysicsMassAPI", "scope": "scene"}),
    ("remove_physics_api", {"prim_path": "/Scene/Nope", "api_name": "PhysicsRigidBodyAPI",
                            "scope": "scene"}),
    ("remove_physics_scene", {"name": "NoSuchScene"}),
    ("remove_joint", {"scope": "scene", "prim_path": "/Scene/Physics/no_such_joint"}),
    ("remove_joint", {"scope": "asset", "name": "nope", "asset_anchor_prim_path": T}),
    ("remove_collision_group", {"name": "NoSuchGroup"}),
]

# A USDZ placement can't be edited as an asset folder, and a scatter's prototype is part of
# the scatter, not a placement: these are refused too.
P = "/Scene/Props/Pkg_07"
PROTO = "/Scene/Nature/Stones/Prototypes/stone"
REFUSALS += [
    ("bind_material", {"prim_path": f"{P}/asset/Mesh", "material_asset": "woodmat"}),
    ("create_material", {"prim_path": f"{P}/asset/Mesh", "material_name": "oak"}),
    ("create_light", {"light_type": "SphereLight", "light_name": "Bad", "asset_prim_path": P}),
    ("apply_physics_api", {"prim_path": f"{P}/asset/Mesh", "api_name": "PhysicsCollisionAPI",
                           "scope": "asset"}),
    ("add_asset_attribute_variant", {"prim_path": P, "variant_set": "size", "variant_name": "x",
                                     "overrides": {f"{P}/asset/Mesh": {"size": 2.0}}}),
    ("setup_asset_geometry_variants", {"prim_path": P, "variant_set": "lod",
                                       "variants": {"a": "./geo.usda"}, "default_variant": "a"}),
    ("select_asset_variant", {"prim_path": P, "variant_set": "size", "variant_name": "x"}),
    ("move_asset", {"prim_path": PROTO, "translate_x": 1}),
    ("remove_prim", {"prim_path": "/Scene/Nature/Stones/Prototypes"}),
]


def _scene_with_one_of_everything(state: SceneState) -> None:
    def call(tool: str, **params: Any) -> dict[str, Any]:
        result = asyncio.run(exec_tool(state, tool, params))
        assert result.success, f"{tool}: {result.error}"
        return result.data or {}

    assert call("place_asset", asset="table", asset_name="Table", group="Furniture",
                translate_x=0, translate_y=0, translate_z=0)["prim_path"] == T
    assert call("place_asset", asset="chair", asset_name="Chair", group="Furniture",
                translate_x=2, translate_y=0, translate_z=0)["prim_path"] == C
    assert call("place_asset", asset="lamp", asset_name="Lamp", group="Props",
                translate_x=4, translate_y=0, translate_z=0)["prim_path"] == L
    assert call("place_asset", asset="ground", asset_name="Ground", group="Architecture",
                translate_x=0, translate_y=-0.1, translate_z=6)["prim_path"] == G
    call("place_asset_inside", asset="crate", asset_name="Box", container_prim_path=T,
         group="Props", translate_x=0.2, translate_y=0.1, translate_z=0)
    call("create_light", light_type="SphereLight", light_name="Key", translate_y=3)
    call("create_light", light_type="SphereLight", light_name="Bulb", asset_prim_path=L)
    call("create_camera", camera_name="Hero", translate_x=3, translate_y=2, translate_z=3,
         look_at=[0, 0, 0])
    oak = call("create_material", prim_path=f"{T}/asset/Top", material_name="oak")["material"]
    call("add_asset_material_variant", prim_path=T, variant_set="look", variant_name="oak",
         bindings={f"{T}/asset/Leg": oak})
    call("setup_asset_geometry_variants", prim_path=L, variant_set="lod",
         variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"}, default_variant="high")
    call("add_scene_lighting_attribute_variant", variant_set="mood", variant_name="dim",
         overrides={"/Scene/Lighting/Key": {"inputs:intensity": 0.3}})
    call("setup_physics_scene")
    call("apply_physics_api", prim_path=C, api_name="PhysicsRigidBodyAPI", scope="scene")
    call("apply_physics_api", prim_path=T, api_name="PhysicsRigidBodyAPI", scope="scene")
    call("apply_physics_api", prim_path=f"{T}/asset/Top", api_name="PhysicsCollisionAPI")
    call("create_joint", joint_type="PhysicsFixedJoint", name="bolt", body0=C, body1=T,
         scope="scene")
    call("create_or_update_collision_group", name="Furniture", includes=[C, T])
    call("create_or_update_collision_group", name="Walls", includes=[G],
         filtered_groups=["Furniture"])
    call("scatter_on_surface", name="Stones", group="Nature", assets=[{"asset": "stone"}],
         surfaces=[G], count=4, seed=1)
    call("save_scene_snapshot", name="v1")
    source = state.library_dir / "pkg_source.usda"
    stage = Usd.Stage.CreateNew(str(source))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, "/pkg").GetPrim())
    UsdGeom.Cube.Define(stage, "/pkg/Mesh")
    stage.Save()
    assert UsdUtils.CreateNewUsdzPackage(str(source), str(state.library_dir / "pkg.usdz"))
    source.unlink()
    assert call("place_asset", asset="pkg", asset_name="Pkg", group="Props",
                translate_x=-2, translate_y=0, translate_z=0)["prim_path"] == P


def _files(*folders: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for folder in folders for p in sorted(folder.rglob("*"))
            if p.is_file()}


def _stage_state(state: SceneState) -> tuple[str, str]:
    stage = state.require_stage()
    return stage.GetRootLayer().ExportToString(), stage.GetSessionLayer().ExportToString()


def test_every_refused_call_changes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _scene_with_one_of_everything(state)
        project, library = state.require_project().path, state.library_dir
        projects = project.parent
        problems = []
        for tool, params in REFUSALS:
            files, stage = _files(projects, library), _stage_state(state)
            result = asyncio.run(exec_tool(state, tool, params))
            if result.success:
                problems.append(f"{tool}({params}) was accepted: {str(result.data)[:200]}")
                continue
            if _files(projects, library) != files:
                changed = sorted(k for k in set(files) | set(_files(projects, library))
                                 if files.get(k) != _files(projects, library).get(k))
                problems.append(f"{tool}({params}) refused but changed files: {changed}")
            if state.stage is not None and _stage_state(state) != stage:
                problems.append(f"{tool}({params}) refused but changed the open stage")
        assert not problems, "\n".join(problems)


def test_removing_what_is_not_there_succeeds_and_changes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _scene_with_one_of_everything(state)
        projects = state.require_project().path.parent
        problems = []
        for tool, params in NO_OPS:
            files, stage = _files(projects, state.library_dir), _stage_state(state)
            result = asyncio.run(exec_tool(state, tool, params))
            if not result.success:
                problems.append(f"{tool}({params}) failed: {result.error}")
            elif result.data.get("removed") is not False:
                problems.append(f"{tool}({params}) reported a removal: {result.data}")
            if _files(projects, state.library_dir) != files or _stage_state(state) != stage:
                problems.append(f"{tool}({params}) changed the project")
        assert not problems, "\n".join(problems)


def test_every_tool_that_changes_the_project_has_a_refusal_case():
    changing = {t.name for t in dispatcher.TOOLS if str(t.effect) != "read"}
    covered = {tool for tool, _ in REFUSALS} | set(NO_REFUSAL)
    assert changing <= covered, sorted(changing - covered)
