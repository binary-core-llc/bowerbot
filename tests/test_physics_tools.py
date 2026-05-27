# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for physics: APIs, joints, collision groups, scene, summary."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Gf, Usd, UsdGeom, UsdPhysics

from tests._helpers import exec_tool, make_state


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
    state, project = make_state(tmp_path)
    asyncio.run(exec_tool(state, "create_stage", {"filename": "test"}))
    return tmp_path, state, project


def _place(tmp_path, state, name="box"):
    asset = _asset(tmp_path, name)
    r = asyncio.run(exec_tool(state, "place_asset", {
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
        r = asyncio.run(exec_tool(state, "list_physics_api_properties", {
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
        r = asyncio.run(exec_tool(state, "list_physics_api_properties", {
            "api_name": "PhysicsCollisionAPI",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "physics:collisionEnabled" in names


def test_list_physics_api_properties_mass():
    """Returns properties for PhysicsMassAPI."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_physics_api_properties", {
            "api_name": "PhysicsMassAPI",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "physics:mass" in names


def test_list_physics_api_properties_invalid():
    """Returns error for unknown API name."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_physics_api_properties", {
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

        asyncio.run(exec_tool(state, "setup_physics_scene", {}))

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(mesh_asset), "asset_name": "Wall",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert placed.success, placed.error
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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
        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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

        asyncio.run(exec_tool(state, "apply_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsCollisionAPI",
        }))

        r = asyncio.run(exec_tool(state, "remove_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsCollisionAPI",
        }))
        assert r.success, r.error


# ── setup_physics_scene ──


def test_setup_physics_scene():
    """Creates /Scene/Physics/PhysicsScene."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        r = asyncio.run(exec_tool(state, "setup_physics_scene", {}))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.IsValid()
        assert prim.IsA(UsdPhysics.Scene)


def test_setup_physics_scene_custom_gravity():
    """Creates scene with custom gravity magnitude."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "setup_physics_scene", {
            "gravity_magnitude": 1.62,
        }))
        assert r.success, r.error


# ── get_physics_summary ──


def test_get_physics_summary():
    """Returns a summary after applying APIs."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(exec_tool(state, "apply_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsCollisionAPI",
        }))

        r = asyncio.run(exec_tool(state, "get_physics_summary", {
            "prim_path": placed.data["prim_path"],
        }))
        assert r.success, r.error
        assert r.data["asset"] is not None


# ── list_joint_properties ──


def test_list_joint_properties_revolute():
    """Returns properties for PhysicsRevoluteJoint."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_joint_properties", {
            "joint_type": "PhysicsRevoluteJoint",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "physics:axis" in names


def test_list_joint_properties_fixed():
    """Returns properties for PhysicsFixedJoint."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_joint_properties", {
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

        asyncio.run(exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))

        r = asyncio.run(exec_tool(state, "create_joint", {
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

        asyncio.run(exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))

        asyncio.run(exec_tool(state, "create_joint", {
            "joint_type": "PhysicsFixedJoint",
            "name": "link",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
        }))

        r = asyncio.run(exec_tool(state, "list_joints", {"scope": "scene"}))
        assert r.success, r.error
        assert len(r.data["joints"]) >= 1


def test_remove_joint():
    """Removes a created joint."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        p1 = _place(tmp_path, state, "e")
        p2 = _place(tmp_path, state, "f")

        asyncio.run(exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))

        created = asyncio.run(exec_tool(state, "create_joint", {
            "joint_type": "PhysicsFixedJoint",
            "name": "temp",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
        }))

        r = asyncio.run(exec_tool(state, "remove_joint", {
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

        asyncio.run(exec_tool(state, "setup_physics_scene", {}))

        r = asyncio.run(exec_tool(
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
        asyncio.run(exec_tool(state, "setup_physics_scene", {}))

        asyncio.run(exec_tool(
            state, "create_or_update_collision_group", {"name": "Floor"},
        ))

        r = asyncio.run(exec_tool(state, "list_collision_groups"))
        assert r.success, r.error
        assert len(r.data["groups"]) >= 1


def test_remove_collision_group():
    """Removes a collision group."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        _place(tmp_path, state)
        asyncio.run(exec_tool(state, "setup_physics_scene", {}))

        asyncio.run(exec_tool(
            state, "create_or_update_collision_group", {"name": "Temp"},
        ))

        r = asyncio.run(exec_tool(
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
        asyncio.run(exec_tool(state, "setup_physics_scene", {}))

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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
        asyncio.run(exec_tool(state, "setup_physics_scene", {}))

        asyncio.run(exec_tool(state, "apply_physics_api", {
            "prim_path": placed.data["prim_path"],
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
        }))

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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
        asyncio.run(exec_tool(state, "setup_physics_scene", {}))

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(mesh_asset),
            "asset_name": "Panel", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        asyncio.run(exec_tool(state, "apply_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsMeshCollisionAPI",
        }))

        r = asyncio.run(exec_tool(state, "remove_physics_api", {
            "prim_path": mesh_path,
            "api_name": "PhysicsCollisionAPI",
        }))
        assert r.success, r.error


# ── list_physics_api_properties: more types ──


def test_list_physics_api_properties_mesh_collision():
    """Returns properties for PhysicsMeshCollisionAPI."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(
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
        r = asyncio.run(exec_tool(
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

        asyncio.run(exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))

        r = asyncio.run(exec_tool(state, "create_joint", {
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
        asyncio.run(exec_tool(state, "setup_physics_scene", {}))

        asyncio.run(exec_tool(
            state, "create_or_update_collision_group", {
                "name": "Env",
                "includes": [p1.data["prim_path"]],
            },
        ))

        r = asyncio.run(exec_tool(
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
        asyncio.run(exec_tool(state, "setup_physics_scene", {}))

        asyncio.run(exec_tool(state, "apply_physics_api", {
            "prim_path": placed.data["prim_path"],
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
        }))

        r = asyncio.run(exec_tool(state, "get_physics_summary", {
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
        r = asyncio.run(exec_tool(state, "setup_physics_scene", {
            "name": "SimScene",
        }))
        assert r.success, r.error
        assert "SimScene" in r.data["prim_path"]


# ── DriveAPI ──


def _joint_with_bodies(tmp_path, state):
    """Place two assets, apply RigidBody, create a RevoluteJoint."""
    p1 = _place(tmp_path, state, "arm")
    p2 = _place(tmp_path, state, "hand")
    asyncio.run(exec_tool(state, "setup_physics_scene", {}))
    for p in [p1, p2]:
        asyncio.run(exec_tool(state, "apply_physics_api", {
            "prim_path": p.data["prim_path"],
            "api_name": "PhysicsRigidBodyAPI",
            "scope": "scene",
        }))
    joint = asyncio.run(exec_tool(state, "create_joint", {
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
        r = asyncio.run(exec_tool(state, "list_physics_api_properties", {
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
        r = asyncio.run(exec_tool(state, "list_physics_api_properties", {
            "api_name": "PhysicsDriveAPI",
        }))
        assert not r.success


def test_apply_drive_api_on_revolute_joint():
    """Applies DriveAPI:angular on a RevoluteJoint."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        joint_path = _joint_with_bodies(tmp_path, state)

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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
        asyncio.run(exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))
        joint = asyncio.run(exec_tool(state, "create_joint", {
            "joint_type": "PhysicsSphericalJoint",
            "name": "ball_socket",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
        }))

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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

        asyncio.run(exec_tool(state, "apply_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsDriveAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))

        r = asyncio.run(exec_tool(state, "remove_physics_api", {
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
        r = asyncio.run(exec_tool(state, "list_physics_api_properties", {
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

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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
        asyncio.run(exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))
        joint = asyncio.run(exec_tool(state, "create_joint", {
            "joint_type": "PhysicsDistanceJoint",
            "name": "rope",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
        }))

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
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
        asyncio.run(exec_tool(state, "setup_physics_scene", {}))
        for p in [p1, p2]:
            asyncio.run(exec_tool(state, "apply_physics_api", {
                "prim_path": p.data["prim_path"],
                "api_name": "PhysicsRigidBodyAPI",
                "scope": "scene",
            }))
        joint = asyncio.run(exec_tool(state, "create_joint", {
            "joint_type": "PhysicsFixedJoint",
            "name": "weld",
            "body0": p1.data["prim_path"],
            "body1": p2.data["prim_path"],
            "scope": "scene",
        }))

        r = asyncio.run(exec_tool(state, "apply_physics_api", {
            "prim_path": joint.data["prim_path"],
            "api_name": "PhysicsLimitAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))
        assert not r.success


def test_remove_limit_api():
    """Removes an applied LimitAPI:angular."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        joint_path = _joint_with_bodies(tmp_path, state)

        asyncio.run(exec_tool(state, "apply_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsLimitAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))

        r = asyncio.run(exec_tool(state, "remove_physics_api", {
            "prim_path": joint_path,
            "api_name": "PhysicsLimitAPI",
            "instance_name": "angular",
            "scope": "scene",
        }))
        assert r.success, r.error
        assert r.data["removed"] is True
