# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for lights: list_light_type_properties, create, update, remove."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdLux

from tests._helpers import exec_tool, library_state, make_state


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


def _setup(tmp):
    tmp_path = Path(tmp)
    state, project = make_state(tmp_path)
    asyncio.run(exec_tool(state, "create_stage", {"filename": "test"}))
    return tmp_path, state, project


# ── list_light_type_properties ──


def test_list_light_type_properties_sphere():
    """Returns inputs for SphereLight including radius."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_light_type_properties", {
            "light_type": "SphereLight",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "inputs:intensity" in names
        assert "inputs:radius" in names
        assert "inputs:color" in names


def test_list_light_type_properties_distant():
    """Returns inputs for DistantLight including angle."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_light_type_properties", {
            "light_type": "DistantLight",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "inputs:angle" in names


def test_list_light_type_properties_dome():
    """Returns inputs for DomeLight including texture:file."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_light_type_properties", {
            "light_type": "DomeLight",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "inputs:texture:file" in names


def test_list_light_type_properties_rect():
    """Returns inputs for RectLight including width and height."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_light_type_properties", {
            "light_type": "RectLight",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "inputs:width" in names
        assert "inputs:height" in names


def test_list_light_type_properties_cylinder():
    """Returns inputs for CylinderLight including length."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_light_type_properties", {
            "light_type": "CylinderLight",
        }))
        assert r.success, r.error
        names = {p["name"] for p in r.data["properties"]}
        assert "inputs:length" in names
        assert "inputs:radius" in names


def test_list_light_type_properties_invalid():
    """Returns error for unknown light type."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "list_light_type_properties", {
            "light_type": "FakeLight",
        }))
        assert not r.success


# ── create_light — scene-level ──


def test_create_sphere_light():
    """Creates a SphereLight with attributes at scene level."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight",
            "light_name": "Key",
            "translate_x": 3.0, "translate_y": 2.0, "translate_z": 1.0,
            "attributes": {"inputs:intensity": 800.0, "inputs:radius": 0.1},
        }))
        assert r.success, r.error
        assert r.data["light_type"] == "SphereLight"

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.IsValid()
        assert prim.GetTypeName() == "SphereLight"
        assert UsdLux.SphereLight(prim).GetIntensityAttr().Get() == 800.0
        assert abs(UsdLux.SphereLight(prim).GetRadiusAttr().Get() - 0.1) < 1e-6


def test_create_distant_light():
    """Creates a DistantLight with angle and rotation."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "DistantLight",
            "light_name": "Sun",
            "rotate_x": -45.0,
            "attributes": {"inputs:intensity": 500.0, "inputs:angle": 0.53},
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.GetTypeName() == "DistantLight"
        assert abs(UsdLux.DistantLight(prim).GetAngleAttr().Get() - 0.53) < 1e-5


def test_create_dome_light_with_texture():
    """Creates a DomeLight and stages the HDRI into project/textures/."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        hdri = tmp_path / "studio.hdr"
        hdri.write_bytes(b"fake-hdri")

        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "DomeLight",
            "light_name": "Env",
            "texture": hdri.name,
            "attributes": {"inputs:intensity": 1.0},
        }))
        assert r.success, r.error

        staged = project.path / "textures" / "studio.hdr"
        assert staged.exists()

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.GetTypeName() == "DomeLight"


def test_remove_dome_light_names_the_texture_to_delete():
    """remove_light lists the texture it left unused; delete_project_texture takes that path."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        hdri = tmp_path / "studio.hdr"
        hdri.write_bytes(b"fake-hdri")
        made = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "DomeLight", "light_name": "Env", "texture": hdri.name,
        }))
        assert made.success, made.error

        removed = asyncio.run(exec_tool(state, "remove_light", {
            "prim_path": made.data["prim_path"],
        }))
        assert removed.success, removed.error
        assert removed.data["unused_files"] == ["textures/studio.hdr"]

        deleted = asyncio.run(exec_tool(state, "delete_project_texture", {
            "file_name": removed.data["unused_files"][0],
        }))
        assert deleted.success, deleted.error
        assert not (project.path / "textures" / "studio.hdr").exists()
        assert hdri.exists()


