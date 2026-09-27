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
        self.call("create_project", name="audit", up_axis=up, meters_per_unit=mpu)

    @property
    def path(self) -> Path:
        return self.state.require_project().path

    def call(self, tool: str, **params: Any) -> dict[str, Any]:
        """Run *tool*; it must succeed, and a change must leave the project clean."""
        result = asyncio.run(exec_tool(self.state, tool, params))
        assert result.success, f"{tool}({params}): {result.error}"
        if not READ_ONLY.search(tool):
            found = problems(audit_project(self.path, sweep_variants=False))
            assert not found, f"after {tool}({params}):\n" + "\n".join(map(str, found))
        return result.data or {}

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
        remove(create())
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
    """Conformed placements, nesting, asset lights and model variants in a Z-up cm scene."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _Project(Path(tmp), up="Z", mpu=0.01)
        call = project.call
        table = call("place_asset", asset="table", asset_name="Table", group="Furniture",
                     translate_x=0, translate_y=0, translate_z=0, rotate_z=90)["prim_path"]
        post = call("place_asset", asset="post", asset_name="Post", group="Props",
                    translate_x=200, translate_y=0, translate_z=0)["prim_path"]
        call("place_asset_inside", asset="post", asset_name="Pin", container_prim_path=table,
             group="Props", translate_x=0, translate_y=0, translate_z=10)
        call("create_light", light_type="SphereLight", light_name="Bulb", asset_prim_path=post,
             translate_z=0.2)
        call("add_scene_model_selection_variant", prim_path=post, variant_set="model",
             variant_name="chair", asset="chair_cm", set_as_default=True)
        call("move_asset", prim_path=post, translate_x=250, rotate_z=15)
        assert call("validate_scene")["error_count"] == 0
        project.audit_everything()


def test_removing_what_was_added_restores_the_project():
    """Each removal (or move back) undoes its creation: scene.usda and the asset folders come
    back byte-identical, with the groups it created gone. Only the project's own copies of
    newly placed assets remain."""
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
        new_asset_copy = (r"^assets/(crate|stone)/",)

        rt = project.round_trip
        rt(lambda: call("place_asset", asset="crate", asset_name="Crate", group="Props",
                        translate_x=6, translate_y=0, translate_z=0),
           lambda made: call("remove_prim", prim_path=made["prim_path"]), keep=new_asset_copy)
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
            """Remove the set, then delete the file it reports unused (the user's yes)."""
            removed = asyncio.run(exec_tool(project.state, "remove_asset_variant_set", {
                "prim_path": lamp, "variant_set": "lod",
            }))
            assert removed.data["unused_files"] == ["assets/lamp/geo_low.usda"]
            call("delete_project_file", file_name="assets/lamp/geo_low.usda")

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
           lambda made: call("remove_scene_variant_set", prim_path=chair, variant_set="model"),
           keep=(r"^assets/chair_cm/",))
        rt(lambda: call("place_asset_inside", asset="crate", asset_name="Box",
                        container_prim_path=table, group="Props",
                        translate_x=0, translate_y=0.1, translate_z=0),
           lambda made: call("remove_prim", prim_path=made["prim_path"]), keep=new_asset_copy)
        rt(lambda: call("scatter_on_surface", name="Stones", group="Nature",
                        assets=[{"asset": "stone"}], surfaces=[ground], count=5, seed=1),
           lambda made: call("remove_prim", prim_path="/Scene/Nature/Stones"), keep=new_asset_copy)
        rt(lambda: call("rename_prim", old_path=chair, new_path="/Scene/Dining/Seat"),
           lambda made: call("rename_prim", old_path=made["new_path"], new_path=chair))
