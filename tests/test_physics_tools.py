# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for physics: APIs, joints, collision groups, scene, summary."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Gf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdPhysics

from bowerbot import config
from tests import _helpers


def _asset(directory: Path, name: str) -> Path:
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, f"/{name}/Mesh").GetSizeAttr().Set(1.0)
    stage.Save()
    return path


def _mesh_asset(directory: Path, name: str) -> Path:
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    mesh = UsdGeom.Mesh.Define(stage, f"/{name}/Mesh")
    mesh.GetPointsAttr().Set([
        Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 0, 0), Gf.Vec3f(0, 1, 0),
    ])
    mesh.GetFaceVertexCountsAttr().Set([3])
    mesh.GetFaceVertexIndicesAttr().Set([0, 1, 2])
    stage.Save()
    return path


def _setup(tmp):
    tmp_path = Path(tmp)
    state, project = _helpers.make_state(tmp_path)
    asyncio.run(_helpers.exec_tool(state, "create_stage", {"filename": "test"}))
    return tmp_path, state, project


def _place(tmp_path, state, name="box"):
    asset = _asset(tmp_path, name)
    r = asyncio.run(_helpers.exec_tool(state, "place_asset", {
        "asset_file_path": str(asset), "asset_name": name.title(),
        "group": "Props",
        "translate_x": 0.0, "translate_y": 1.0, "translate_z": 0.0,
    }))
    assert r.success, r.error
    return r


# ── list_physics_api_properties ──


def test_list_physics_api_properties_rigid_body():
    """Returns properties for PhysicsRigidBodyAPI."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "list_physics_api_properties", {
            "api_name": "PhysicsRigidBodyAPI",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "physics:velocity" in names
        assert "physics:rigidBodyEnabled" in names


def test_list_physics_api_properties_collision():
    """Returns properties for PhysicsCollisionAPI."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "list_physics_api_properties", {
            "api_name": "PhysicsCollisionAPI",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "physics:collisionEnabled" in names


def test_list_physics_api_properties_mass():
    """Returns properties for PhysicsMassAPI."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "list_physics_api_properties", {
            "api_name": "PhysicsMassAPI",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "physics:mass" in names


def test_list_physics_api_properties_invalid():
    """Returns error for unknown API name."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "list_physics_api_properties", {
            "api_name": "FakeAPI",
        }))
        assert not r.success


# ── apply_physics_api ──


def test_apply_rigid_body_scene_scope():
    """Applies RigidBodyAPI at scene scope."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        prim_path = placed.data["prim_path"]

        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": prim_path,
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.HasAPI(UsdPhysics.RigidBodyAPI)


def test_apply_collision_with_companion():
    """Applying MeshCollisionAPI auto-applies CollisionAPI."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        mesh_asset = _mesh_asset(tmp_path, "wall")
        placed = asyncio.run(_helpers.exec_tool(state, "place_asset", {
            "asset_file_path": str(mesh_asset), "asset_name": "Wall",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert placed.success, placed.error
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsMeshCollisionAPI",
            "scope": "scene",
        }))
        assert r.success, r.error
        assert r.data.get("companion_api") == "PhysicsCollisionAPI"


def test_apply_physics_api_asset_scope():
    """Applies API at asset scope, creating phy.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsCollisionAPI",
        }))
        assert r.success, r.error
        assert r.data["scope"] == "asset"

        phy_path = project.assets_dir / "box" / "phy.usda"
        assert phy_path.exists()


def test_apply_physics_api_invalid_prim():
    """Fails for nonexistent prim."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": "/Scene/Nope",
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
        }))
        assert not r.success


# ── remove_physics_api ──


def test_remove_physics_api():
    """Removes an applied API."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsCollisionAPI",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "remove_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsCollisionAPI",
        }))
        assert r.success, r.error


# ── setup_physics_scene ──


def test_setup_physics_scene():
    """Creates /Scene/Physics/PhysicsScene."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.IsValid()
        assert prim.IsA(UsdPhysics.Scene)