def test_create_rect_light():
    """Creates a RectLight with width and height."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "RectLight",
            "light_name": "Panel",
            "attributes": {
                "inputs:intensity": 1000.0,
                "inputs:width": 1.5,
                "inputs:height": 0.8,
            },
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        rect = UsdLux.RectLight(prim)
        assert abs(rect.GetWidthAttr().Get() - 1.5) < 1e-6
        assert abs(rect.GetHeightAttr().Get() - 0.8) < 1e-6


def test_create_disk_light():
    """Creates a DiskLight with radius."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "DiskLight",
            "light_name": "Fill",
            "attributes": {"inputs:radius": 0.3},
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.GetTypeName() == "DiskLight"


def test_create_cylinder_light():
    """Creates a CylinderLight with radius and length."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "CylinderLight",
            "light_name": "Tube",
            "attributes": {"inputs:radius": 0.02, "inputs:length": 1.2},
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.GetTypeName() == "CylinderLight"


def test_create_light_unique_naming():
    """Second light with same name gets a _02 suffix."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r1 = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Bulb",
        }))
        r2 = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Bulb",
        }))
        assert r1.success and r2.success
        assert r1.data["prim_path"] != r2.data["prim_path"]
        assert "_02" in r2.data["prim_path"]


def test_create_light_with_light_linking():
    """Light linking authors a UsdLux light:link collection."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "hero")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Hero",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        hero_path = placed.data["prim_path"]

        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "RectLight", "light_name": "Rim",
            "light_link_includes": [hero_path],
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        link = UsdLux.LightAPI(prim).GetLightLinkCollectionAPI()
        targets = link.GetIncludesRel().GetTargets()
        assert Sdf.Path(hero_path) in targets


# ── create_light — asset-level ──


def test_create_asset_light():
    """Creates a light inside an asset's lgt.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "lamp")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Lamp",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))

        r = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": placed.data["prim_path"],
            "light_type": "SphereLight",
            "light_name": "Bulb",
            "attributes": {"inputs:intensity": 500.0},
        }))
        assert r.success, r.error
        assert r.data["asset_folder"] == "lamp"

        lgt_path = project.path / "assets" / "lamp" / "lgt.usda"
        assert lgt_path.exists()


def test_create_asset_scene_only_light_refused():
    """DomeLight and DistantLight are scene environment lights, not asset-level."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "lamp")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Lamp",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        for light_type in ("DomeLight", "DistantLight"):
            r = asyncio.run(exec_tool(state, "create_light", {
                "asset_prim_path": placed.data["prim_path"],
                "light_type": light_type,
                "light_name": "Env",
            }))
            assert not r.success, light_type
            assert "scene-level" in r.error.lower()


# ── create_light — error cases ──


def test_create_light_missing_stage():
    """Fails when no stage has been created."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp))
        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "X",
        }))
        assert not r.success


# ── update_light ──


