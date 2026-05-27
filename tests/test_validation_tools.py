# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for validation: validate_scene, package_scene."""

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


# ── validate_scene ──


def test_validate_scene_passes():
    """A well-formed scene passes validation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state, _ = _setup(tmp)
        asset = _asset(tmp_path, "item")
        asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": str(asset), "asset_name": "Item",
            "group": "Props",
            "translate_x": 1.0, "translate_y": 0.0, "translate_z": 1.0,
        }))

        r = asyncio.run(exec_tool(state, "validate_scene"))
        assert r.success, r.error
        assert r.data["is_valid"]


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
            "asset_file_path": str(asset), "asset_name": "Item",
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
