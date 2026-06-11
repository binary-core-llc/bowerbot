# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for lights: list_light_type_properties, create, update, remove."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdLux

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
            "texture": str(hdri),
            "attributes": {"inputs:intensity": 1.0},
        }))
        assert r.success, r.error

        staged = project.path / "textures" / "studio.hdr"
        assert staged.exists()

        stage = Usd.Stage.Open(str(project.scene_path))
        prim = stage.GetPrimAtPath(r.data["prim_path"])
        assert prim.GetTypeName() == "DomeLight"


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
            "asset_file_path": str(asset), "asset_name": "Hero",
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
            "asset_file_path": str(asset), "asset_name": "Lamp",
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
            "asset_file_path": str(asset), "asset_name": "Lamp",
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
            "texture": str(hdri),
        }))
        assert r.success, r.error
        assert (project.path / "textures" / "sunset.hdr").exists()


def test_update_asset_rect_light_texture_into_asset():
    """An asset RectLight's texture update stages into the asset's maps/, not project textures/."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        asset = _asset(tmp_path, "panel")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset), "asset_name": "Panel",
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
            "texture": str(tex),
        }))
        assert r.success, r.error

        assert (project.path / "assets" / "panel" / "maps" / "screen.png").exists()
        assert not (project.path / "textures" / "screen.png").exists()

        stage = Usd.Stage.Open(str(project.path / "assets" / "panel" / "lgt.usda"))
        rect = next(p for p in stage.Traverse() if p.GetName() == "Screen")
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
            "asset_file_path": str(asset), "asset_name": "Lamp",
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
            "asset_file_path": str(asset), "asset_name": "Lamp",
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
            "asset_file_path": str(asset), "asset_name": "Lamp",
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