def test_update_light_position():
    """Updates a light's translate."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
            "translate_x": 1.0, "translate_y": 1.0, "translate_z": 1.0,
        }))
        prim_path = created.data["prim_path"]

        r = asyncio.run(exec_tool(state, "update_light", {
            "prim_path": prim_path,
            "translate_x": 5.0, "translate_y": 3.0, "translate_z": 2.0,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(prim_path)
        xf = UsdGeom.Xformable(prim)
        t = xf.GetLocalTransformation().ExtractTranslation()
        assert abs(t[0] - 5.0) < 0.01


def test_update_light_rotation():
    """Updates a light's rotation."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "DiskLight", "light_name": "Down",
        }))

        r = asyncio.run(exec_tool(state, "update_light", {
            "prim_path": created.data["prim_path"],
            "rotate_x": -90.0,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(created.data["prim_path"])
        assert tuple(prim.GetAttribute("xformOp:rotateXYZ").Get()) == (-90.0, 0.0, 0.0)
        assert list(UsdGeom.Xformable(prim).GetXformOpOrderAttr().Get()) == [
            "xformOp:translate", "xformOp:rotateXYZ",
        ]


def test_update_light_keeps_omitted_axes():
    """Axes left out of an update keep their values, for translate and rotate."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        path = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "RectLight", "light_name": "Panel",
            "translate_x": 1.0, "translate_y": 2.0, "translate_z": 3.0,
            "rotate_x": 10.0, "rotate_y": 20.0, "rotate_z": 30.0,
        })).data["prim_path"]

        for update in ({"translate_x": 5.0}, {"rotate_y": 45.0}):
            r = asyncio.run(exec_tool(state, "update_light", {"prim_path": path, **update}))
            assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(path)
        assert tuple(prim.GetAttribute("xformOp:translate").Get()) == (5.0, 2.0, 3.0)
        assert tuple(prim.GetAttribute("xformOp:rotateXYZ").Get()) == (10.0, 45.0, 30.0)


def _world_position(scene_path: Path, prim_path: str) -> tuple[float, ...]:
    stage = Usd.Stage.Open(str(scene_path))
    matrix = UsdGeom.XformCache().GetLocalToWorldTransform(stage.GetPrimAtPath(prim_path))
    return tuple(round(v, 4) for v in matrix.ExtractTranslation())


def test_update_asset_light_absolute_uses_the_placement_frame():
    """An absolute update lands at the world position asked for, on a moved
    and rotated placement, and omitted axes keep their world value."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "lamp")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Lamp", "group": "Props",
            "translate_x": 10.0, "translate_y": 0.0, "translate_z": 0.0, "rotate_y": 90.0,
        }))
        light = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": placed.data["prim_path"],
            "light_type": "SphereLight", "light_name": "Bulb", "position_mode": "absolute",
            "translate_x": 10.0, "translate_y": 3.0, "translate_z": 1.0,
        })).data["prim_path"]
        assert _world_position(project.scene_path, light) == (10.0, 3.0, 1.0)

        r = asyncio.run(exec_tool(state, "update_light", {
            "prim_path": light, "position_mode": "absolute",
            "translate_x": 10.0, "translate_y": 5.0, "translate_z": 1.0,
        }))
        assert r.success, r.error
        assert _world_position(project.scene_path, light) == (10.0, 5.0, 1.0)

        r = asyncio.run(exec_tool(state, "update_light", {
            "prim_path": light, "position_mode": "absolute", "translate_y": 6.0,
        }))
        assert r.success, r.error
        assert _world_position(project.scene_path, light) == (10.0, 6.0, 1.0)


def test_update_asset_light_offset_keeps_omitted_axes():
    """Moving an asset light needs position_mode; a bounds_offset update moves only its axes."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "lamp")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Lamp", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        light = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": placed.data["prim_path"],
            "light_type": "SphereLight", "light_name": "Bulb",
            "translate_x": 0.1, "translate_y": 0.5, "translate_z": -0.2,
        })).data["prim_path"]
        before = _world_position(project.scene_path, light)

        r = asyncio.run(exec_tool(state, "update_light", {
            "prim_path": light, "translate_x": 0.3, "rotate_z": 15.0,
        }))
        assert not r.success
        assert "position_mode" in r.error
        assert _world_position(project.scene_path, light) == before

        r = asyncio.run(exec_tool(state, "update_light", {
            "prim_path": light, "position_mode": "bounds_offset",
            "translate_x": 0.3, "rotate_z": 15.0,
        }))
        assert r.success, r.error
        after = _world_position(project.scene_path, light)
        assert after == (0.3, before[1], before[2])
        lgt = Usd.Stage.Open(str(project.path / "assets" / "lamp" / "lgt.usda"))
        bulb = lgt.GetPrimAtPath("/lamp/lgt/Bulb")
        assert tuple(bulb.GetAttribute("xformOp:rotateXYZ").Get()) == (0.0, 0.0, 15.0)


def test_update_light_texture():
    """Stages an HDRI on update and sets inputs:texture:file."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "DomeLight", "light_name": "Env",
            "attributes": {"inputs:intensity": 1.0},
        }))

        hdri = tmp_path / "sunset.hdr"
        hdri.write_bytes(b"fake-hdri")

        r = asyncio.run(exec_tool(state, "update_light", {
            "prim_path": created.data["prim_path"],
            "texture": hdri.name,
        }))
        assert r.success, r.error
        assert (project.path / "textures" / "sunset.hdr").exists()


