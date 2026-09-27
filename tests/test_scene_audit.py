# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scene audit: what the tools author stays clean, and removals leave nothing behind.

Every call that changes the project is followed by a full USD audit
(``tests/_usd_audit.py``), so a stale spec, a dangling relationship, an
unresolved or absolute path, a broken model hierarchy or a malformed asset
folder fails the test at the call that introduced it.
"""

from __future__ import annotations

import asyncio
import difflib
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bowerbot import dispatcher
from bowerbot.state import SceneState
from tests._helpers import build_library as _library
from tests._helpers import exec_tool
from tests._usd_audit import audit_project, problems

READ_ONLY = re.compile(r"^(list_|search_|get_)|^(validate_scene|compute_grid_layout)$")


# ── a project that audits itself after every change ──


class _Project:
    def __init__(self, tmp: Path, *, up: str = "Y", mpu: float = 1.0) -> None:
        library = tmp / "library"
        _library(library)
        self.state = SceneState(library_dir=library, projects_dir=tmp / "projects")
        self.called: list[str] = []
        self.round_tripped: set[str] = set()
        self.call("create_project", name="audit", up_axis=up, meters_per_unit=mpu)

    @property
    def path(self) -> Path:
        return self.state.require_project().path

    def call(self, tool: str, **params: Any) -> dict[str, Any]:
        """Run *tool*; it must succeed, and a change must leave the project clean."""
        self.called.append(tool)
        result = asyncio.run(exec_tool(self.state, tool, params))
        assert result.success, f"{tool}({params}): {result.error}"
        if not READ_ONLY.search(tool):
            found = problems(audit_project(self.path, sweep_variants=False))
            assert not found, f"after {tool}({params}):\n" + "\n".join(map(str, found))
        return result.data or {}

    def remove(self, tool: str, **params: Any) -> dict[str, Any]:
        """Run a removal, delete everything it reports unused (the user's yes), then audit.

        Only what the removal reports is deleted, so a leftover it fails to
        report shows up in the round trip's byte comparison.
        """
        self.called.append(tool)
        result = asyncio.run(exec_tool(self.state, tool, params))
        assert result.success, f"{tool}({params}): {result.error}"
        self._delete_reported(result.data or {})
        found = problems(audit_project(self.path, sweep_variants=False))
        assert not found, f"after {tool}({params}):\n" + "\n".join(map(str, found))
        return result.data or {}

    def _delete_reported(self, data: dict[str, Any]) -> None:
        for rel in data.get("unused_files", []):
            self.call("delete_project_file", file_name=rel)
        for name in data.get("unused_assets", []):
            self._delete_reported(self.call("delete_project_asset", name=name))

    def audit_everything(self) -> None:
        """The full audit, with every variant of every set selected in turn."""
        found = problems(audit_project(self.path))
        assert not found, "\n".join(map(str, found))

    def files(self) -> dict[str, str]:
        """Each USD text layer's content and every other file's size (project.json aside)."""
        files: dict[str, str] = {}
        for path in sorted(self.path.rglob("*")):
            if path.is_file() and path.name != "project.json":
                rel = str(path.relative_to(self.path))
                size = f"<{path.stat().st_size} bytes>"
                files[rel] = path.read_text() if path.suffix == ".usda" else size
        return files

    def round_trip(self, create: Callable[[], dict[str, Any]],
                   remove: Callable[[dict[str, Any]], object],
                   *, keep: tuple[str, ...] = ()) -> None:
        """*create*, then *remove* (given what create returned), restore the project.

        New files matching a *keep* pattern are allowed to remain.
        """
        before = self.files()
        start = len(self.called)
        made = create()
        self.round_tripped.update(self.called[start:])
        remove(made)
        after = self.files()
        leftovers = []
        for rel in sorted(set(before) | set(after)):
            if rel not in before and any(re.search(pattern, rel) for pattern in keep):
                continue
            if before.get(rel) != after.get(rel):
                diff = difflib.unified_diff(
                    before.get(rel, "").splitlines(), after.get(rel, "").splitlines(),
                    lineterm="", n=1,
                )
                leftovers.append(f"{rel}:\n" + "\n".join(list(diff)[2:30]))
        assert not leftovers, "\n".join(leftovers)


# ── tests ──


def test_a_scene_built_with_every_tool_stays_clean():
    """Placements, layouts, nesting, lights, a camera, materials, variants, physics and a
    scatter, each audited as it lands; then every variant is audited too."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _Project(Path(tmp))
        call = project.call
        table = call("place_asset", asset="table", asset_name="Table", group="Furniture",
                     translate_x=0, translate_y=0, translate_z=0)["prim_path"]
        chair = call("place_asset", asset="chair", asset_name="Chair", group="Furniture",
                     translate_x=1.5, translate_y=0, translate_z=0, rotate_y=30)["prim_path"]
        lamp = call("place_asset", asset="lamp", asset_name="Lamp", group="Props",
                    translate_x=0, translate_y=0.1, translate_z=0)["prim_path"]
        ground = call("place_asset", asset="ground", asset_name="Ground", group="Architecture",
                      translate_x=0, translate_y=-0.05, translate_z=6)["prim_path"]
        call("place_layout", placements=[{
            "asset": "crate", "group": "Storage/Racks",
            "pattern": {"type": "grid", "origin": [4, 0, 0], "count": [3, 2],
                        "spacing": [0.5, 0.5]},
        }])
        call("place_asset_inside", asset="crate", asset_name="Box", container_prim_path=table,
             group="Props", translate_x=0.3, translate_y=0.1, translate_z=0)
        call("move_asset", prim_path=chair, translate_z=0.5, rotate_y=45)
        chair = call("rename_prim", old_path=chair, new_path="/Scene/Dining/Chair")["new_path"]

        call("create_light", light_type="DomeLight", light_name="Sky", texture="hdri/sky.png")
        call("create_light", light_type="SphereLight", light_name="Bulb", asset_prim_path=lamp,
             light_link_includes=[f"{lamp}/asset/Shade"])
        call("create_light", light_type="RectLight", light_name="Glow", asset_prim_path=table,
             texture="textures/glow.png", rotate_x=-90)
        call("create_camera", camera_name="Hero", translate_x=4, translate_y=2, translate_z=4,
             look_at=[0, 0, 0])

        oak = call("create_material", prim_path=f"{table}/asset/Top",
                   material_name="oak")["material"]
        call("bind_material", prim_path=f"{table}/asset/Leg", material_asset="woodmat")
        call("add_asset_material_variant", prim_path=table, variant_set="look", variant_name="oak",
             bindings={f"{table}/asset/Leg": oak})
        call("add_asset_attribute_variant", prim_path=lamp, variant_set="fabric",
             variant_name="wood",
             overrides={f"{lamp}/asset/mtl/cloth/tex": {"inputs:file": "textures/glow.png"}})
        call("add_scene_lighting_attribute_variant", variant_set="mood", variant_name="dim",
             overrides={"/Scene/Lighting/Sky": {"inputs:intensity": 0.3}})
        call("add_scene_model_selection_variant", prim_path=chair, variant_set="model",
             variant_name="cm", asset="chair_cm")
        call("add_scene_model_selection_variant", prim_path=chair, variant_set="model",
             variant_name="post", asset="post", set_as_default=True)

        call("setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
             variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"},
             default_variant="high")
        call("add_asset_configuration_variant", prim_path=table, variant_set="legs",
             variant_name="none", activations={f"{table}/asset/Leg": False})

        call("setup_physics_scene")
        call("apply_physics_api", prim_path=chair, api_name="PhysicsRigidBodyAPI", scope="scene")
        call("apply_physics_api", prim_path=f"{table}/asset/Top", api_name="PhysicsCollisionAPI")
        call("apply_physics_api", prim_path=f"{table}/asset/Leg", api_name="PhysicsCollisionAPI")
        call("apply_physics_api", prim_path=f"{table}/asset/Top",
             api_name="PhysicsFilteredPairsAPI",
             relationships={"physics:filteredPairs": [f"{table}/asset/Leg"]})
        call("create_joint", joint_type="PhysicsFixedJoint", name="bolt", body0=chair, body1=table,
             scope="scene")
        call("create_or_update_collision_group", name="Furniture", includes=[chair, table])

        call("scatter_on_surface", name="Stones", group="Nature", assets=[{"asset": "stone"}],
             surfaces=[ground], count=6, seed=1)
        call("scatter_on_surface", name="Rocks", group="Nature", assets=[{"asset": "stone"}],
             surfaces=[ground], count=4, seed=2, output="placements")
        call("save_scene_snapshot", name="v1")

        assert call("validate_scene")["error_count"] == 0
        project.audit_everything()


def test_a_z_up_centimeter_scene_stays_clean():
    """Nearly every tool in a Z-up centimeter scene, where each placement, light, camera,
    scatter and physics value is converted: each call audited, then every variant."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _Project(Path(tmp), up="Z", mpu=0.01)
        call = project.call
        table = call("place_asset", asset="table", asset_name="Table", group="Furniture",
                     translate_x=0, translate_y=0, translate_z=0, rotate_z=90)["prim_path"]
        post = call("place_asset", asset="post", asset_name="Post", group="Props",
                    translate_x=200, translate_y=0, translate_z=0)["prim_path"]
        lamp = call("place_asset", asset="lamp", asset_name="Lamp", group="Props",
                    translate_x=-150, translate_y=50, translate_z=0)["prim_path"]
        ground = call("place_asset", asset="ground", asset_name="Ground", group="Architecture",
                      translate_x=0, translate_y=600, translate_z=-5)["prim_path"]
        call("place_asset_inside", asset="post", asset_name="Pin", container_prim_path=table,
             group="Props", translate_x=0, translate_y=0, translate_z=10)
        call("place_layout", placements=[{
            "asset": "crate", "group": "Storage",
            "pattern": {"type": "grid", "origin": [400, 0, 0], "count": [2, 2],
                        "spacing": [50, 50]}}])
        call("create_light", light_type="SphereLight", light_name="Bulb", asset_prim_path=post,
             translate_z=0.2)
        call("create_light", light_type="RectLight", light_name="Glow", asset_prim_path=table,
             texture="textures/glow.png", position_mode="absolute",
             translate_x=0, translate_y=0, translate_z=60)
        call("create_light", light_type="DomeLight", light_name="Sky", texture="hdri/sky.png")
        call("create_light", light_type="DiskLight", light_name="Key", translate_z=300)
        call("update_light", prim_path="/Scene/Lighting/Key", translate_x=100, rotate_x=20)
        call("create_camera", camera_name="Hero", translate_x=400, translate_y=-400,
             translate_z=200, look_at=[0, 0, 50])
        call("update_camera", prim_path="/Scene/Cameras/Hero", translate_z=250,
             look_at=[0, 0, 0])

        oak = call("create_material", prim_path=f"{table}/asset/Top",
                   material_name="oak")["material"]
        call("bind_material", prim_path=f"{table}/asset/Leg", material_asset="woodmat")
        call("add_asset_material_variant", prim_path=table, variant_set="look",
             variant_name="oak", bindings={f"{table}/asset/Leg": oak})
        call("add_asset_attribute_variant", prim_path=table, variant_set="size",
             variant_name="big", overrides={f"{table}/asset/Top": {"size": 2.0}})
        call("add_asset_configuration_variant", prim_path=table, variant_set="legs",
             variant_name="none", activations={f"{table}/asset/Leg": False})
        call("select_asset_variant", prim_path=table, variant_set="look", variant_name="oak")
        call("select_asset_variant_for_instance", prim_path=table, variant_set="size",
             variant_name="big")
        call("setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
             variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"},
             default_variant="high")
        call("add_asset_geometry_variant", prim_path=lamp, variant_set="lod",
             variant_name="mid", payloads={lamp: "./geo_low.usda"})
        call("add_scene_lighting_attribute_variant", variant_set="mood", variant_name="dim",
             overrides={"/Scene/Lighting/Key": {"inputs:intensity": 0.3}})
        call("add_scene_lighting_selection_variant", variant_set="rig", variant_name="sky_only",
             activations={"/Scene/Lighting/Key": False, "/Scene/Lighting/Sky": True})
        call("select_scene_variant", prim_path="/Scene/Lighting", variant_set="mood",
             variant_name="dim")
        call("add_scene_model_selection_variant", prim_path=post, variant_set="model",
             variant_name="chair", asset="chair_cm", set_as_default=True)
        call("move_asset", prim_path=post, translate_x=250, rotate_z=15)
        call("set_prim_attribute", prim_path="/Scene/Lighting/Key",
             attribute_name="inputs:intensity", value=4.0)

        physics = call("setup_physics_scene")
        assert abs(physics["gravity_magnitude"] - 981.0) < 1e-6
        call("apply_physics_api", prim_path=table, api_name="PhysicsRigidBodyAPI", scope="scene")
        call("apply_physics_api", prim_path=lamp, api_name="PhysicsRigidBodyAPI", scope="scene")
        call("apply_physics_api", prim_path=f"{table}/asset/Top", api_name="PhysicsCollisionAPI")
        call("apply_physics_api", prim_path=f"{table}/asset/Leg", api_name="PhysicsCollisionAPI")
        call("apply_physics_api", prim_path=f"{table}/asset/Top",
             api_name="PhysicsFilteredPairsAPI",
             relationships={"physics:filteredPairs": [f"{table}/asset/Leg"]})
        call("create_joint", joint_type="PhysicsRevoluteJoint", name="hinge", body0=table,
             body1=lamp, scope="scene", attributes={"physics:axis": "Z"})
        call("create_or_update_collision_group", name="Furniture", includes=[table, lamp])

        call("scatter_on_surface", name="Stones", group="Nature", assets=[{"asset": "stone"}],
             surfaces=[ground], count=6, seed=1)
        call("scatter_along_path", name="Fence", group="Nature", assets=[{"asset": "crate"}],
             points=[[-300, 400, 0], [300, 400, 0]], count=4, surfaces=[ground])
        floating = call("place_asset", asset="crate", asset_name="Floating", group="Props",
                        translate_x=100, translate_y=600, translate_z=200)["prim_path"]
        call("drop_to_surface", prim_paths=[floating], surfaces=[ground])
        call("freeze_asset")
        call("save_scene_snapshot", name="v1")
        call("package_scene")
        assert call("validate_scene")["error_count"] == 0
        project.audit_everything()


def test_removing_what_was_added_restores_the_project():
    """Each removal (or move back) undoes its creation: scene.usda and the asset folders come
    back byte-identical, with the groups it created gone, once the assets and files the
    removal reports unused are deleted."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _Project(Path(tmp))
        call = project.call
        table = call("place_asset", asset="table", asset_name="Table", group="Furniture",
                     translate_x=0, translate_y=0, translate_z=0)["prim_path"]
        chair = call("place_asset", asset="chair", asset_name="Chair", group="Furniture",
                     translate_x=2, translate_y=0, translate_z=0)["prim_path"]
        lamp = call("place_asset", asset="lamp", asset_name="Lamp", group="Props",
                    translate_x=4, translate_y=0, translate_z=0)["prim_path"]
        ground = call("place_asset", asset="ground", asset_name="Ground", group="Architecture",
                      translate_x=0, translate_y=0, translate_z=8)["prim_path"]
        call("setup_physics_scene")
        top, leg = f"{table}/asset/Top", f"{table}/asset/Leg"
        rt = project.round_trip
        rt(lambda: call("place_asset", asset="crate", asset_name="Crate", group="Props",
                        translate_x=6, translate_y=0, translate_z=0),
           lambda made: project.remove("remove_prim", prim_path=made["prim_path"]))
        rt(lambda: call("create_light", light_type="SphereLight", light_name="Key"),
           lambda made: call("remove_light", prim_path=made["prim_path"]))
        rt(lambda: call("create_light", light_type="SphereLight", light_name="Bulb",
                        asset_prim_path=lamp),
           lambda made: call("remove_light", prim_path=made["prim_path"]))
        rt(lambda: call("create_camera", camera_name="Cam", translate_x=3, translate_y=2,
                        translate_z=3, look_at=[0, 0, 0]),
           lambda made: call("remove_camera", prim_path=made["prim_path"]))
        rt(lambda: call("create_material", prim_path=top, material_name="oak"),
           lambda made: call("remove_material", prim_path=top))
        rt(lambda: call("apply_physics_api", prim_path=chair, api_name="PhysicsRigidBodyAPI",
                        scope="scene"),
           lambda made: call("remove_physics_api", prim_path=chair,
                             api_name="PhysicsRigidBodyAPI", scope="scene"))
        rt(lambda: call("apply_physics_api", prim_path=leg, api_name="PhysicsCollisionAPI"),
           lambda made: call("remove_physics_api", prim_path=leg, api_name="PhysicsCollisionAPI"))
        rt(lambda: call("create_or_update_collision_group", name="Group", includes=[chair]),
           lambda made: call("remove_collision_group", name="Group"))
        def remove_lod(made: dict[str, Any]) -> None:
            removed = project.remove("remove_asset_variant_set", prim_path=lamp, variant_set="lod")
            assert removed["unused_files"] == ["assets/lamp/geo_low.usda"]

        rt(lambda: call("setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
                        variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"},
                        default_variant="high"),
           remove_lod)
        call("apply_physics_api", prim_path=top, api_name="PhysicsCollisionAPI")
        call("apply_physics_api", prim_path=leg, api_name="PhysicsCollisionAPI")
        rt(lambda: call("apply_physics_api", prim_path=top, api_name="PhysicsFilteredPairsAPI",
                        relationships={"physics:filteredPairs": [leg]}),
           lambda made: call("remove_physics_api", prim_path=top,
                             api_name="PhysicsFilteredPairsAPI"))
        rt(lambda: call("add_asset_attribute_variant", prim_path=table, variant_set="size",
                        variant_name="big", overrides={top: {"size": 2.0}}),
           lambda made: call("remove_asset_variant_set", prim_path=table, variant_set="size"))
        rt(lambda: call("add_scene_model_selection_variant", prim_path=chair,
                        variant_set="model", variant_name="cm", asset="chair_cm"),
           lambda made: project.remove("remove_scene_variant_set", prim_path=chair,
                                       variant_set="model"))
        rt(lambda: call("place_asset_inside", asset="crate", asset_name="Box",
                        container_prim_path=table, group="Props",
                        translate_x=0, translate_y=0.1, translate_z=0),
           lambda made: project.remove("remove_prim", prim_path=made["prim_path"]))
        rt(lambda: call("scatter_on_surface", name="Stones", group="Nature",
                        assets=[{"asset": "stone"}], surfaces=[ground], count=5, seed=1),
           lambda made: project.remove("remove_prim", prim_path="/Scene/Nature/Stones"))
        rt(lambda: call("rename_prim", old_path=chair, new_path="/Scene/Dining/Seat"),
           lambda made: call("rename_prim", old_path=made["new_path"], new_path=chair))


# Tools that create something, and what undoes each; the round trips below cover them all.
_CREATES = re.compile(r"^(create_|place_|add_|apply_|bind_|setup_|save_|scatter_)")
_NOT_UNDONE = {
    "create_project": "makes a new project; nothing deletes a project",
}


def test_every_creation_is_undone_exactly():
    """Each tool that creates something, undone by its removal (and the deletion of what the
    removal reports unused), gives the project back byte for byte."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _Project(Path(tmp))
        call, rt = project.call, project.round_trip
        table = call("place_asset", asset="table", asset_name="Table", group="Furniture",
                     translate_x=0, translate_y=0, translate_z=0)["prim_path"]
        chair = call("place_asset", asset="chair", asset_name="Chair", group="Furniture",
                     translate_x=2, translate_y=0, translate_z=0)["prim_path"]
        lamp = call("place_asset", asset="lamp", asset_name="Lamp", group="Props",
                    translate_x=4, translate_y=0, translate_z=0)["prim_path"]
        ground = call("place_asset", asset="ground", asset_name="Ground", group="Architecture",
                      translate_x=0, translate_y=-0.1, translate_z=8)["prim_path"]
        call("setup_physics_scene")
        top, leg = f"{table}/asset/Top", f"{table}/asset/Leg"

        def gone(path: str) -> None:
            project.remove("remove_prim", prim_path=path)

        # ── placements ──
        rt(lambda: call("place_asset", asset="crate", asset_name="Crate", group="Props",
                        translate_x=6, translate_y=0, translate_z=0),
           lambda made: gone(made["prim_path"]))
        rt(lambda: call("place_asset_inside", asset="crate", asset_name="Box",
                        container_prim_path=table, group="Props",
                        translate_x=0, translate_y=0.1, translate_z=0),
           lambda made: gone(made["prim_path"]))
        rt(lambda: call("place_layout", placements=[{
            "asset": "crate", "group": "Storage/Racks",
            "pattern": {"type": "grid", "origin": [4, 0, 4], "count": [2, 2],
                        "spacing": [0.5, 0.5]}}]),
           lambda made: gone("/Scene/Storage/Racks"))
        rt(lambda: call("scatter_on_surface", name="Stones", group="Nature",
                        assets=[{"asset": "stone"}], surfaces=[ground], count=5, seed=1),
           lambda made: gone("/Scene/Nature/Stones"))
        rt(lambda: call("scatter_on_surface", name="Rocks", group="Nature",
                        assets=[{"asset": "stone"}], surfaces=[ground], count=3, seed=2,
                        output="placements"),
           lambda made: gone("/Scene/Nature/Rocks"))
        rt(lambda: call("scatter_along_path", name="Posts", group="Street",
                        assets=[{"asset": "crate"}], points=[[-3, 0, 8], [3, 0, 8]], count=4,
                        surfaces=[ground]),
           lambda made: gone("/Scene/Street/Posts"))

        # ── lights and cameras ──
        rt(lambda: call("create_light", light_type="SphereLight", light_name="Key"),
           lambda made: call("remove_light", prim_path=made["prim_path"]))
        rt(lambda: call("create_light", light_type="DomeLight", light_name="Sky",
                        texture="hdri/sky.png"),
           lambda made: project.remove("remove_light", prim_path=made["prim_path"]))
        rt(lambda: call("create_light", light_type="RectLight", light_name="Glow",
                        asset_prim_path=table, texture="textures/glow.png", rotate_x=-90),
           lambda made: project.remove("remove_light", prim_path=made["prim_path"]))
        rt(lambda: call("create_camera", camera_name="Cam", translate_x=3, translate_y=2,
                        translate_z=3, look_at=[0, 0, 0]),
           lambda made: call("remove_camera", prim_path=made["prim_path"]))

        # ── materials ──
        rt(lambda: call("create_material", prim_path=top, material_name="oak"),
           lambda made: project.remove("remove_material", prim_path=top))
        rt(lambda: call("bind_material", prim_path=leg, material_asset="woodmat"),
           lambda made: project.remove("remove_material", prim_path=leg))

        # ── asset variants ──
        def oak_look() -> dict[str, Any]:
            oak = call("create_material", prim_path=top, material_name="oak")["material"]
            return call("add_asset_material_variant", prim_path=table, variant_set="look",
                        variant_name="oak", bindings={leg: oak})

        def no_look(made: dict[str, Any]) -> None:
            project.remove("remove_asset_variant", prim_path=table, variant_set="look",
                           variant_name="oak")
            project.remove("remove_material", prim_path=top)

        rt(oak_look, no_look)
        rt(lambda: call("add_asset_attribute_variant", prim_path=table, variant_set="size",
                        variant_name="big", overrides={top: {"size": 2.0}}),
           lambda made: call("remove_asset_variant", prim_path=table, variant_set="size",
                             variant_name="big"))
        rt(lambda: call("add_asset_configuration_variant", prim_path=table, variant_set="legs",
                        variant_name="none", activations={leg: False}),
           lambda made: call("remove_asset_variant_set", prim_path=table, variant_set="legs"))

        def lods() -> dict[str, Any]:
            call("setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
                 variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"},
                 default_variant="high")
            return call("add_asset_geometry_variant", prim_path=lamp, variant_set="lod",
                        variant_name="mid", payloads={lamp: "./geo_low.usda"})

        rt(lods, lambda made: project.remove("remove_asset_variant_set", prim_path=lamp,
                                             variant_set="lod"))

        def per_instance() -> dict[str, Any]:
            call("add_asset_attribute_variant", prim_path=table, variant_set="size",
                 variant_name="big", overrides={top: {"size": 2.0}})
            call("add_asset_attribute_variant", prim_path=table, variant_set="size",
                 variant_name="small", overrides={top: {"size": 0.5}})
            call("select_asset_variant", prim_path=table, variant_set="size",
                 variant_name="small")
            return call("select_asset_variant_for_instance", prim_path=table,
                        variant_set="size", variant_name="big")

        rt(per_instance, lambda made: call("remove_asset_variant_set", prim_path=table,
                                           variant_set="size"))

        # ── scene variants ──
        def moods() -> dict[str, Any]:
            call("create_light", light_type="SphereLight", light_name="Key")
            call("add_scene_lighting_attribute_variant", variant_set="mood", variant_name="dim",
                 overrides={"/Scene/Lighting/Key": {"inputs:intensity": 0.3}})
            call("add_scene_lighting_attribute_variant", variant_set="mood",
                 variant_name="bright", overrides={"/Scene/Lighting/Key": {"inputs:intensity": 3}})
            return call("select_scene_variant", prim_path="/Scene/Lighting", variant_set="mood",
                        variant_name="bright")

        def no_moods(made: dict[str, Any]) -> None:
            call("remove_scene_variant", prim_path="/Scene/Lighting", variant_set="mood",
                 variant_name="dim")
            call("remove_scene_variant", prim_path="/Scene/Lighting", variant_set="mood",
                 variant_name="bright")
            call("remove_light", prim_path="/Scene/Lighting/Key")

        rt(moods, no_moods)

        def rigs() -> dict[str, Any]:
            call("create_light", light_type="SphereLight", light_name="Key")
            call("create_light", light_type="DiskLight", light_name="Fill")
            return call("add_scene_lighting_selection_variant", variant_set="rig",
                        variant_name="key_only",
                        activations={"/Scene/Lighting/Key": True, "/Scene/Lighting/Fill": False})

        def no_rigs(made: dict[str, Any]) -> None:
            call("remove_scene_variant_set", prim_path="/Scene/Lighting", variant_set="rig")
            call("remove_light", prim_path="/Scene/Lighting/Key")
            call("remove_light", prim_path="/Scene/Lighting/Fill")

        rt(rigs, no_rigs)
        rt(lambda: call("add_scene_model_selection_variant", prim_path=chair,
                        variant_set="model", variant_name="cm", asset="chair_cm"),
           lambda made: project.remove("remove_scene_variant_set", prim_path=chair,
                                       variant_set="model"))

        # ── physics ──
        rt(lambda: call("setup_physics_scene", name="Moon", gravity_magnitude=1.62),
           lambda made: call("remove_physics_scene", name="Moon"))
        rt(lambda: call("apply_physics_api", prim_path=chair, api_name="PhysicsMassAPI",
                        scope="scene", attributes={"physics:mass": 4.0}),
           lambda made: call("remove_physics_api", prim_path=chair, api_name="PhysicsMassAPI",
                             scope="scene"))

        def scene_joint() -> dict[str, Any]:
            call("apply_physics_api", prim_path=chair, api_name="PhysicsRigidBodyAPI",
                 scope="scene")
            return call("create_joint", joint_type="PhysicsFixedJoint", name="bolt",
                        body0=chair, body1=table, scope="scene")

        def no_scene_joint(made: dict[str, Any]) -> None:
            call("remove_joint", scope="scene", prim_path=made["prim_path"])
            call("remove_physics_api", prim_path=chair, api_name="PhysicsRigidBodyAPI",
                 scope="scene")

        rt(scene_joint, no_scene_joint)

        def asset_joint() -> dict[str, Any]:
            call("apply_physics_api", prim_path=top, api_name="PhysicsRigidBodyAPI")
            call("apply_physics_api", prim_path=leg, api_name="PhysicsRigidBodyAPI")
            return call("create_joint", joint_type="PhysicsRevoluteJoint", name="hinge",
                        body0=top, body1=leg, scope="asset",
                        attributes={"physics:axis": "Y"})

        def no_asset_joint(made: dict[str, Any]) -> None:
            call("remove_joint", scope="asset", name="hinge", asset_anchor_prim_path=table)
            call("remove_physics_api", prim_path=leg, api_name="PhysicsRigidBodyAPI")
            call("remove_physics_api", prim_path=top, api_name="PhysicsRigidBodyAPI")

        rt(asset_joint, no_asset_joint)
        rt(lambda: call("create_or_update_collision_group", name="Solid", includes=[chair, table],
                        filtered_groups=["Solid"]),
           lambda made: call("remove_collision_group", name="Solid"))

        # ── snapshots, edits that are moved or set back ──
        rt(lambda: call("save_scene_snapshot", name="v1"),
           lambda made: project.remove("delete_scene_snapshot", name="v1"))

        def only_in_a_snapshot() -> dict[str, Any]:
            crate = call("place_asset", asset="crate", asset_name="Crate", group="Props",
                         translate_x=6, translate_y=0, translate_z=0)["prim_path"]
            call("create_light", light_type="DomeLight", light_name="Sky", texture="hdri/sky.png")
            call("save_scene_snapshot", name="v2")
            project.remove("remove_prim", prim_path=crate)
            return project.remove("remove_light", prim_path="/Scene/Lighting/Sky")

        def snapshot_gone(made: dict[str, Any]) -> None:
            assert not made["unused_files"], "the snapshot still uses the sky texture"
            gone_now = project.remove("delete_scene_snapshot", name="v2")
            assert gone_now["unused_assets"] == ["crate"]
            assert gone_now["unused_files"] == ["textures/sky.png"]

        rt(only_in_a_snapshot, snapshot_gone)

        def crate_on_a_post() -> dict[str, Any]:
            post = call("place_asset", asset="post", asset_name="Post", group="Props",
                        translate_x=8, translate_y=0, translate_z=0)["prim_path"]
            call("place_asset_inside", asset="crate", asset_name="Box",
                 container_prim_path=post, group="Props",
                 translate_x=8, translate_y=0.5, translate_z=0)
            return {"prim_path": post}

        def post_gone(made: dict[str, Any]) -> None:
            # post's contents.usda still places crate, so only post is unused; deleting
            # post then reports crate (the cascade _delete_reported follows).
            removed = project.remove("remove_prim", prim_path=made["prim_path"])
            assert removed["unused_assets"] == ["post"]

        rt(crate_on_a_post, post_gone)
        rt(lambda: call("move_asset", prim_path=chair, translate_x=3, translate_z=1, rotate_y=45),
           lambda made: call("move_asset", prim_path=chair, translate_x=2, translate_z=0,
                             rotate_y=0))
        rt(lambda: call("set_prim_attribute", prim_path=top, attribute_name="visibility",
                        value="invisible"),
           lambda made: call("set_prim_attribute", prim_path=top, attribute_name="visibility",
                             value=None))

        def floating_then_dropped() -> dict[str, Any]:
            crate = call("place_asset", asset="crate", asset_name="Crate", group="Props",
                         translate_x=0, translate_y=2, translate_z=8)["prim_path"]
            call("drop_to_surface", prim_paths=[crate], surfaces=[ground])
            return {"prim_path": crate}

        rt(floating_then_dropped, lambda made: gone(made["prim_path"]))

        def lit_and_framed() -> dict[str, Any]:
            call("create_light", light_type="SphereLight", light_name="Key", translate_y=3)
            call("update_light", prim_path="/Scene/Lighting/Key", translate_x=2, rotate_y=30)
            call("create_camera", camera_name="Cam", translate_x=3, translate_y=2, translate_z=3)
            return call("update_camera", prim_path="/Scene/Cameras/Cam", look_at=[0, 0, 0])

        def unlit(made: dict[str, Any]) -> None:
            call("remove_camera", prim_path="/Scene/Cameras/Cam")
            call("remove_light", prim_path="/Scene/Lighting/Key")

        rt(lit_and_framed, unlit)

        # ── calls that change nothing on a clean project ──
        for tool, params in (("freeze_asset", {}), ("cleanup_unused_contents", {}),
                             ("cleanup_unused_materials", {}), ("create_stage", {}),
                             ("open_project", {"name": "audit"})):
            rt(lambda tool=tool, params=params: call(tool, **params), lambda made: None)
        rt(lambda: call("package_scene"), lambda made: None, keep=(r"\.usdz$",))

        creators = {t.name for t in dispatcher.TOOLS if _CREATES.search(t.name)}
        missing = creators - project.round_tripped - set(_NOT_UNDONE)
        assert not missing, f"creations without a round trip: {sorted(missing)}"


def test_every_tool_that_changes_the_project_is_audited():
    """Each such tool is called somewhere in this module, so its result is audited."""
    source = Path(__file__).read_text()
    changing = {t.name for t in dispatcher.TOOLS if str(t.effect) != "read"}
    called = {name for name in changing if f'call("{name}"' in source
              or f"'{name}'" in source or f'("{name}",' in source}
    assert changing <= called, sorted(changing - called)


def test_renaming_and_removing_a_placement_everything_points_at():
    """A crate that a joint, a collision group, a pair filter, a light link and a per-placement
    override all name: renaming rewrites every one; removing leaves nothing dangling."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _Project(Path(tmp))
        call = project.call
        chair = call("place_asset", asset="chair", asset_name="Chair", group="Furniture",
                     translate_x=2, translate_y=0, translate_z=0)["prim_path"]
        crate = call("place_asset", asset="crate", asset_name="Crate", group="Props",
                     translate_x=6, translate_y=0, translate_z=0)["prim_path"]
        call("setup_physics_scene")
        for path in (chair, crate):
            call("apply_physics_api", prim_path=path, api_name="PhysicsRigidBodyAPI",
                 scope="scene")
        call("apply_physics_api", prim_path=chair, api_name="PhysicsFilteredPairsAPI",
             scope="scene", relationships={"physics:filteredPairs": [crate]})
        call("create_joint", joint_type="PhysicsFixedJoint", name="bolt", body0=chair,
             body1=crate, scope="scene")
        call("create_or_update_collision_group", name="Boxes", includes=[crate])
        call("create_light", light_type="SphereLight", light_name="Spot",
             light_link_includes=[crate])
        call("set_prim_attribute", prim_path=f"{crate}/asset/Mesh", attribute_name="visibility",
             value="invisible")

        moved = call("rename_prim", old_path=crate, new_path="/Scene/Storage/Crate")
        crate = moved["new_path"]
        stage = project.state.require_stage()
        text = project.path.joinpath("scene.usda").read_text()
        assert "Props/Crate" not in text, "a relationship still names the old path"
        assert f"<{crate}>" in text

        removed = call("remove_prim", prim_path=crate)
        assert removed["scrubbed_dangling_refs"]["rels_touched"]
        text = project.path.joinpath("scene.usda").read_text()
        assert "Crate" not in text, "something still names the removed crate"
        assert not stage.GetPrimAtPath("/Scene/Storage")
        assert call("validate_scene")["error_count"] == 0
        project.audit_everything()
