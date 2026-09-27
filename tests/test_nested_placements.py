# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tools given a nested placement (an asset placed inside another) edit that nested asset."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Gf, Usd, UsdGeom, UsdPhysics, UsdShade

from tests._helpers import exec_tool, library_state
from tests._usd_audit import audit_project, problems


def _run(state, tool, **params):
    return asyncio.run(exec_tool(state, tool, params))


def _lamp_on_a_table(state) -> tuple[str, str]:
    """A table moved and turned in the scene, with a lamp placed inside it, on its top."""
    table = _run(state, "place_asset", asset="table", asset_name="Table", group="Furniture",
                 translate_x=2.0, translate_y=0.0, translate_z=1.0, rotate_y=90.0)
    assert table.success, table.error
    lamp = _run(state, "place_asset_inside", asset="lamp", asset_name="Lamp",
                container_prim_path=table.data["prim_path"], group="Props",
                translate_x=2.1, translate_y=0.05, translate_z=1.2)
    assert lamp.success, lamp.error
    return table.data["prim_path"], lamp.data["prim_path"]


def _files(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def test_asset_tools_on_a_nested_placement_edit_the_nested_asset():
    """Variants, materials, lights and physics on a lamp inside a table land in the lamp's folder.

    They used to resolve to the container: a light or a collider meant for the
    lamp was written into the table's lgt.usda / phy.usda.
    """
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _, lamp = _lamp_on_a_table(state)
        assets = state.require_project().assets_dir
        table_files = _files(assets / "table")
        light_at = (2.5, 1.5, 0.5)

        calls = [
            ("add_asset_material_variant", dict(
                prim_path=lamp, variant_set="finish", variant_name="cloth",
                bindings={"/Shade": "/lamp/mtl/cloth"})),
            ("setup_asset_geometry_variants", dict(
                prim_path=lamp, variant_set="lod", default_variant="high",
                variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"})),
            ("bind_material", dict(prim_path=f"{lamp}/asset/Base", material_asset="woodmat")),
            ("create_light", dict(
                light_type="SphereLight", light_name="Bulb", asset_prim_path=lamp,
                position_mode="absolute", translate_x=light_at[0], translate_y=light_at[1],
                translate_z=light_at[2])),
            ("apply_physics_api", dict(
                prim_path=f"{lamp}/asset/Base", api_name="PhysicsCollisionAPI", scope="asset")),
        ]
        for tool, params in calls:
            r = _run(state, tool, **params)
            assert r.success, f"{tool}: {r.error}"
            folder = r.data.get("asset_folder") or Path(r.data["asset_path"]).name
            assert folder == "lamp", f"{tool} edited {folder}"
        assert _files(assets / "table") == table_files

        listed = _run(state, "list_variants", prim_path=lamp)
        assert {s["name"] for c in listed.data["carriers"] for s in c["variant_sets"]} >= {
            "finish", "lod",
        }
        stage = state.require_stage()
        base = stage.GetPrimAtPath(f"{lamp}/asset/Base")
        bound = UsdShade.MaterialBindingAPI(base).ComputeBoundMaterial()[0]
        assert bound.GetPath() == f"{lamp}/asset/mtl/wood"
        assert base.HasAPI(UsdPhysics.CollisionAPI)
        bulb = UsdGeom.Xformable(stage.GetPrimAtPath(f"{lamp}/asset/lgt/Bulb"))
        world = bulb.ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
        assert Gf.IsClose(world, Gf.Vec3d(*light_at), 1e-4), world
        assert problems(audit_project(state.require_project().path)) == []


def test_moving_and_removing_a_nested_placement_edit_its_container():
    """The nested wrapper itself still lives in the container's contents.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _, lamp = _lamp_on_a_table(state)
        assets = state.require_project().assets_dir
        lamp_files = _files(assets / "lamp")

        moved = _run(state, "move_asset", prim_path=lamp,
                     translate_x=1.8, translate_y=0.2, translate_z=1.1)
        assert moved.success, moved.error
        wrapper = UsdGeom.Xformable(state.require_stage().GetPrimAtPath(lamp))
        world = wrapper.ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
        assert Gf.IsClose(world, Gf.Vec3d(1.8, 0.2, 1.1), 1e-4), world
        assert "Lamp" in (assets / "table" / "contents.usda").read_text()

        removed = _run(state, "remove_prim", prim_path=lamp)
        assert removed.success, removed.error
        assert not state.require_stage().GetPrimAtPath(lamp)
        assert _files(assets / "lamp") == lamp_files


def test_the_shared_asset_guard_counts_nested_placements():
    """A lamp placed in the scene and inside a table is shared by two placements."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _lamp_on_a_table(state)
        lamp = _run(state, "place_asset", asset="lamp", asset_name="Lamp", group="Props",
                    translate_x=-2.0, translate_y=0.0, translate_z=0.0).data["prim_path"]

        refused = _run(state, "bind_material", prim_path=f"{lamp}/asset/Base",
                       material_asset="woodmat")
        assert not refused.success
        assert "referenced by 2 scene instances" in refused.error

        r = _run(state, "bind_material", prim_path=f"{lamp}/asset/Base",
                 material_asset="woodmat", confirm_shared_modification=True)
        assert r.success, r.error


def test_validate_scene_checks_an_asset_placed_only_inside_another():
    """A nested asset's folder is validated too, not only the scene-level ones."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _lamp_on_a_table(state)
        stray = state.require_project().assets_dir / "lamp" / "variants.usda"
        stray.write_text("#usda 1.0\n")

        r = _run(state, "validate_scene")
        assert r.success, r.error
        assert any("variants.usda exists in lamp" in i["message"] for i in r.data["issues"])


def test_edits_on_a_nested_placement_undo_cleanly():
    """Add a variant, an instance selection, a material, a light and a collider; remove them all.

    The lamp's folder returns to what it was (once the texture the removal
    reports is deleted), the table's never changes, and the per-instance
    selection on the nested lamp is scrubbed with its variant set.
    """
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _, lamp = _lamp_on_a_table(state)
        project = state.require_project()
        lamp_files = _files(project.assets_dir / "lamp")
        table_files = _files(project.assets_dir / "table")
        base = f"{lamp}/asset/Base"
        steps = [
            ("add_asset_material_variant", dict(prim_path=lamp, variant_set="finish",
                                                variant_name="cloth",
                                                bindings={"/Shade": "/lamp/mtl/cloth"})),
            ("select_asset_variant_for_instance", dict(prim_path=lamp, variant_set="finish",
                                                       variant_name="cloth")),
            ("bind_material", dict(prim_path=base, material_asset="woodmat")),
            ("create_light", dict(light_type="SphereLight", light_name="Bulb",
                                  asset_prim_path=lamp, translate_x=0.0, translate_y=0.3,
                                  translate_z=0.0)),
            ("apply_physics_api", dict(prim_path=base, api_name="PhysicsCollisionAPI",
                                       scope="asset")),
            ("remove_physics_api", dict(prim_path=base, api_name="PhysicsCollisionAPI",
                                        scope="asset")),
            ("remove_light", dict(prim_path=f"{lamp}/asset/lgt/Bulb")),
            ("remove_material", dict(prim_path=base)),
            ("remove_asset_variant_set", dict(prim_path=lamp, variant_set="finish")),
        ]
        unused: list[str] = []
        for tool, params in steps:
            r = _run(state, tool, **params)
            assert r.success, f"{tool}: {r.error}"
            unused += r.data.get("unused_files", [])
        assert unused == ["assets/lamp/maps/wood.png"]
        assert _run(state, "delete_project_file", file_name=unused[0]).success

        assert _files(project.assets_dir / "lamp") == lamp_files
        assert _files(project.assets_dir / "table") == table_files
        assert "finish" not in project.scene_path.read_text()
        assert problems(audit_project(project.path)) == []