def test_update_asset_rect_light_texture_into_asset():
    """An asset RectLight's texture update stages into the asset's maps/, not project textures/."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "panel")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Panel",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        created = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": placed.data["prim_path"],
            "light_type": "RectLight",
            "light_name": "Screen",
        }))
        assert created.success, created.error

        tex = tmp_path / "screen.png"
        tex.write_bytes(b"fake-png")
        r = asyncio.run(exec_tool(state, "update_light", {
            "prim_path": created.data["prim_path"],
            "texture": tex.name,
        }))
        assert r.success, r.error

        assert (project.path / "assets" / "panel" / "maps" / "screen.png").exists()
        assert not (project.path / "textures" / "screen.png").exists()

        stage = Usd.Stage.Open(str(project.path / "assets" / "panel" / "lgt.usda"))
        rect = next(p for p in stage.TraverseAll() if p.GetName() == "Screen")
        tex_val = rect.GetAttribute("inputs:texture:file").Get()
        path = tex_val.path if hasattr(tex_val, "path") else str(tex_val)
        assert "maps/screen.png" in path


def test_update_light_nonexistent_prim():
    """Fails for a prim that does not exist."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "update_light", {
            "prim_path": "/Scene/Lighting/NoSuchLight",
            "translate_x": 1.0,
        }))
        assert not r.success


# ── remove_light ──


def test_remove_scene_light():
    """Removes a scene-level light."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Temp",
        }))
        prim_path = created.data["prim_path"]

        r = asyncio.run(exec_tool(state, "remove_light", {
            "prim_path": prim_path,
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        assert not stage.GetPrimAtPath(prim_path).IsValid()


def test_remove_asset_light():
    """Removes an asset-level light from lgt.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "lamp")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Lamp",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))

        created = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": placed.data["prim_path"],
            "light_type": "SphereLight", "light_name": "Bulb",
        }))
        assert created.success, created.error

        r = asyncio.run(exec_tool(state, "remove_light", {
            "prim_path": created.data["prim_path"],
        }))
        assert r.success, r.error
        assert r.data["asset_folder"] == "lamp"


def test_remove_scene_light_drops_targets_at_it():
    """A dome light's portals rel at the removed light is dropped."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        dome = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "DomeLight", "light_name": "Sky",
        })).data["prim_path"]
        window = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "RectLight", "light_name": "Window",
        })).data["prim_path"]
        stage = Usd.Stage.Open(str(project.scene_path))
        stage.GetPrimAtPath(dome).CreateRelationship("portals").SetTargets([window])
        stage.Save()

        r = asyncio.run(exec_tool(state, "remove_light", {"prim_path": window}))
        assert r.success, r.error
        assert r.data["scrubbed_dangling_refs"]["rels_touched"]

        stage = Usd.Stage.Open(str(project.scene_path))
        assert stage.GetPrimAtPath(dome).GetRelationship("portals").GetTargets() == []


def test_remove_asset_light_drops_targets_in_every_placement():
    """Removing an asset light drops the targets at it under each placement only."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "lamp")
        placements = [
            asyncio.run(exec_tool(state, "place_asset", {
                "asset": asset.stem, "asset_name": "Lamp",
                "group": "Props",
                "translate_x": x, "translate_y": 0.0, "translate_z": 0.0,
            })).data["prim_path"]
            for x in (0.0, 3.0)
        ]
        bulb = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": placements[0],
            "light_type": "SphereLight", "light_name": "Bulb",
        })).data["prim_path"]
        bulbs = [bulb, bulb.replace(placements[0], placements[1])]
        stage = Usd.Stage.Open(str(project.scene_path))
        stage.DefinePrim("/Scene/Rig", "Scope").CreateRelationship("watch").SetTargets(
            [*bulbs, placements[0]],
        )
        stage.Save()

        r = asyncio.run(exec_tool(state, "remove_light", {"prim_path": bulb}))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        watch = stage.GetPrimAtPath("/Scene/Rig").GetRelationship("watch")
        assert [str(t) for t in watch.GetTargets()] == [placements[0]]


def test_remove_light_refuses_light_from_asset_files():
    """A light that ships in the asset's own files is refused, not falsely reported removed."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "lamp")
        asset_stage = Usd.Stage.Open(str(asset))
        UsdLux.SphereLight.Define(asset_stage, "/lamp/Bulb")
        asset_stage.Save()
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Lamp",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        bulb = f"{placed.data['prim_path']}/asset/Bulb"

        r = asyncio.run(exec_tool(state, "remove_light", {"prim_path": bulb}))
        assert not r.success
        assert "asset's own files" in r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        assert stage.GetPrimAtPath(bulb).IsValid()


def test_remove_light_refuses_anything_but_a_light():
    """A camera or the Lighting group is refused (remove_prim removes them)."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        light = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
        })).data["prim_path"]
        camera = asyncio.run(exec_tool(state, "create_camera", {
            "camera_name": "Cam",
        })).data["prim_path"]

        for path in (camera, "/Scene/Lighting"):
            r = asyncio.run(exec_tool(state, "remove_light", {"prim_path": path}))
            assert not r.success, path
            assert "remove_prim" in r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        assert stage.GetPrimAtPath(camera).IsValid()
        assert stage.GetPrimAtPath(light).IsValid()


