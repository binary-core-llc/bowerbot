# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for variant tools (17 tools)."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom

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


def _place(tmp_path, state, name="chair"):
    asset = _asset(tmp_path, name)
    r = asyncio.run(exec_tool(state, "place_asset", {
        "asset_file_path": str(asset), "asset_name": name.title(),
        "group": "Furniture",
        "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
    }))
    assert r.success, r.error
    return r


def _make_material(state, mesh_path, name="wood"):
    r = asyncio.run(exec_tool(state, "create_material", {
        "prim_path": mesh_path,
        "material_name": name,
    }))
    assert r.success, r.error
    return r


# ── add_asset_material_variant ──


def test_add_asset_material_variant():
    """Authors a material-binding variant on an asset."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        mat = _make_material(state, mesh_path, "oak")

        r = asyncio.run(exec_tool(state, "add_asset_material_variant", {
            "prim_path": placed.data["prim_path"],
            "variant_set": "material",
            "variant_name": "oak",
            "bindings": {
                mesh_path: mat.data["material"],
            },
        }))
        assert r.success, r.error


def test_add_asset_material_variant_two_variants():
    """Two material variants coexist in the same set."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        m1 = _make_material(state, mesh_path, "walnut")
        m2 = _make_material(state, mesh_path, "maple")

        for name, mat in [("walnut", m1), ("maple", m2)]:
            r = asyncio.run(exec_tool(
                state, "add_asset_material_variant", {
                    "prim_path": placed.data["prim_path"],
                    "variant_set": "material",
                    "variant_name": name,
                    "bindings": {mesh_path: mat.data["material"]},
                },
            ))
            assert r.success, r.error


# ── add_asset_configuration_variant ──


def test_add_asset_configuration_variant():
    """Authors a configuration variant toggling prim activation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        r = asyncio.run(exec_tool(
            state, "add_asset_configuration_variant", {
                "prim_path": placed.data["prim_path"],
                "variant_set": "config",
                "variant_name": "hidden",
                "activations": {mesh_path: False},
            },
        ))
        assert r.success, r.error


def test_add_asset_configuration_variant_two():
    """Two configuration variants (open/closed)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        for name, active in [("open", True), ("closed", False)]:
            r = asyncio.run(exec_tool(
                state, "add_asset_configuration_variant", {
                    "prim_path": placed.data["prim_path"],
                    "variant_set": "door_state",
                    "variant_name": name,
                    "activations": {mesh_path: active},
                },
            ))
            assert r.success, r.error


# ── add_asset_attribute_variant ──


def test_add_asset_attribute_variant():
    """Authors an attribute-override variant on an asset."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)

        asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": placed.data["prim_path"],
            "light_type": "SphereLight",
            "light_name": "Bulb",
            "attributes": {"inputs:intensity": 500.0},
        }))

        r = asyncio.run(exec_tool(
            state, "add_asset_attribute_variant", {
                "prim_path": placed.data["prim_path"],
                "variant_set": "mood",
                "variant_name": "warm",
                "overrides": {
                    "lgt/Bulb": {
                        "inputs:intensity": 1500.0,
                        "inputs:color": [1.0, 0.8, 0.6],
                    },
                },
            },
        ))
        assert r.success, r.error


# ── setup_asset_geometry_variants + add_asset_geometry_variant ──


def test_setup_and_add_geometry_variant():
    """Sets up geometry variants then adds another."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)

        asset_dir = project.assets_dir / "chair"
        low_geo = asset_dir / "geo_low.usda"
        low_stage = Usd.Stage.CreateNew(str(low_geo))
        UsdGeom.SetStageMetersPerUnit(low_stage, 1.0)
        root = low_stage.DefinePrim("/chair", "Xform")
        low_stage.SetDefaultPrim(root)
        UsdGeom.Cube.Define(low_stage, "/chair/Mesh")
        low_stage.Save()

        r = asyncio.run(exec_tool(
            state, "setup_asset_geometry_variants", {
                "prim_path": placed.data["prim_path"],
                "variant_set": "lod",
                "variants": {
                    "high": "./geo.usda",
                    "low": "./geo_low.usda",
                },
                "default_variant": "high",
            },
        ))
        assert r.success, r.error


# ── list_asset_geo_files ──


def test_list_asset_geo_files():
    """Lists alternate geometry files in an asset folder."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)

        alt = project.assets_dir / "chair" / "geo_low.usda"
        alt_stage = Usd.Stage.CreateNew(str(alt))
        UsdGeom.SetStageMetersPerUnit(alt_stage, 1.0)
        root = alt_stage.DefinePrim("/chair", "Xform")
        alt_stage.SetDefaultPrim(root)
        UsdGeom.Cube.Define(alt_stage, "/chair/Mesh")
        alt_stage.Save()

        r = asyncio.run(exec_tool(state, "list_asset_geo_files", {
            "prim_path": placed.data["prim_path"],
        }))
        assert r.success, r.error
        assert len(r.data["geo_files"]) >= 1


# ── select_asset_variant ──


def test_select_asset_variant():
    """Selects a variant on the asset root."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        m1 = _make_material(state, mesh_path, "a")
        m2 = _make_material(state, mesh_path, "b")
        for name, mat in [("a", m1), ("b", m2)]:
            asyncio.run(exec_tool(
                state, "add_asset_material_variant", {
                    "prim_path": placed.data["prim_path"],
                    "variant_set": "mtl",
                    "variant_name": name,
                    "bindings": {mesh_path: mat.data["material"]},
                },
            ))

        r = asyncio.run(exec_tool(state, "select_asset_variant", {
            "prim_path": placed.data["prim_path"],
            "variant_set": "mtl",
            "variant_name": "b",
        }))
        assert r.success, r.error


