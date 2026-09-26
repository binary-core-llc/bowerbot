# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for validation: validate_scene, package_scene."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Sdr, Usd, UsdGeom, UsdShade

from bowerbot.schemas import Severity
from bowerbot.utils.validation.compliance import run_usd_compliance_checker
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


# ── validate_scene ──


def test_validate_scene_passes():
    """A well-formed scene passes validation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "item")
        asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Item",
            "group": "Props",
            "translate_x": 1.0, "translate_y": 0.0, "translate_z": 1.0,
        }))

        r = asyncio.run(exec_tool(state, "validate_scene"))
        assert r.success, r.error
        assert r.data["is_valid"]


def test_validate_scene_after_create_material_has_no_errors():
    """BowerBot's own hybrid materials never fail validation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "item")
        placed = asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Item", "group": "Props",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        for name in ("red", "blue"):
            made = asyncio.run(exec_tool(state, "create_material", {
                "prim_path": placed.data["prim_path"], "material_name": name,
            }))
            assert made.success, made.error

        r = asyncio.run(exec_tool(state, "validate_scene"))
        assert r.success, r.error
        assert r.data["is_valid"], r.data["issues"]
        assert r.data["error_count"] == 0
        if "mtlx" not in Sdr.Registry().GetAllShaderNodeSourceTypes():
            notes = [i for i in r.data["issues"] if i["severity"] == "info"]
            assert len(notes) == 1
            assert "MaterialX shaders not checked" in notes[0]["message"]


def _stage_with_shaders(path: Path, *shader_ids: str) -> Path:
    stage = Usd.Stage.CreateNew(str(path))
    root = UsdGeom.Xform.Define(stage, "/Scene")
    stage.SetDefaultPrim(root.GetPrim())
    UsdShade.Material.Define(stage, "/Scene/Looks/look")
    for index, shader_id in enumerate(shader_ids):
        UsdShade.Shader.Define(stage, f"/Scene/Looks/look/s{index}").CreateIdAttr(shader_id)
    stage.GetPrimAtPath("/Scene").GetReferences().AddReference("./missing.usda")
    stage.Save()
    return path


def test_unknown_shader_id_is_still_an_error():
    """Only MaterialX ids are spared; any other id the registry lacks stays an error."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _stage_with_shaders(
            Path(tmp) / "scene.usda", "MadeUpShader", "ND_standard_surface_surfaceshader",
        )
        errors = [
            i.message for i in run_usd_compliance_checker(path) if i.severity is Severity.ERROR
        ]
        assert any("MadeUpShader" in message for message in errors)
        assert not any("ND_standard_surface_surfaceshader" in message for message in errors)


def test_compliance_issues_come_back_in_a_stable_order():
    """Errors first, then warnings, then notes; by prim path and message within each."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _stage_with_shaders(
            Path(tmp) / "scene.usda", "MadeUpShader", "ND_standard_surface_surfaceshader",
        )
        issues = run_usd_compliance_checker(path)
        order = [(list(Severity).index(i.severity), i.prim_path or "", i.message) for i in issues]
        assert len(issues) > 2
        assert order == sorted(order)
        assert issues == run_usd_compliance_checker(path)


def test_validate_scene_missing_stage():
    """Fails when no stage is open."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp))
        r = asyncio.run(exec_tool(state, "validate_scene"))
        assert not r.success


# ── package_scene ──


def test_package_scene_produces_usdz():
    """Package produces a .usdz file on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "item")
        asyncio.run(exec_tool(state, "place_asset", {
            "asset": asset.stem, "asset_name": "Item",
            "group": "Props",
            "translate_x": 1.0, "translate_y": 0.0, "translate_z": 1.0,
        }))

        r = asyncio.run(exec_tool(state, "package_scene"))
        assert r.success, r.error

        usdz_path = Path(r.data["usdz_path"])
        assert usdz_path.exists()
        assert usdz_path.suffix == ".usdz"
        assert usdz_path.stat().st_size > 0


def test_package_scene_missing_stage():
    """Fails when no stage is open."""
    with tempfile.TemporaryDirectory() as tmp:
        state, _ = make_state(Path(tmp))
        r = asyncio.run(exec_tool(state, "package_scene"))
        assert not r.success
