# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for variant tools (17 tools)."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom

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


def _place(tmp_path, state, name="chair"):
    asset = _asset(tmp_path, name)
    r = asyncio.run(exec_tool(state, "place_asset", {
        "asset": asset.stem, "asset_name": name.title(),
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


def test_variant_set_and_variant_names_are_cleaned():
    """Set and variant names are cleaned on create, and the same spelling finds
    them again on select."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        mesh_path = f"{placed.data['prim_path']}/asset/Mesh"
        mat = _make_material(state, mesh_path, "oak")

        r = asyncio.run(exec_tool(state, "add_asset_material_variant", {
            "prim_path": placed.data["prim_path"],
            "variant_set": "Wood Finish", "variant_name": "light oak",
            "bindings": {mesh_path: mat.data["material"]},
        }))
        assert r.success, r.error

        r = asyncio.run(exec_tool(state, "select_asset_variant", {
            "prim_path": placed.data["prim_path"],
            "variant_set": "Wood Finish", "variant_name": "light oak",
        }))
        assert r.success, r.error
        stage = Usd.Stage.Open(str(project.scene_path))
        variant_set = stage.GetPrimAtPath(f"{placed.data['prim_path']}/asset").GetVariantSet(
            "Wood_Finish",
        )
        assert variant_set.GetVariantNames() == ["light_oak"]
        assert variant_set.GetVariantSelection() == "light_oak"


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


def test_add_asset_attribute_variant_unknown_attribute():
    """Rejects an unknown attribute name on an asset prim with a helpful hint."""
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
                    "lgt/Bulb": {"inputs:intensit": 1500.0},
                },
            },
        ))
        assert not r.success
        assert "do not exist" in r.error
        assert "inputs:intensity" in r.error


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


def test_asset_variants_refuse_what_does_not_exist():
    """A material variant needs an existing prim and material; selecting needs an
    existing set and variant. Refusals leave the asset untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state).data["prim_path"]
        mesh_path = f"{placed}/asset/Mesh"
        oak = _make_material(state, mesh_path, "oak").data["material"]
        asset_dir = project.assets_dir / "chair"

        for bindings in ({mesh_path: "/mtl/nope"}, {f"{placed}/asset/Nope": oak}):
            r = asyncio.run(exec_tool(state, "add_asset_material_variant", {
                "prim_path": placed, "variant_set": "look", "variant_name": "ghost",
                "bindings": bindings,
            }))
            assert not r.success, bindings
        assert not (asset_dir / "variants.usda").exists()

        r = asyncio.run(exec_tool(state, "add_asset_material_variant", {
            "prim_path": placed, "variant_set": "look", "variant_name": "oak",
            "bindings": {mesh_path: oak},
        }))
        assert r.success, r.error
        root_before = (asset_dir / "chair.usda").read_text()
        for set_name, variant in (("look", "nope"), ("nope", "oak")):
            r = asyncio.run(exec_tool(state, "select_asset_variant", {
                "prim_path": placed, "variant_set": set_name, "variant_name": variant,
            }))
            assert not r.success, (set_name, variant)
        assert (asset_dir / "chair.usda").read_text() == root_before


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


def test_add_scene_lighting_attribute_variant_unknown_attribute():
    """Rejects an unknown attribute name on a scene light with a helpful hint."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state, _ = _setup(tmp)

        created = asyncio.run(exec_tool(state, "create_light", {
            "light_type": "SphereLight", "light_name": "Key",
            "attributes": {"inputs:intensity": 1000.0},
        }))
        light_path = created.data["prim_path"]

        r = asyncio.run(exec_tool(
            state, "add_scene_lighting_attribute_variant", {
                "clear_masking_overrides": True,
                "variant_set": "mood",
                "variant_name": "warm",
                "overrides": {
                    light_path: {"inputs:intensit": 1500.0},
                },
            },
        ))
        assert not r.success
        assert "do not exist" in r.error
        assert "inputs:intensity" in r.error


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
                "asset": alt.stem,
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
                "asset": alt.stem,
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


def test_side_layer_after_lod_setup_keeps_payloads_in_variants():
    """Adding a material after the LOD setup never puts the geo payload back on the root."""
    from pxr import Sdf

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state)
        prim_path = placed.data["prim_path"]
        asset_dir = project.path / "assets" / "chair"
        (asset_dir / "geo_low.usda").write_text((asset_dir / "geo.usda").read_text())
        r = asyncio.run(exec_tool(state, "setup_asset_geometry_variants", {
            "prim_path": prim_path, "variant_set": "lod",
            "variants": {"high": "./geo.usda", "low": "./geo_low.usda"},
            "default_variant": "high",
        }))
        assert r.success, r.error

        _make_material(state, f"{prim_path}/asset/Mesh")

        root = Sdf.Layer.FindOrOpen(str(asset_dir / "chair.usda"))
        root.Reload()
        payloads = root.GetPrimAtPath("/chair").payloadList
        assert not payloads.GetAddedOrExplicitItems()


# ── clean variant authoring ──


def test_texture_attribute_variant_stages_into_the_asset():
    """A texture in an asset attribute variant lands in the asset's maps/ and resolves."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state).data["prim_path"]
        (tmp_path / "hdri").mkdir()
        (tmp_path / "hdri" / "glow.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        light = asyncio.run(exec_tool(state, "create_light", {
            "asset_prim_path": placed, "light_type": "RectLight", "light_name": "Screen",
        })).data["prim_path"]

        r = asyncio.run(exec_tool(state, "add_asset_attribute_variant", {
            "prim_path": placed, "variant_set": "screen", "variant_name": "on",
            "overrides": {light: {"inputs:texture:file": "hdri/glow.png"}},
        }))
        assert r.success, r.error
        asset_dir = project.assets_dir / "chair"
        assert (asset_dir / "maps" / "glow.png").is_file()
        text = (asset_dir / "variants.usda").read_text()
        assert "@./maps/glow.png@" in text
        assert not (project.path / "textures" / "glow.png").exists()


