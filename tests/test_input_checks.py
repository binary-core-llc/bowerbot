# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""What the input checks still let through: numbered names, self-filtering groups, user data."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Gf, UsdGeom, UsdPhysics

from tests._helpers import exec_tool, library_state
from tests._usd_audit import audit_project, problems


def _run(state, tool, **params):
    return asyncio.run(exec_tool(state, tool, params))


def _ok(state, tool, **params):
    result = _run(state, tool, **params)
    assert result.success, f"{tool}: {result.error}"
    return result.data


def _two_bodies(state) -> tuple[str, str]:
    chair = _ok(state, "place_asset", asset="chair", asset_name="Chair", group="Furniture",
                translate_x=0.0, translate_y=0.0, translate_z=0.0)["prim_path"]
    table = _ok(state, "place_asset", asset="table", asset_name="Table", group="Furniture",
                translate_x=2.0, translate_y=0.0, translate_z=0.0)["prim_path"]
    _ok(state, "apply_physics_api", prim_path=chair, api_name="PhysicsRigidBodyAPI", scope="scene")
    return chair, table


def test_a_taken_joint_or_asset_light_name_gets_the_next_number():
    """A second 'bolt' is bolt_02 and leaves the first joint as it was; the same for an asset
    light (which used to crash) and an asset joint."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        chair, table = _two_bodies(state)
        first = _ok(state, "create_joint", joint_type="PhysicsFixedJoint", name="bolt",
                    body0=chair, body1=table, scope="scene")["prim_path"]
        second = _ok(state, "create_joint", joint_type="PhysicsRevoluteJoint", name="bolt",
                     body0=chair, scope="scene")["prim_path"]
        assert (first, second) == ("/Scene/Physics/bolt", "/Scene/Physics/bolt_02")
        stage = state.require_stage()
        assert stage.GetPrimAtPath(first).GetTypeName() == "PhysicsFixedJoint"
        assert UsdPhysics.Joint(stage.GetPrimAtPath(first)).GetBody1Rel().GetTargets() == [table]

        top, leg = f"{table}/asset/Top", f"{table}/asset/Leg"
        for part in (top, leg):
            _ok(state, "apply_physics_api", prim_path=part, api_name="PhysicsRigidBodyAPI")
        hinges = [_ok(state, "create_joint", joint_type="PhysicsRevoluteJoint", name="hinge",
                      body0=top, body1=leg, scope="asset")["prim_path"] for _ in range(2)]
        assert [h.rsplit("/", 1)[-1] for h in hinges] == ["hinge", "hinge_02"]
        _ok(state, "remove_joint", scope="asset", name="hinge_02", asset_anchor_prim_path=table)

        lamp = _ok(state, "place_asset", asset="lamp", asset_name="Lamp", group="Props",
                   translate_x=4.0, translate_y=0.0, translate_z=0.0)["prim_path"]
        bulbs = [_ok(state, "create_light", light_type="SphereLight", light_name="Bulb",
                     asset_prim_path=lamp)["prim_path"] for _ in range(2)]
        assert [b.rsplit("/", 1)[-1] for b in bulbs] == ["Bulb", "Bulb_02"]
        assert problems(audit_project(state.require_project().path)) == []


def test_a_collision_group_can_filter_itself():
    """A group whose members never collide with each other is created in one call."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        chair, table = _two_bodies(state)
        path = _ok(state, "create_or_update_collision_group", name="Stack",
                   includes=[chair, table], filtered_groups=["Stack"])["prim_path"]
        group = UsdPhysics.CollisionGroup(state.require_stage().GetPrimAtPath(path))
        assert group.GetFilteredGroupsRel().GetTargets() == [path]
        assert problems(audit_project(state.require_project().path)) == []


