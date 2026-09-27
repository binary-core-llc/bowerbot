# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""A change reports what it leaves behind: assets nothing uses, pair filters that stop acting."""

import asyncio
import tempfile
from pathlib import Path

from tests._helpers import exec_tool, library_state
from tests._usd_audit import audit_project, problems


def _ok(state, tool, **params):
    result = asyncio.run(exec_tool(state, tool, params))
    assert result.success, f"{tool}: {result.error}"
    return result.data


def _place(state, asset, name, group="Props", x=0.0):
    return _ok(state, "place_asset", asset=asset, asset_name=name, group=group,
               translate_x=x, translate_y=0.0, translate_z=0.0)["prim_path"]


def test_removing_the_last_placement_reports_its_asset_and_keeps_it():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        assets = state.require_project().assets_dir
        first, second = _place(state, "crate", "A"), _place(state, "crate", "B", x=1.0)
        _place(state, "table", "Table", group="Furniture", x=3.0)
        _place(state, "chair", "Chair", group="Furniture", x=5.0)

        assert _ok(state, "remove_prim", prim_path=first)["unused_assets"] == []
        removed = _ok(state, "remove_prim", prim_path=second)
        assert removed["unused_assets"] == ["crate"]
        assert "delete_project_asset" in removed["message"]
        assert (assets / "crate").is_dir()

        group = _ok(state, "remove_prim", prim_path="/Scene/Furniture")
        assert group["unused_assets"] == ["chair", "table"]
        assert problems(audit_project(state.require_project().path)) == []


def test_a_nested_asset_is_unused_only_when_its_container_goes_too():
    """Removing a nested placement reports its asset; removing the container reports the
    container, and deleting the container then reports what only it placed."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        table = _place(state, "table", "Table", group="Furniture")

        def box() -> str:
            return _ok(state, "place_asset_inside", asset="crate", asset_name="Box",
                       container_prim_path=table, group="Props",
                       translate_x=0.0, translate_y=0.1, translate_z=0.0)["prim_path"]

        assert _ok(state, "remove_prim", prim_path=box())["unused_assets"] == ["crate"]
        box()
        assert _ok(state, "remove_prim", prim_path=table)["unused_assets"] == ["table"]
        deleted = _ok(state, "delete_project_asset", name="table")
        assert deleted["unused_assets"] == ["crate"]
        assert "crate" in deleted["message"]
        assert _ok(state, "delete_project_asset", name="crate")["unused_assets"] == []
        assert not any(state.require_project().assets_dir.iterdir())


def test_an_asset_only_a_variant_or_a_snapshot_used_is_reported_when_that_goes():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        chair = _place(state, "chair", "Chair")
        for name, asset in (("cm", "chair_cm"), ("post", "post")):
            _ok(state, "add_scene_model_selection_variant", prim_path=chair,
                variant_set="model", variant_name=name, asset=asset)
        removed = _ok(state, "remove_scene_variant", prim_path=chair, variant_set="model",
                      variant_name="cm")
        assert removed["unused_assets"] == ["chair_cm"]
        whole_set = _ok(state, "remove_scene_variant_set", prim_path=chair, variant_set="model")
        assert whole_set["unused_assets"] == ["post"]

        crate = _place(state, "crate", "Crate", x=2.0)
        _ok(state, "create_light", light_type="DomeLight", light_name="Sky",
            texture="hdri/sky.png")
        _ok(state, "save_scene_snapshot", name="v1")
        assert _ok(state, "remove_prim", prim_path=crate)["unused_assets"] == []
        assert _ok(state, "remove_light", prim_path="/Scene/Lighting/Sky")["unused_files"] == []
        snapshot = _ok(state, "delete_scene_snapshot", name="v1")
        assert snapshot["unused_assets"] == ["crate"]
        assert snapshot["unused_files"] == ["textures/sky.png"]
        assert "crate" in snapshot["message"] and "sky.png" in snapshot["message"]
        assert problems(audit_project(state.require_project().path)) == []


def test_a_scatter_reports_the_assets_it_stops_using():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        ground = _place(state, "ground", "Ground", group="Architecture")
        _ok(state, "scatter_on_surface", name="Stones", group="Nature",
            assets=[{"asset": "stone"}, {"asset": "crate"}], surfaces=[ground], count=6, seed=1)
        again = _ok(state, "scatter_on_surface", name="Stones", group="Nature",
                    assets=[{"asset": "stone"}], surfaces=[ground], count=6, seed=1, replace=True)
        assert again["unused_assets"] == ["crate"]

        path = {"points": [[-3.0, 0.0, 2.0], [3.0, 0.0, 2.0]], "count": 4, "surfaces": [ground]}
        _ok(state, "scatter_along_path", name="Fence", group="Nature",
            assets=[{"asset": "post"}], **path)
        swapped = _ok(state, "scatter_along_path", name="Fence", group="Nature",
                      assets=[{"asset": "crate"}], replace=True, **path)
        assert swapped["unused_assets"] == ["post"]

        assert _ok(state, "remove_prim", prim_path="/Scene/Nature")["unused_assets"] == [
            "crate", "stone",
        ]
        assert problems(audit_project(state.require_project().path)) == []


def test_removing_what_a_pair_filter_needs_reports_the_filter():
    """A filter pairs bodies, colliders or articulation roots: taking the API off either side
    leaves it authored and doing nothing, at scene and at asset scope."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        chair, crate = _place(state, "chair", "Chair"), _place(state, "crate", "Crate", x=2.0)
        for prim, api in ((chair, "PhysicsRigidBodyAPI"), (chair, "PhysicsCollisionAPI"),
                          (crate, "PhysicsRigidBodyAPI")):
            _ok(state, "apply_physics_api", prim_path=prim, api_name=api, scope="scene")
        _ok(state, "apply_physics_api", prim_path=chair, api_name="PhysicsFilteredPairsAPI",
            scope="scene", relationships={"physics:filteredPairs": [crate]})

        still_a_body = _ok(state, "remove_physics_api", prim_path=chair,
                           api_name="PhysicsCollisionAPI", scope="scene")
        assert still_a_body["inert_pair_filters"] == []
        target_gone = _ok(state, "remove_physics_api", prim_path=crate,
                          api_name="PhysicsRigidBodyAPI", scope="scene")
        assert target_gone["inert_pair_filters"] == [{"prim_path": chair, "target": crate}]
        assert "no longer act" in target_gone["message"]
        filter_gone = _ok(state, "remove_physics_api", prim_path=chair,
                          api_name="PhysicsFilteredPairsAPI", scope="scene")
        assert filter_gone["inert_pair_filters"] == []

        table = _place(state, "table", "Table", group="Furniture", x=5.0)
        top, leg = f"{table}/asset/Top", f"{table}/asset/Leg"
        for part in (top, leg):
            _ok(state, "apply_physics_api", prim_path=part, api_name="PhysicsCollisionAPI")
        _ok(state, "apply_physics_api", prim_path=top, api_name="PhysicsFilteredPairsAPI",
            relationships={"physics:filteredPairs": [leg]})
        owner_gone = _ok(state, "remove_physics_api", prim_path=top,
                         api_name="PhysicsCollisionAPI")
        assert owner_gone["inert_pair_filters"] == [{"prim_path": top, "target": leg}]
        assert problems(audit_project(state.require_project().path)) == []