def test_material_variant_binding_is_a_schema_relationship():
    """The variant's material:binding is authored like UsdShade does, not as a custom rel."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state).data["prim_path"]
        mesh = f"{placed}/asset/Mesh"
        oak = _make_material(state, mesh, "oak").data["material"]
        r = asyncio.run(exec_tool(state, "add_asset_material_variant", {
            "prim_path": placed, "variant_set": "look", "variant_name": "oak",
            "bindings": {mesh: oak},
        }))
        assert r.success, r.error
        text = (project.assets_dir / "chair" / "variants.usda").read_text()
        assert "rel material:binding" in text
        assert "custom rel material:binding" not in text


def test_removing_the_default_lod_selects_another():
    """Removing the selected LOD selects a remaining one (so the asset keeps its geometry)
    and names the payload file nothing uses any more."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, project = _setup(tmp)
        placed = _place(tmp_path, state).data["prim_path"]
        asset_dir = project.path / "assets" / "chair"
        (asset_dir / "geo_low.usda").write_text((asset_dir / "geo.usda").read_text())
        asyncio.run(exec_tool(state, "setup_asset_geometry_variants", {
            "prim_path": placed, "variant_set": "lod",
            "variants": {"high": "./geo.usda", "low": "./geo_low.usda"},
            "default_variant": "high",
        }))

        r = asyncio.run(exec_tool(state, "remove_asset_variant", {
            "prim_path": placed, "variant_set": "lod", "variant_name": "high",
        }))
        assert r.success, r.error
        assert r.data["default_variant"] == "low"
        assert r.data["unused_files"] == ["assets/chair/geo.usda"]
        stage = Usd.Stage.Open(str(project.scene_path))
        gprims = [p for p in Usd.PrimRange(stage.GetPrimAtPath(placed)) if p.IsA(UsdGeom.Gprim)]
        assert gprims


# ── placement paths, material twins and leftover textures ──


def _run(state, tool, **params):
    return asyncio.run(exec_tool(state, tool, params))


def test_model_selection_takes_a_placement_s_asset_child():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        table = _run(state, "place_asset", asset="table", asset_name="Table", group="Furniture",
                     translate_x=0.0, translate_y=0.0, translate_z=0.0).data["prim_path"]

        r = _run(state, "add_scene_model_selection_variant", prim_path=f"{table}/asset",
                 variant_set="model", variant_name="chair", asset="chair")
        assert r.success, r.error
        assert "model" in state.require_stage().GetPrimAtPath(table).GetVariantSets().GetNames()