# ── select_asset_variant_for_instance ──


def test_select_asset_variant_for_instance():
    """Authors a per-instance variant selection in scene.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        mat = _make_material(state, mesh_path, "red")
        asyncio.run(exec_tool(
            state, "add_asset_material_variant", {
                "prim_path": placed.data["prim_path"],
                "variant_set": "color",
                "variant_name": "red",
                "bindings": {mesh_path: mat.data["material"]},
            },
        ))

        r = asyncio.run(exec_tool(
            state, "select_asset_variant_for_instance", {
                "prim_path": placed.data["prim_path"],
                "variant_set": "color",
                "variant_name": "red",
            },
        ))
        assert r.success, r.error


# ── remove_asset_variant ──


def test_remove_asset_variant():
    """Removes a single variant from an asset variant set."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        mat = _make_material(state, mesh_path, "temp")
        asyncio.run(exec_tool(
            state, "add_asset_material_variant", {
                "prim_path": placed.data["prim_path"],
                "variant_set": "mtl",
                "variant_name": "temp",
                "bindings": {mesh_path: mat.data["material"]},
            },
        ))

        r = asyncio.run(exec_tool(state, "remove_asset_variant", {
            "prim_path": placed.data["prim_path"],
            "variant_set": "mtl",
            "variant_name": "temp",
        }))
        assert r.success, r.error


# ── remove_asset_variant_set ──


def test_remove_asset_variant_set():
    """Removes an entire variant set from an asset."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        mat = _make_material(state, mesh_path, "x")
        asyncio.run(exec_tool(
            state, "add_asset_material_variant", {
                "prim_path": placed.data["prim_path"],
                "variant_set": "doomed",
                "variant_name": "x",
                "bindings": {mesh_path: mat.data["material"]},
            },
        ))

        r = asyncio.run(exec_tool(state, "remove_asset_variant_set", {
            "prim_path": placed.data["prim_path"],
            "variant_set": "doomed",
        }))
        assert r.success, r.error


# ── list_variants ──


def test_list_variants_empty():
    """Returns empty when no variants exist."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)

        r = asyncio.run(exec_tool(state, "list_variants", {
            "prim_path": placed.data["prim_path"],
        }))
        assert r.success, r.error


def test_list_variants_after_add():
    """Returns variant sets after authoring one."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"

        mat = _make_material(state, mesh_path, "v")
        asyncio.run(exec_tool(
            state, "add_asset_material_variant", {
                "prim_path": placed.data["prim_path"],
                "variant_set": "vis",
                "variant_name": "v",
                "bindings": {mesh_path: mat.data["material"]},
            },
        ))

        r = asyncio.run(exec_tool(state, "list_variants", {
            "prim_path": placed.data["prim_path"],
        }))
        assert r.success, r.error
        all_sets = set()
        for carrier in r.data["carriers"]:
            for vs in carrier["variant_sets"]:
                all_sets.add(vs["name"])
        assert "vis" in all_sets


# ── add_scene_lighting_attribute_variant ──


def test_add_scene_lighting_attribute_variant():
    """Authors a lighting mood variant at scene level."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, project = _setup(tmp)

        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
            "attributes": {"inputs:intensity": 1000.0},
        }))
        assert created.success, created.error
        light_path = created.data["prim_path"]

        r = asyncio.run(exec_tool(
            state, "add_scene_lighting_attribute_variant", {
                "clear_masking_overrides": True,
                "variant_set": "mood",
                "variant_name": "warm",
                "overrides": {
                    light_path: {
                        "inputs:intensity": 1500.0,
                        "inputs:color": [1.0, 0.85, 0.7],
                    },
                },
            },
        ))
        assert r.success, r.error


def test_add_scene_lighting_attribute_variant_two_moods():
    """Two lighting moods coexist."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)

        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
            "attributes": {"inputs:intensity": 1000.0},
        }))
        light_path = created.data["prim_path"]

        for name, intensity in [("warm", 1500.0), ("cool", 800.0)]:
            r = asyncio.run(exec_tool(
                state, "add_scene_lighting_attribute_variant", {
                "clear_masking_overrides": True,
                    "variant_set": "mood",
                    "variant_name": name,
                    "overrides": {
                        light_path: {"inputs:intensity": intensity},
                    },
                },
            ))
            assert r.success, r.error


# ── add_scene_lighting_selection_variant ──


def test_add_scene_lighting_selection_variant():
    """Authors a lighting selection variant toggling active flags."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)

        disk = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "DiskLight", "light_name": "Key_Disk",
        }))
        rect = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "RectLight", "light_name": "Key_Rect",
        }))

        r = asyncio.run(exec_tool(
            state, "add_scene_lighting_selection_variant", {
                "variant_set": "key_type",
                "variant_name": "disk",
                "activations": {
                    disk.data["prim_path"]: True,
                    rect.data["prim_path"]: False,
                },
            },
        ))
        assert r.success, r.error