def test_create_light_cleans_the_name():
    """A name with spaces or a leading digit becomes a valid prim name."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        for name, expected in (("Key Light", "Key_Light"), ("3 Point Fill", "_3_Point_Fill")):
            r = asyncio.run(exec_tool(state, "create_light", {
                "light_type": "SphereLight", "light_name": name,
            }))
            assert r.success, r.error
            assert r.data["prim_path"] == f"/Scene/Lighting/{expected}"
        stage = Usd.Stage.Open(str(project.scene_path))
        assert stage.GetPrimAtPath("/Scene/Lighting/_3_Point_Fill").IsValid()


def test_create_light_refuses_unknown_attributes_and_creates_nothing():
    """An input the light type does not declare is refused, not silently dropped."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        before = project.scene_path.read_text()
        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
            "attributes": {"inputs:intensity": 500.0, "inputs:nope": 1},
        }))
        assert not r.success
        assert "inputs:nope" in r.error and "list_light_type_properties" in r.error
        assert project.scene_path.read_text() == before

        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
            "attributes": {"inputs:intensity": 500.0, "treatAsPoint": True},
        }))
        assert r.success, r.error


def test_scene_light_link_targets_must_exist():
    """A light link to a prim that does not exist is refused and nothing is created."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)
        before = project.scene_path.read_text()
        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Rim",
            "light_link_includes": ["/Scene/Nope"],
        }))
        assert not r.success
        assert "/Scene/Nope" in r.error
        assert project.scene_path.read_text() == before


def test_asset_light_links_prims_inside_its_own_asset():
    """An asset light's links point inside its asset (so they compose); others are refused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _asset(tmp_path, "lamp")
        placed = []
        for x in (0.0, 3.0):
            r = asyncio.run(exec_tool(state, "place_asset", {
                "asset": "lamp", "asset_name": "Lamp", "group": "Props",
                "translate_x": x, "translate_y": 0.0, "translate_z": 0.0,
            }))
            placed.append(r.data["prim_path"])
        shade = f"{placed[0]}/asset/Mesh"

        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Bulb",
            "asset_prim_path": placed[0], "light_link_includes": [shade],
        }))
        assert r.success, r.error
        stage = Usd.Stage.Open(str(project.scene_path))
        light = stage.GetPrimAtPath(r.data["prim_path"])
        links = UsdLux.LightAPI(light).GetLightLinkCollectionAPI()
        assert [str(t) for t in links.GetIncludesRel().GetTargets()] == [shade]

        r = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Spill",
            "asset_prim_path": placed[0], "light_link_includes": [f"{placed[1]}/asset/Mesh"],
        }))
        assert not r.success
        assert "outside" in r.error


def test_remove_light_nonexistent_prim():
    """Fails for a prim that does not exist."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "remove_light", {
            "prim_path": "/Scene/Lighting/Ghost",
        }))
        assert not r.success


# ── asset-light spatial input coercion ──


def _cm_asset(directory: Path, name: str) -> Path:
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, f"/{name}/Mesh").GetSizeAttr().Set(1.0)
    stage.Save()
    return path


def test_create_asset_light_spatial_string_coerced():
    """A JSON-string spatial input on a non-meter asset is coerced and scaled."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _cm_asset(tmp_path, "cmlamp")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Lamp",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert placed.success, placed.error

        r = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": placed.data["prim_path"],
            "light_type": "SphereLight", "light_name": "Bulb",
            "attributes": {"inputs:radius": "0.05"},
        }))
        assert r.success, r.error

        lgt = Usd.Stage.Open(str(project.assets_dir / "cmlamp" / "lgt.usda"))
        radius = lgt.GetPrimAtPath("/cmlamp/lgt/Bulb").GetAttribute("inputs:radius").Get()
        assert abs(radius - 5.0) < 1e-4