def test_an_attribute_variant_on_a_bowerbot_shader_carries_its_twin():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        table = _run(state, "place_asset", asset="table", asset_name="Table", group="Furniture",
                     translate_x=0.0, translate_y=0.0, translate_z=0.0).data["prim_path"]
        _run(state, "create_material", prim_path=f"{table}/asset/Top", material_name="paint",
             base_color_r=1.0, base_color_g=0.0, base_color_b=0.0)

        r = _run(state, "add_asset_attribute_variant", prim_path=table, variant_set="paint",
                 variant_name="blue", set_as_default=True, overrides={
                     f"{table}/asset/mtl/paint/standard_surface": {
                         "inputs:base_color": [0.0, 0.0, 1.0],
                     },
                 })
        assert r.success, r.error
        assert r.data["overrides"]["/table/mtl/paint/preview_surface"] == {
            "inputs:diffuseColor": [0.0, 0.0, 1.0],
        }
        preview = state.require_stage().GetPrimAtPath(f"{table}/asset/mtl/paint/preview_surface")
        assert tuple(preview.GetAttribute("inputs:diffuseColor").Get()) == (0.0, 0.0, 1.0)


def test_removing_a_textured_attribute_variant_lists_its_texture():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        lamp = _run(state, "place_asset", asset="lamp", asset_name="Lamp", group="Props",
                    translate_x=0.0, translate_y=0.0, translate_z=0.0).data["prim_path"]
        _run(state, "create_light", light_type="RectLight", light_name="Screen",
             asset_prim_path=lamp, texture="textures/glow.png")
        added = _run(state, "add_asset_attribute_variant", prim_path=lamp, variant_set="screen",
                     variant_name="sky",
                     overrides={"lgt/Screen": {"inputs:texture:file": "hdri/sky.png"}})
        assert added.success, added.error

        removed = _run(state, "remove_asset_variant", prim_path=lamp, variant_set="screen",
                       variant_name="sky")
        assert removed.success, removed.error
        assert removed.data["unused_files"] == ["assets/lamp/maps/sky.png"]


# ── LODs from the library ──


def _box_file(path: Path, name: str, size, *, up: str = "Y", mpu: float = 1.0,
              parts=("Base", "Shade")) -> None:
    from pxr import Gf
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, mpu)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z if up == "Z" else UsdGeom.Tokens.y)
    stage.SetDefaultPrim(stage.DefinePrim(f"/{name}", "Xform"))
    for part in parts:
        cube = UsdGeom.Cube.Define(stage, f"/{name}/{part}")
        cube.GetSizeAttr().Set(1.0)
        cube.AddScaleOp().Set(Gf.Vec3f(*size))
    stage.Save()


def _lamp(state):
    lamp = _run(state, "place_asset", asset="lamp", asset_name="Lamp", group="Props",
                translate_x=0.0, translate_y=0.0, translate_z=0.0).data["prim_path"]
    return lamp, state.require_project().assets_dir / "lamp"


def _size(state, prim_path):
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    bound = cache.ComputeWorldBound(state.require_stage().GetPrimAtPath(prim_path))
    return tuple(round(v, 4) for v in bound.ComputeAlignedRange().GetSize())