def test_setup_physics_scene_custom_gravity():
    """Creates scene with custom gravity magnitude and echoes it back."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {
            "gravity_magnitude": 1.62,
        }))
        assert r.success, r.error
        assert r.data["gravity_magnitude"] == 1.62


def test_default_gravity_points_down_in_a_z_up_centimeter_project():
    """Default gravity is Earth's in project units, along minus the project's up axis."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = _helpers.make_state(
            Path(tmp), up_axis=config.UpAxis.Z, meters_per_unit=0.01,
        )
        asyncio.run(_helpers.exec_tool(state, "create_stage", {"filename": "test"}))
        r = asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
        assert r.success, r.error
        assert r.data["gravity_direction"] == [0.0, 0.0, -1.0]
        assert abs(r.data["gravity_magnitude"] - 981.0) < 1e-6


def test_setup_physics_scene_reports_resolved_gravity():
    """With no gravity params, the response reports the authored Earth gravity, not null."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
        assert r.success, r.error
        assert r.data["gravity_magnitude"] == 9.81
        assert r.data["gravity_direction"] == [0.0, -1.0, 0.0]

        stage = Usd.Stage.Open(str(project.scene_path))
        scene = UsdPhysics.Scene(stage.GetPrimAtPath(r.data["prim_path"]))
        assert abs(scene.GetGravityMagnitudeAttr().Get() - 9.81) < 1e-6
        gd = scene.GetGravityDirectionAttr().Get()
        assert (round(gd[0], 3), round(gd[1], 3), round(gd[2], 3)) == (0.0, -1.0, 0.0)


# ── get_physics_summary ──


def test_get_physics_summary():
    """Returns a summary after applying APIs."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsCollisionAPI",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "get_physics_summary", {
            "prim_path": placed.data["prim_path"],
        }))
        assert r.success, r.error
        assert r.data["asset"] is not None


# ── list_joint_properties ──


def test_list_joint_properties_revolute():
    """Returns properties for PhysicsRevoluteJoint."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "list_joint_properties", {
            "joint_type": "PhysicsRevoluteJoint",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "physics:axis" in names


def test_list_joint_properties_fixed():
    """Returns properties for PhysicsFixedJoint."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "list_joint_properties", {
            "joint_type": "PhysicsFixedJoint",
        }))
        assert r.success, r.error


# ── create_joint / remove_joint / list_joints ──


def test_create_fixed_joint_scene_scope():
    """Creates a FixedJoint connecting two bodies at scene scope."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        p1 = _place(tmp_path, state, "a")
        p2 = _place(tmp_path, state, "b")

        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))

        r = asyncio.run(_helpers.exec_tool(state, "create_joint", {
            "joint_type": "PhysicsFixedJoint",
            "name": "weld",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
        }))
        assert r.success, r.error
        assert "prim_path" in r.data


def test_list_joints_after_create():
    """Lists joints after creation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        p1 = _place(tmp_path, state, "c")
        p2 = _place(tmp_path, state, "d")

        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))

        asyncio.run(_helpers.exec_tool(state, "create_joint", {
            "joint_type": "PhysicsFixedJoint",
            "name": "link",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "list_joints", {"scope": "scene"}))
        assert r.success, r.error
        assert len(r.data["joints"]) >= 1


def test_remove_joint():
    """Removes a created joint."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        p1 = _place(tmp_path, state, "e")
        p2 = _place(tmp_path, state, "f")

        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))

        created = asyncio.run(_helpers.exec_tool(state, "create_joint", {
            "joint_type": "PhysicsFixedJoint",
            "name": "temp",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "remove_joint", {
            "prim_path": created.data["prim_path"],
            "scope": "scene",
        }))
        assert r.success, r.error
        assert r.data["removed"] is True


# ── collision groups ──


def test_create_collision_group():
    """Creates a collision group with includes."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)

        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))

        r = asyncio.run(_helpers.exec_tool(
            state, "create_or_update_collision_group", {
                "name": "Walls",
                "includes": [placed.data["prim_path"]],
            },
        ))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.IsValid()