def test_create_asset_light_spatial_garbage_refused():
    """A non-numeric spatial input fails with a curated error, not a crash."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _cm_asset(tmp_path, "cmlamp2")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Lamp",
            "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert placed.success, placed.error

        r = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": placed.data["prim_path"],
            "light_type": "SphereLight", "light_name": "Bulb",
            "attributes": {"inputs:radius": "big"},
        }))
        assert not r.success
        assert "spatial light input" in r.error


def test_asset_light_offset_uses_asset_units():
    """An asset light 0.1 m above a 1 m loose-file asset sits 0.1 m above its top."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": _asset(tmp_path, "block").stem, "asset_name": "Block",
            "group": "Props", "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        light = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": placed.data["prim_path"], "light_type": "SphereLight",
            "light_name": "Glow", "translate_y": 0.1,
        }))
        assert light.success, light.error

        stage = Usd.Stage.Open(str(project.scene_path))
        world = UsdGeom.Xformable(stage.GetPrimAtPath(light.data["prim_path"]))
        y = world.ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()[1]
        assert abs(y - 0.6) < 1e-6


def test_textures_that_share_a_name_do_not_overwrite_each_other():
    """Two different files named screen.png each keep their own copy; the same file is reused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        _asset(tmp_path, "panel")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": "panel", "asset_name": "Panel", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        })).data["prim_path"]
        for folder, data in (("a", b"A"), ("b", b"B")):
            (tmp_path / "tex" / folder).mkdir(parents=True)
            (tmp_path / "tex" / folder / "screen.png").write_bytes(b"\x89PNG" + data * 32)

        paths = []
        for name, texture in (("S1", "tex/a/screen.png"), ("S2", "tex/b/screen.png"),
                              ("S3", "tex/a/screen.png")):
            r = asyncio.run(exec_tool(state, "create_light", {
                "asset_prim_path": placed, "light_type": "RectLight", "light_name": name,
                "texture": texture,
            }))
            assert r.success, r.error
            stage = Usd.Stage.Open(str(project.scene_path))
            light = stage.GetPrimAtPath(r.data["prim_path"])
            paths.append(light.GetAttribute("inputs:texture:file").Get().path)
        assert paths == ["./maps/screen.png", "./maps/screen_2.png", "./maps/screen.png"]


# ── placement paths and leftover textures ──


def _run(state, tool, **params):
    return asyncio.run(exec_tool(state, tool, params))


def test_an_asset_light_takes_the_placement_or_its_asset_child_never_a_part():
    """A part path is refused before anything is written; /asset means the placement."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        lamp = _run(state, "place_asset", asset="lamp", asset_name="Lamp", group="Props",
                    translate_x=5.0, translate_y=0.0, translate_z=0.0).data["prim_path"]
        light = {"light_type": "SphereLight", "light_name": "Bulb", "position_mode": "absolute",
                 "translate_x": 5.1, "translate_y": 0.5, "translate_z": 0.0}

        part = _run(state, "create_light", asset_prim_path=f"{lamp}/asset/Shade", **light)
        assert not part.success
        assert f"pass the placement itself ({lamp})" in part.error
        assert not (state.require_project().assets_dir / "lamp" / "lgt.usda").exists()

        made = _run(state, "create_light", asset_prim_path=f"{lamp}/asset", **light)
        assert made.success, made.error
        assert made.data["position"] == {"x": 5.1, "y": 0.5, "z": 0.0}


def test_removing_an_asset_rect_light_lists_its_texture_for_deletion():
    """The copied texture stays until the user deletes it; the library keeps its original."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        project = state.require_project()
        lamp = _run(state, "place_asset", asset="lamp", asset_name="Lamp", group="Props",
                    translate_x=0.0, translate_y=0.0, translate_z=0.0).data["prim_path"]
        screen = _run(state, "create_light", light_type="RectLight", light_name="Screen",
                      asset_prim_path=lamp, texture="textures/glow.png")
        assert screen.success, screen.error
        maps = project.assets_dir / "lamp" / "maps"

        removed = _run(state, "remove_light", prim_path=screen.data["prim_path"])
        assert removed.success, removed.error
        assert removed.data["unused_files"] == ["assets/lamp/maps/glow.png"]

        deleted = _run(state, "delete_project_texture", file_name="assets/lamp/maps/glow.png")
        assert deleted.success, deleted.error
        assert not (maps / "glow.png").exists()
        assert (maps / "shade.png").exists()
        assert (state.library_dir / "textures" / "glow.png").exists()