def test_an_lod_from_the_library_folder_is_copied_into_the_asset():
    """The asset's spare library file is listed, then copied in next to geo.usda when used."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        lamp, folder = _lamp(state)
        assert not (folder / "geo_low.usda").exists()

        listed = _run(state, "list_asset_geo_files", prim_path=lamp)
        assert listed.data["library_files"] == ["lamp/geo_low.usda"]

        r = _run(state, "setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
                 variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"},
                 default_variant="high")
        assert r.success, r.error
        assert r.data["variants"] == {"high": "./geo.usda", "low": "./geo_low.usda"}
        assert (folder / "geo_low.usda").exists()
        assert (state.library_dir / "lamp" / "geo_low.usda").exists()


def test_a_loose_lod_in_other_units_needs_conform_units():
    """Refused without the flag (nothing copied); converted with it, to the asset's size."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _box_file(state.library_dir / "lamp_small.usda", "lamp_small", (40, 40, 60),
                  up="Z", mpu=0.01)
        lamp, folder = _lamp(state)
        before = sorted(p.name for p in folder.rglob("*"))
        setup = {"prim_path": lamp, "variant_set": "lod", "default_variant": "high",
                 "variants": {"high": "./geo.usda", "small": "lamp_small"}}

        refused = _run(state, "setup_asset_geometry_variants", **setup)
        assert not refused.success
        assert "conform_units=true" in refused.error
        assert sorted(p.name for p in folder.rglob("*")) == before

        r = _run(state, "setup_asset_geometry_variants", **setup, conform_units=True)
        assert r.success, r.error
        high = _size(state, lamp)
        _run(state, "select_asset_variant_for_instance", prim_path=lamp, variant_set="lod",
             variant_name="small")
        assert _size(state, lamp) == high
        copy = Usd.Stage.Open(str(folder / "geo_small.usda"))
        assert UsdGeom.GetStageMetersPerUnit(copy) == 1.0
        assert UsdGeom.GetStageUpAxis(copy) == UsdGeom.Tokens.y
        assert "conform" not in (state.library_dir / "lamp_small.usda").read_text()


def test_a_converted_lod_keeps_each_parts_place():
    """Each part of a Z-up centimeter LOD lands where a plain Z-up to Y-up conversion puts it."""
    from pxr import Gf, Sdf
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        source = state.library_dir / "lamp_cm.usda"
        stage = Usd.Stage.CreateNew(str(source))
        UsdGeom.SetStageMetersPerUnit(stage, 0.01)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        stage.SetDefaultPrim(stage.DefinePrim("/lamp_cm", "Xform"))
        base = UsdGeom.Cube.Define(stage, "/lamp_cm/Base")  # off-center, turned, uneven
        base.AddTranslateOp().Set(Gf.Vec3d(10.0, 0.0, 20.0))
        base.AddRotateZOp().Set(30.0)
        base.AddScaleOp().Set(Gf.Vec3f(40.0, 20.0, 10.0))
        shade = UsdGeom.Cube.Define(stage, "/lamp_cm/Shade")
        shade.AddTranslateOp().Set(Gf.Vec3d(0.0, 5.0, 60.0))
        shade.AddScaleOp().Set(Gf.Vec3f(40.0, 40.0, 30.0))
        stage.Save()

        # Truth: the file referenced under a Y-up meter conversion (x, y, z) -> (x, z, -y).
        truth_stage = Usd.Stage.CreateInMemory()
        holder = UsdGeom.Xform.Define(truth_stage, "/t")
        holder.AddRotateXOp().Set(-90.0)
        holder.AddScaleOp().Set(Gf.Vec3f(0.01))
        holder.GetPrim().GetReferences().AddReference(str(source))
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default"])

        def part_bounds(stage, root):
            return {
                name: tuple(round(v, 4) for r in (cache.ComputeWorldBound(
                    stage.GetPrimAtPath(f"{root}/{name}")).ComputeAlignedRange(),)
                    for v in (*r.GetMin(), *r.GetMax()))
                for name in ("Base", "Shade")
            }

        truth = part_bounds(truth_stage, "/t")
        lamp, folder = _lamp(state)
        r = _run(state, "setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
                 variants={"high": "./geo.usda", "cm": "lamp_cm"}, default_variant="cm",
                 conform_units=True)
        assert r.success, r.error
        cache.Clear()
        assert part_bounds(state.require_stage(), f"{lamp}/asset") == truth

        copy = Sdf.Layer.FindOrOpen(str(folder / "geo_cm.usda"))
        assert not [n for n in copy.GetPrimAtPath("/lamp_cm").properties.keys()
                    if n.startswith("xformOp")]
        assert list(copy.GetPrimAtPath("/lamp_cm/Base").attributes["xformOpOrder"].default) == [
            "xformOp:transform:conform", "xformOp:translate", "xformOp:rotateZ", "xformOp:scale",
        ]