# ── add_scene_model_selection_variant ──


def test_add_scene_model_selection_variant():
    """Authors a model-selection variant swapping asset refs."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        placed = _place(tmp_path, state, "chair")

        alt = _asset(tmp_path, "stool")
        r = asyncio.run(exec_tool(
            state, "add_scene_model_selection_variant", {
                "prim_path": placed.data["prim_path"],
                "variant_set": "seating",
                "variant_name": "stool",
                "asset_file_path": str(alt),
            },
        ))
        assert r.success, r.error


# ── select_scene_variant ──


def test_select_scene_variant():
    """Selects a scene-level variant on /Scene/Lighting."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)

        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
            "attributes": {"inputs:intensity": 1000.0},
        }))
        light_path = created.data["prim_path"]

        asyncio.run(exec_tool(
            state, "add_scene_lighting_attribute_variant", {
                "clear_masking_overrides": True,
                "variant_set": "mood",
                "variant_name": "bright",
                "overrides": {
                    light_path: {"inputs:intensity": 2000.0},
                },
            },
        ))

        r = asyncio.run(exec_tool(state, "select_scene_variant", {
            "prim_path": "/Scene/Lighting",
            "variant_set": "mood",
            "variant_name": "bright",
        }))
        assert r.success, r.error


# ── remove_scene_variant ──


def test_remove_scene_variant():
    """Removes a single variant from a scene-level variant set."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)

        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
            "attributes": {"inputs:intensity": 1000.0},
        }))
        light_path = created.data["prim_path"]

        asyncio.run(exec_tool(
            state, "add_scene_lighting_attribute_variant", {
                "clear_masking_overrides": True,
                "variant_set": "mood",
                "variant_name": "temp",
                "overrides": {
                    light_path: {"inputs:intensity": 500.0},
                },
            },
        ))

        r = asyncio.run(exec_tool(state, "remove_scene_variant", {
            "prim_path": "/Scene/Lighting",
            "variant_set": "mood",
            "variant_name": "temp",
        }))
        assert r.success, r.error


# ── remove_scene_variant_set ──


def test_remove_scene_variant_set():
    """Removes an entire scene-level variant set."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)

        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
            "attributes": {"inputs:intensity": 1000.0},
        }))
        light_path = created.data["prim_path"]

        asyncio.run(exec_tool(
            state, "add_scene_lighting_attribute_variant", {
                "clear_masking_overrides": True,
                "variant_set": "doomed",
                "variant_name": "x",
                "overrides": {
                    light_path: {"inputs:intensity": 1.0},
                },
            },
        ))

        r = asyncio.run(exec_tool(state, "remove_scene_variant_set", {
            "prim_path": "/Scene/Lighting",
            "variant_set": "doomed",
        }))
        assert r.success, r.error


# ── remove_scene_variant_set: model selection demotes ──


def test_remove_model_selection_set_demotes():
    """Removing a model-selection set demotes back to a direct ref."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state, "chair")

        alt = _asset(tmp_path, "stool")
        asyncio.run(exec_tool(
            state, "add_scene_model_selection_variant", {
                "prim_path": placed.data["prim_path"],
                "variant_set": "seating",
                "variant_name": "stool",
                "asset_file_path": str(alt),
            },
        ))

        r = asyncio.run(exec_tool(state, "remove_scene_variant_set", {
            "prim_path": placed.data["prim_path"],
            "variant_set": "seating",
        }))
        assert r.success, r.error

        stage = Usd.Stage.Open(str(project.scene_path))
        asset_child = stage.GetPrimAtPath(
            f"{placed.data['prim_path']}/asset",
        )
        assert asset_child.IsValid()


# ── error cases ──


def test_add_material_variant_missing_stage():
    """Fails when no stage is open."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp))
        r = asyncio.run(exec_tool(
            state, "add_asset_material_variant", {
                "prim_path": "/Scene/Furniture/X",
                "variant_set": "mtl",
                "variant_name": "x",
                "bindings": {},
            },
        ))
        assert not r.success


def test_add_config_variant_invalid_prim():
    """Fails for a nonexistent prim."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(
            state, "add_asset_configuration_variant", {
                "prim_path": "/Scene/Furniture/Ghost",
                "variant_set": "x",
                "variant_name": "y",
                "activations": {"/Scene/Furniture/Ghost/asset/Mesh": False},
            },
        ))
        assert not r.success


def test_select_scene_variant_unknown_set():
    """Fails when selecting from a nonexistent variant set."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)
        r = asyncio.run(exec_tool(state, "select_scene_variant", {
            "prim_path": "/Scene/Lighting",
            "variant_set": "nope",
            "variant_name": "x",
        }))
        assert not r.success
