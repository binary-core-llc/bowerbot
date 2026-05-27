# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for library: search_assets, list_assets."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom

from tests._helpers import exec_tool, make_state


def _seed_library(lib_dir: Path) -> None:
    for name in ("table", "chair", "lamp"):
        path = lib_dir / f"{name}.usda"
        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        root = stage.DefinePrim(f"/{name}", "Xform")
        stage.SetDefaultPrim(root)
        UsdGeom.Cube.Define(stage, f"/{name}/Mesh")
        stage.Save()


# ── search_assets ──


def test_search_assets_finds_match():
    """Finds assets matching a keyword."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lib_dir = tmp_path / "library"
        lib_dir.mkdir()
        _seed_library(lib_dir)

        state, _ = make_state(tmp_path)
        state.library_dir = lib_dir

        r = asyncio.run(exec_tool(state, "search_assets", {
            "query": "table",
        }))
        assert r.success, r.error
        assert len(r.data["results"]) >= 1


def test_search_assets_no_match():
    """Returns empty when nothing matches."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lib_dir = tmp_path / "library"
        lib_dir.mkdir()
        _seed_library(lib_dir)

        state, _ = make_state(tmp_path)
        state.library_dir = lib_dir

        r = asyncio.run(exec_tool(state, "search_assets", {
            "query": "spaceship",
        }))
        assert r.success, r.error
        assert len(r.data["results"]) == 0


# ── list_assets ──


def test_list_assets():
    """Lists all assets in the library."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lib_dir = tmp_path / "library"
        lib_dir.mkdir()
        _seed_library(lib_dir)

        state, _ = make_state(tmp_path)
        state.library_dir = lib_dir

        r = asyncio.run(exec_tool(state, "list_assets"))
        assert r.success, r.error
        assert len(r.data["results"]) >= 3


def test_list_assets_empty_library():
    """Returns empty for an empty library."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lib_dir = tmp_path / "library"
        lib_dir.mkdir()

        state, _ = make_state(tmp_path)
        state.library_dir = lib_dir

        r = asyncio.run(exec_tool(state, "list_assets"))
        assert r.success, r.error
        assert len(r.data["results"]) == 0