def test_list_collision_groups():
    """Lists collision groups after creation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state)
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))

        asyncio.run(_helpers.exec_tool(
            state, "create_or_update_collision_group", {"name": "Floor"},
        ))

        r = asyncio.run(_helpers.exec_tool(state, "list_collision_groups"))
        assert r.success, r.error
        assert len(r.data["groups"]) >= 1


def test_remove_collision_group():
    """Removes a collision group."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state)
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))

        asyncio.run(_helpers.exec_tool(
            state, "create_or_update_collision_group", {"name": "Temp"},
        ))

        r = asyncio.run(_helpers.exec_tool(
            state, "remove_collision_group", {"name": "Temp"},
        ))
        assert r.success, r.error
        assert r.data["removed"] is True


# ── apply_physics_api: with attributes ──


def test_apply_rigid_body_with_attributes():
    """Applies RigidBodyAPI with velocity attribute."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": placed.data["prim_path"],
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
            "attributes": {
                "physics:velocity": [0.0, 5.0, 0.0],
            },
        }))
        assert r.success, r.error
        assert "physics:velocity" in r.data["attributes_set"]


def test_apply_mass_api():
    """Applies MassAPI with mass attribute."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))

        asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": placed.data["prim_path"],
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": placed.data["prim_path"],
            "api_name": "PhysicsMassAPI",
            "scope": "scene",
            "attributes": {"physics:mass": 10.0},
        }))
        assert r.success, r.error


def test_apply_articulation_root():
    """Applies ArticulationRootAPI at scene scope."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": placed.data["prim_path"],
            "api_name": "PhysicsArticulationRootAPI",
            "scope": "scene",
        }))
        assert r.success, r.error


# ── remove_physics_api: cascade ──


def test_remove_collision_cascades_mesh_collision():
    """Removing CollisionAPI also removes MeshCollisionAPI."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        mesh_asset = _mesh_asset(tmp_path, "panel")
        placed = asyncio.run(_helpers.exec_tool(state, "place_asset", {
            "asset_file_path": str(mesh_asset),
            "asset_name": "Panel", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsMeshCollisionAPI",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "remove_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsCollisionAPI",
        }))
        assert r.success, r.error


# ── list_physics_api_properties: more types ──


def test_list_physics_api_properties_mesh_collision():
    """Returns properties for PhysicsMeshCollisionAPI."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(
            state, "list_physics_api_properties",
            {"api_name": "PhysicsMeshCollisionAPI"},
        ))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "physics:approximation" in names


def test_list_physics_api_properties_articulation():
    """Returns properties for PhysicsArticulationRootAPI."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(
            state, "list_physics_api_properties",
            {"api_name": "PhysicsArticulationRootAPI"},
        ))
        assert r.success, r.error


# ── joints: revolute ──


def test_create_revolute_joint():
    """Creates a RevoluteJoint with axis attribute."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        p1 = _place(tmp_path, state, "g")
        p2 = _place(tmp_path, state, "h")

        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))

        r = asyncio.run(_helpers.exec_tool(state, "create_joint", {
            "joint_type": "PhysicsRevoluteJoint",
            "name": "hinge",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
            "attributes": {"physics:axis": "Y"},
        }))
        assert r.success, r.error


# ── collision group: update existing ──


def test_update_collision_group():
    """Updating an existing collision group adds new members."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        p1 = _place(tmp_path, state, "i")
        p2 = _place(tmp_path, state, "j")
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))

        asyncio.run(_helpers.exec_tool(
            state, "create_or_update_collision_group", {
                "name": "Env",
                "includes": [p1.data["prim_path"]],
            },
        ))

        r = asyncio.run(_helpers.exec_tool(
            state, "create_or_update_collision_group", {
                "name": "Env",
                "includes": [p2.data["prim_path"]],
            },
        ))
        assert r.success, r.error


# ── get_physics_summary: scene scope ──


def test_get_physics_summary_scene_scope():
    """Returns scene-side summary after applying API at scene scope."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))

        asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": placed.data["prim_path"],
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "get_physics_summary", {
            "prim_path": placed.data["prim_path"],
        }))
        assert r.success, r.error
        assert r.data["scene"] is not None
        assert len(r.data["scene"]["prims"]) >= 1


# ── setup_physics_scene: custom name ──


def test_setup_physics_scene_custom_name():
    """Creates a physics scene with a custom name."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {
            "name": "SimScene",
        }))
        assert r.success, r.error
        assert "SimScene" in r.data["prim_path"]