def test_set_prim_attribute_takes_real_names_and_user_data_and_suggests_the_rest():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        table = _ok(state, "place_asset", asset="table", asset_name="Table", group="Furniture",
                    translate_x=0.0, translate_y=0.0, translate_z=0.0)["prim_path"]
        oak = _ok(state, "create_material", prim_path=f"{table}/asset/Top",
                  material_name="oak")["material"]
        shader = f"{table}/asset/mtl/{oak.rsplit('/', 1)[-1]}/preview_surface"
        light = _ok(state, "create_light", light_type="SphereLight",
                    light_name="Key")["prim_path"]

        _ok(state, "set_prim_attribute", prim_path=light, attribute_name="inputs:intensity",
            value=5.0)
        _ok(state, "set_prim_attribute", prim_path=shader, attribute_name="inputs:roughness",
            value=0.3)
        _ok(state, "set_prim_attribute", prim_path=table, attribute_name="userProperties:sku",
            value="T-100")
        _ok(state, "set_prim_attribute", prim_path=f"{table}/asset/Top",
            attribute_name="primvars:wear", value=0.2)

        typo = _run(state, "set_prim_attribute", prim_path=light,
                    attribute_name="inputs:intensty", value=5.0)
        assert not typo.success and "inputs:intensity" in typo.error
        shader_typo = _run(state, "set_prim_attribute", prim_path=shader,
                           attribute_name="inputs:roughnes", value=0.3)
        assert not shader_typo.success and "inputs:roughness" in shader_typo.error
        api = _run(state, "set_prim_attribute", prim_path=table, attribute_name="physics:mass",
                   value=3.0)
        assert not api.success and "apply_physics_api" in api.error


def test_a_geometry_variant_only_extends_a_geometry_set():
    """A new set, or a set of another kind, would load a second geometry: refused."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        lamp = _ok(state, "place_asset", asset="lamp", asset_name="Lamp", group="Props",
                   translate_x=0.0, translate_y=0.0, translate_z=0.0)["prim_path"]
        _ok(state, "setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
            variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"}, default_variant="low")
        _ok(state, "add_asset_attribute_variant", prim_path=lamp, variant_set="look",
            variant_name="big", overrides={f"{lamp}/asset/Shade": {"size": 2.0}})
        for set_name in ("alt", "look"):
            r = _run(state, "add_asset_geometry_variant", prim_path=lamp, variant_set=set_name,
                     variant_name="x", payloads={lamp: "./geo.usda"})
            assert not r.success and "['lod']" in r.error, r.error
        _ok(state, "add_asset_geometry_variant", prim_path=lamp, variant_set="lod",
            variant_name="mid", payloads={lamp: "./geo_low.usda"})


def test_one_piece_of_a_scatter_can_be_edited_in_place():
    """The scatter prompt's recipe: change one piece's entry and write the array back."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        ground = _ok(state, "place_asset", asset="ground", asset_name="Ground",
                     group="Architecture", translate_x=0.0, translate_y=0.0,
                     translate_z=0.0)["prim_path"]
        _ok(state, "scatter_on_surface", name="Stones", group="Nature",
            assets=[{"asset": "stone"}], surfaces=[ground], count=4, seed=1)
        stones = "/Scene/Nature/Stones"
        instancer = UsdGeom.PointInstancer(state.require_stage().GetPrimAtPath(stones))
        positions = [list(p) for p in instancer.GetPositionsAttr().Get()]
        positions[2] = [1.0, 0.15, 1.0]
        _ok(state, "set_prim_attribute", prim_path="/Scene/Nature/Stones",
            attribute_name="positions", value=positions)
        _ok(state, "set_prim_attribute", prim_path="/Scene/Nature/Stones",
            attribute_name="invisibleIds", value=[0])
        instancer = UsdGeom.PointInstancer(state.require_stage().GetPrimAtPath(stones))
        assert instancer.GetPositionsAttr().Get()[2] == Gf.Vec3f(1.0, 0.15, 1.0)
        assert _ok(state, "validate_scene")["error_count"] == 0


def test_no_gravity_is_a_zero_magnitude():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        r = _ok(state, "setup_physics_scene", name="Space", gravity_magnitude=0.0)
        assert r["gravity_magnitude"] == 0.0