def test_an_lod_that_cannot_be_used_leaves_nothing_behind():
    """A whole asset, or a file with other part names, is refused and the folder is unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _box_file(state.library_dir / "lamp_odd.usda", "lamp_odd", (0.4, 0.6, 0.4),
                  parts=("Stand",))
        lamp, folder = _lamp(state)
        _run(state, "setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
             variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"},
             default_variant="high")
        before = {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()}

        for source, hint in (("woodmat", "whole asset"), ("lamp_odd", "divergent")):
            r = _run(state, "add_asset_geometry_variant", prim_path=lamp, variant_set="lod",
                     variant_name="alt", payloads={lamp: source})
            assert not r.success, source
            assert hint in r.error, r.error
            assert {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before


def test_removing_an_lod_set_keeps_the_selected_lod():
    """With 'low' selected, removing the set leaves the asset showing 'low', not geo.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        lamp, folder = _lamp(state)
        _run(state, "setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
             variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"},
             default_variant="low")

        r = _run(state, "remove_asset_variant_set", prim_path=lamp, variant_set="lod")
        assert r.success, r.error
        assert r.data["demoted_to_direct_payload"] == "./geo_low.usda"
        root = Sdf.Layer.FindOrOpen(str(folder / "lamp.usda")).GetPrimAtPath("/lamp")
        assert [p.assetPath for p in root.payloadList.GetAddedOrExplicitItems()] == [
            "./geo_low.usda",
        ]
        assert r.data["unused_files"] == ["assets/lamp/geo.usda"]


def test_an_lod_set_left_with_one_variant_is_suspect():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        lamp, _ = _lamp(state)
        _run(state, "setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
             variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"},
             default_variant="high")

        r = _run(state, "remove_asset_variant", prim_path=lamp, variant_set="lod",
                 variant_name="low")
        assert r.success, r.error
        assert r.data["unused_files"] == ["assets/lamp/geo_low.usda"]
        assert [(s["variant_set"], s["scope"]) for s in r.data["suspect_variant_sets"]] == [
            ("lod", "asset"),
        ]


def test_an_lod_never_overwrites_a_file_the_asset_has():
    """The LOD's own maps/shade.png lands beside the lamp's, which stays as it was."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        library = state.library_dir
        _box_file(library / "lamp_textured.usda", "lamp_textured", (0.4, 0.6, 0.4))
        (library / "maps").mkdir()
        (library / "maps" / "shade.png").write_bytes(b"\x89PNG\r\n\x1a\nother shade")
        layer = Sdf.Layer.FindOrOpen(str(library / "lamp_textured.usda"))
        shade = layer.GetPrimAtPath("/lamp_textured/Shade")
        Sdf.AttributeSpec(shade, "userProperties:map", Sdf.ValueTypeNames.Asset).default = (
            "./maps/shade.png"
        )
        layer.Save()
        lamp, folder = _lamp(state)
        own = (folder / "maps" / "shade.png").read_bytes()

        r = _run(state, "setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
                 variants={"high": "./geo.usda", "tex": "lamp_textured"},
                 default_variant="high")
        assert r.success, r.error
        assert (folder / "maps" / "shade.png").read_bytes() == own
        copy = Sdf.Layer.FindOrOpen(str(folder / "geo_tex.usda"))
        path = copy.GetAttributeAtPath("/lamp_textured/Shade.userProperties:map").default.path
        assert path == "./maps/shade_2.png"
        assert (folder / "maps" / "shade_2.png").read_bytes().endswith(b"other shade")


def test_delete_project_file_removes_a_leftover_lod():
    """Once no variant loads it, the LOD layer can go; a layer in use or a root cannot."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        lamp, folder = _lamp(state)
        _run(state, "setup_asset_geometry_variants", prim_path=lamp, variant_set="lod",
             variants={"high": "./geo.usda", "low": "lamp/geo_low.usda"},
             default_variant="high")

        in_use = _run(state, "delete_project_file", file_name="assets/lamp/geo_low.usda")
        assert not in_use.success
        assert "variants.usda" in in_use.error
        root = _run(state, "delete_project_file", file_name="assets/lamp/lamp.usda")
        assert not root.success
        assert "delete_project_asset" in root.error

        _run(state, "remove_asset_variant", prim_path=lamp, variant_set="lod",
             variant_name="low")
        deleted = _run(state, "delete_project_file", file_name="assets/lamp/geo_low.usda")
        assert deleted.success, deleted.error
        assert not (folder / "geo_low.usda").exists()
        assert (folder / "geo.usda").exists()