# ── DriveAPI ──


def _joint_with_bodies(tmp_path, state):
    """Place two assets, apply RigidBody, create a RevoluteJoint."""
    p1 = _place(tmp_path, state, "arm")
    p2 = _place(tmp_path, state, "hand")
    asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
    for p in [p1, p2]:
        asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": p.data["prim_path"],
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
        }))
    joint = asyncio.run(_helpers.exec_tool(state, "create_joint", {
        "joint_type": "PhysicsRevoluteJoint",
        "name": "hinge",
        "body0": p1.data["prim_path"],
        "body1": p2.data["prim_path"],
        "scope": "scene",
    }))
    assert joint.success, joint.error
    return joint.data["prim_path"]


def test_list_drive_api_properties():
    """Returns DriveAPI properties with instance name substituted."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "list_physics_api_properties", {
            "api_name": "PhysicsDriveAPI",
            "instance_name": "angular",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "drive:angular:physics:stiffness" in names
        assert "drive:angular:physics:damping" in names
        assert "drive:angular:physics:type" in names


def test_list_drive_api_requires_instance_name():
    """Fails when instance_name is omitted for a multi-apply API."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "list_physics_api_properties", {
            "api_name": "PhysicsDriveAPI",
        }))
        assert not r.success


def test_apply_drive_api_on_revolute_joint():
    """Applies DriveAPI:angular on a RevoluteJoint."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        joint_path = _joint_with_bodies(tmp_path, state)

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsDriveAPI",
            "instance_name": "angular",
            "scope": "scene",
            "attributes": {
                "drive:angular:physics:stiffness": 100.0,
                "drive:angular:physics:damping": 10.0,
                "drive:angular:physics:type": "force",
            },
        }))
        assert r.success, r.error
        assert r.data["instance_name"] == "angular"
        assert "drive:angular:physics:stiffness" in r.data["attributes_set"]

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(joint_path)
        assert prim.HasAPI(UsdPhysics.DriveAPI, "angular")


def test_apply_drive_api_refuses_spherical():
    """DriveAPI is not supported on SphericalJoint."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        p1 = _place(tmp_path, state, "ball")
        p2 = _place(tmp_path, state, "socket")
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))
        joint = asyncio.run(_helpers.exec_tool(state, "create_joint", {
            "joint_type": "PhysicsSphericalJoint",
            "name": "ball_socket",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": joint.data["prim_path"],
            "api_name": "PhysicsDriveAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))
        assert not r.success


def test_apply_drive_api_refuses_bad_instance():
    """DriveAPI refuses 'linear' on a RevoluteJoint."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        joint_path = _joint_with_bodies(tmp_path, state)

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsDriveAPI",
            "instance_name": "linear",
            "scope": "scene",
        }))
        assert not r.success
        assert "linear" in r.error


def test_remove_drive_api():
    """Removes an applied DriveAPI:angular."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        joint_path = _joint_with_bodies(tmp_path, state)

        asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsDriveAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "remove_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsDriveAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))
        assert r.success, r.error
        assert r.data["removed"] is True


# ── LimitAPI ──


def test_list_limit_api_properties():
    """Returns LimitAPI properties with instance name substituted."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "list_physics_api_properties", {
            "api_name": "PhysicsLimitAPI",
            "instance_name": "angular",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "limit:angular:physics:low" in names
        assert "limit:angular:physics:high" in names


def test_apply_limit_api_on_revolute_joint():
    """Applies LimitAPI:angular on a RevoluteJoint."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        joint_path = _joint_with_bodies(tmp_path, state)

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsLimitAPI",
            "instance_name": "angular",
            "scope": "scene",
            "attributes": {
                "limit:angular:physics:low": -90.0,
                "limit:angular:physics:high": 90.0,
            },
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(joint_path)
        assert prim.HasAPI(UsdPhysics.LimitAPI, "angular")


def test_apply_limit_api_distance_on_distance_joint():
    """Applies LimitAPI:distance on a DistanceJoint."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        p1 = _place(tmp_path, state, "anchor")
        p2 = _place(tmp_path, state, "tether")
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))
        joint = asyncio.run(_helpers.exec_tool(state, "create_joint", {
            "joint_type": "PhysicsDistanceJoint",
            "name": "rope",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": joint.data["prim_path"],
            "api_name": "PhysicsLimitAPI",
            "instance_name": "distance",
            "scope": "scene",
            "attributes": {
                "limit:distance:physics:low": 0.5,
                "limit:distance:physics:high": 2.0,
            },
        }))
        assert r.success, r.error


def test_apply_limit_api_refuses_fixed_joint():
    """LimitAPI is not supported on FixedJoint."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        p1 = _place(tmp_path, state, "base")
        p2 = _place(tmp_path, state, "top")
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))
        joint = asyncio.run(_helpers.exec_tool(state, "create_joint", {
            "joint_type": "PhysicsFixedJoint",
            "name": "weld",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": joint.data["prim_path"],
            "api_name": "PhysicsLimitAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))
        assert not r.success


def test_remove_api_message_when_present():
    """Message confirms removal when API was present."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))
        asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": placed.data["prim_path"],
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "remove_physics_api", {
            "prim_path": placed.data["prim_path"],
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
        }))
        assert r.success, r.error
        assert r.data["removed"] is True
        assert "Removed" in r.data["message"]


def test_remove_api_message_when_not_present():
    """Message says 'not present' when API was already gone."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))

        r = asyncio.run(_helpers.exec_tool(state, "remove_physics_api", {
            "prim_path": placed.data["prim_path"],
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
        }))
        assert r.success, r.error
        assert r.data["removed"] is False
        assert "not present" in r.data["message"]


def test_remove_api_cascade_message():
    """After cascade removal, second remove says 'not present'."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        mesh_asset = _mesh_asset(tmp_path, "slab")
        placed = asyncio.run(_helpers.exec_tool(state, "place_asset", {
            "asset_file_path": str(mesh_asset),
            "asset_name": "Slab", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsMeshCollisionAPI",
        }))
        asyncio.run(_helpers.exec_tool(state, "remove_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsCollisionAPI",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "remove_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsMeshCollisionAPI",
        }))
        assert r.success, r.error
        assert r.data["removed"] is False
        assert "not present" in r.data["message"]


def test_remove_drive_api_message():
    """Message includes instance name for multi-apply removal."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        joint_path = _joint_with_bodies(tmp_path, state)

        asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsDriveAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "remove_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsDriveAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))
        assert r.success, r.error
        assert r.data["removed"] is True
        assert "DriveAPI:angular" in r.data["message"]


# ── list_physics_scenes / remove_physics_scene ──


def test_list_physics_scenes():
    """Lists created PhysicsScene prims."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {}))

        r = asyncio.run(_helpers.exec_tool(state, "list_physics_scenes"))
        assert r.success, r.error
        assert r.data["count"] >= 1
        names = {s["name"] for s in r.data["scenes"]}
        assert "PhysicsScene" in names


def test_list_physics_scenes_empty():
    """Returns empty when no PhysicsScene exists."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(_helpers.exec_tool(state, "list_physics_scenes"))
        assert r.success, r.error
        assert r.data["count"] == 0


def test_remove_physics_scene_success():
    """Removes a PhysicsScene prim by name."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        asyncio.run(_helpers.exec_tool(state, "setup_physics_scene", {
            "name": "ToDelete",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "remove_physics_scene", {
            "name": "ToDelete",
        }))
        assert r.success, r.error
        assert r.data["removed"] is True
        assert "Removed" in r.data["message"]

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath("/Scene/Physics/ToDelete")
        assert not prim.IsValid()


def test_remove_physics_scene_not_found():
    """Returns removed=false with a clear message for missing scene."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)

        r = asyncio.run(_helpers.exec_tool(state, "remove_physics_scene", {
            "name": "Nonexistent",
        }))
        assert r.success, r.error
        assert r.data["removed"] is False
        assert "not found" in r.data["message"]


def test_remove_limit_api():
    """Removes an applied LimitAPI:angular."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        joint_path = _joint_with_bodies(tmp_path, state)

        asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsLimitAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))

        r = asyncio.run(_helpers.exec_tool(state, "remove_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsLimitAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))
        assert r.success, r.error
        assert r.data["removed"] is True


# ── collider shapes ──


def _cart_asset(directory: Path) -> Path:
    """A Y-up, meters asset whose parts are groups: /cart/Wheel (an Xform) holds the mesh."""
    path = directory / "cart.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    stage.SetDefaultPrim(stage.DefinePrim("/cart", "Xform"))
    wheel = UsdGeom.Xform.Define(stage, "/cart/Wheel")
    wheel.AddTranslateOp().Set(Gf.Vec3d(0.5, 0.3, 0.0))
    UsdGeom.Cube.Define(stage, "/cart/Wheel/Tire").GetSizeAttr().Set(0.4)
    stage.Save()
    return path


def _cart_scene(tmp: str, up_axis: config.UpAxis, meters_per_unit: float):
    """A project in the given convention with the cart placed; returns state and the wheel path."""
    tmp_path = Path(tmp)
    state, _ = _helpers.make_state(tmp_path, up_axis=up_axis, meters_per_unit=meters_per_unit)
    asyncio.run(_helpers.exec_tool(state, "create_stage", {"filename": "test"}))
    placed = asyncio.run(_helpers.exec_tool(state, "place_asset", {
        "asset_file_path": str(_cart_asset(tmp_path)), "asset_name": "Cart", "group": "Props",
        "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
    }))
    assert placed.success, placed.error
    return state, f"{placed.data['prim_path']}/asset/Wheel"


def _world_box(state, prim_path: str, purpose: str):
    """World bounds (min, max) of a prim, counting only geometry of *purpose*."""
    stage = Usd.Stage.Open(str(state.stage_path))
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [purpose])
    box = cache.ComputeWorldBound(stage.GetPrimAtPath(prim_path)).ComputeAlignedRange()
    return box.GetMin(), box.GetMax()


def _collider_shape_sizes(scope: str, up_axis: config.UpAxis, meters_per_unit: float) -> None:
    """A cylinder asked for in project units measures exactly that in the world."""
    with tempfile.TemporaryDirectory() as tmp:
        state, wheel = _cart_scene(tmp, up_axis, meters_per_unit)
        radius, height = 0.3 / meters_per_unit, 0.2 / meters_per_unit
        r = asyncio.run(_helpers.exec_tool(state, "add_collider_shape", {
            "prim_path": wheel, "name": "collider", "shape": "cylinder",
            "radius": radius, "height": height, "axis": "X", "scope": scope,
        }))
        assert r.success, r.error
        assert r.data["prim_path"] == f"{wheel}/collider"

        lo, hi = _world_box(state, r.data["prim_path"], UsdGeom.Tokens.guide)
        size = sorted(hi[i] - lo[i] for i in range(3))
        assert abs(size[0] - height) < 1e-6 * height, size
        assert abs(size[1] - 2 * radius) < 1e-6 * radius, size
        assert abs(size[2] - 2 * radius) < 1e-6 * radius, size
        # The axle runs along the asset's X, which is the world's X in both conventions.
        assert abs((hi[0] - lo[0]) - height) < 1e-6 * height

        # It sits on the wheel's pivot.
        stage = Usd.Stage.Open(str(state.stage_path))
        pivot = UsdGeom.Xformable(stage.GetPrimAtPath(wheel)).ComputeLocalToWorldTransform(
            Usd.TimeCode.Default(),
        ).ExtractTranslation()
        for i in range(3):
            assert abs((lo[i] + hi[i]) / 2 - pivot[i]) < 1e-6 / meters_per_unit


def test_collider_shape_size_asset_scope_y_up_meters():
    _collider_shape_sizes("asset", config.UpAxis.Y, 1.0)


def test_collider_shape_size_asset_scope_z_up_centimeters():
    _collider_shape_sizes("asset", config.UpAxis.Z, 0.01)


def test_collider_shape_size_scene_scope_y_up_meters():
    _collider_shape_sizes("scene", config.UpAxis.Y, 1.0)


def test_collider_shape_size_scene_scope_z_up_centimeters():
    _collider_shape_sizes("scene", config.UpAxis.Z, 0.01)


def test_collider_shape_is_seen_by_physics_only():
    """Renders and the asset's box skip the shape; physics gets a collider under the body."""
    with tempfile.TemporaryDirectory() as tmp:
        state, wheel = _cart_scene(tmp, config.UpAxis.Y, 1.0)
        placement = wheel.rsplit("/asset/", 1)[0]
        before = _world_box(state, placement, UsdGeom.Tokens.default_)
        body = asyncio.run(_helpers.exec_tool(state, "apply_physics_api", {
            "prim_path": wheel, "api_name": "PhysicsRigidBodyAPI",
        }))
        assert body.success, body.error

        r = asyncio.run(_helpers.exec_tool(state, "add_collider_shape", {
            "prim_path": wheel, "name": "collider", "shape": "sphere", "radius": 2.0,
        }))
        assert r.success, r.error

        # A sphere far bigger than the cart does not change the box renders and layout use.
        assert _world_box(state, placement, UsdGeom.Tokens.default_) == before
        stage = Usd.Stage.Open(str(state.stage_path))
        shape = stage.GetPrimAtPath(r.data["prim_path"])
        assert shape.IsA(UsdGeom.Sphere)
        assert UsdGeom.Imageable(shape).GetPurposeAttr().Get() == UsdGeom.Tokens.guide
        assert shape.HasAPI(UsdPhysics.CollisionAPI)
        assert shape.GetParent().HasAPI(UsdPhysics.RigidBodyAPI)

        valid = asyncio.run(_helpers.exec_tool(state, "validate_scene", {}))
        assert valid.success and valid.data["is_valid"], valid.data


def test_box_collider_keeps_its_size_under_a_stretched_part():
    """A box is the size asked for in the world, even when its part is stretched."""
    with tempfile.TemporaryDirectory() as tmp:
        state, wheel = _cart_scene(tmp, config.UpAxis.Y, 1.0)
        placement = wheel.rsplit("/asset/", 1)[0]
        stretched = asyncio.run(_helpers.exec_tool(state, "set_prim_attribute", {
            "prim_path": placement, "attribute_name": "xformOp:scale", "value": [1, 2, 4],
        }))
        assert stretched.success, stretched.error

        r = asyncio.run(_helpers.exec_tool(state, "add_collider_shape", {
            "prim_path": wheel, "name": "block", "shape": "box", "scope": "scene",
            "size_x": 0.5, "size_y": 0.25, "size_z": 1.0,
        }))
        assert r.success, r.error
        lo, hi = _world_box(state, r.data["prim_path"], UsdGeom.Tokens.guide)
        assert [round(hi[i] - lo[i], 6) for i in range(3)] == [0.5, 0.25, 1.0]

        round_one = asyncio.run(_helpers.exec_tool(state, "add_collider_shape", {
            "prim_path": wheel, "name": "ball", "shape": "sphere", "scope": "scene", "radius": 0.2,
        }))
        assert not round_one.success
        assert "ColliderNonUniformScale" in round_one.error


def test_removing_the_only_collider_shape_leaves_nothing_behind():
    """After the removal the asset has no physics file and the scene no leftover opinion."""
    with tempfile.TemporaryDirectory() as tmp:
        state, wheel = _cart_scene(tmp, config.UpAxis.Y, 1.0)
        phy = state.project.assets_dir / "cart" / "phy.usda"
        scene_before = state.stage_path.read_text()

        for scope in ("asset", "scene"):
            added = asyncio.run(_helpers.exec_tool(state, "add_collider_shape", {
                "prim_path": wheel, "name": "collider", "shape": "capsule", "scope": scope,
                "radius": 0.1, "height": 0.4, "axis": "Y",
            }))
            assert added.success, added.error
            assert phy.exists() == (scope == "asset")

            removed = asyncio.run(_helpers.exec_tool(state, "remove_collider_shape", {
                "prim_path": added.data["prim_path"],
            }))
            assert removed.success, removed.error
            assert removed.data["removed"] is True
            assert removed.data["scope"] == scope
            assert not phy.exists()
            assert state.stage_path.read_text() == scene_before
            assert "phy.usda" not in (phy.parent / "cart.usda").read_text()
