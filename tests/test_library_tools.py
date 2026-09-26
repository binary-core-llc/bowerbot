# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for library: search_assets, list_assets."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom, UsdShade

from bowerbot.utils.library_utils import scan_library
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


# ── classification: material libraries vs models, read once ──


def _material_file(path: Path, *, with_geometry: bool) -> Path:
    stage = Usd.Stage.CreateNew(str(path))
    stage.SetDefaultPrim(stage.DefinePrim(f"/{path.stem}", "Xform"))
    UsdShade.Material.Define(stage, f"/{path.stem}/Looks/red")
    if with_geometry:
        UsdGeom.Cube.Define(stage, f"/{path.stem}/Body")
    stage.Save()
    return path


def test_a_model_with_its_own_material_is_geometry():
    """Only a file with materials and no geometry is a material library ('mtl')."""
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp)
        _material_file(lib / "paints.usda", with_geometry=False)
        _material_file(lib / "pillow.usda", with_geometry=True)
        found = {e["name"]: e["category"] for e in scan_library(lib)}
        assert found == {"paints": "mtl", "pillow": "geo"}


def test_classification_is_indexed_and_refreshed_when_a_file_changes(monkeypatch):
    """A rescan reads no unchanged file, re-reads a changed one, and never writes the library."""
    from bowerbot.utils import library_utils

    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp) / "lib"
        lib.mkdir()
        index = Path(tmp) / "home" / "library_index.json"
        _material_file(lib / "paints.usda", with_geometry=False)
        _material_file(lib / "pillow.usda", with_geometry=True)
        reads: list[str] = []
        classify = library_utils._classify_loose
        monkeypatch.setattr(
            library_utils, "_classify_loose",
            lambda path: reads.append(path.name) or classify(path),
        )

        scan_library(lib, index_file=index)
        assert sorted(reads) == ["paints.usda", "pillow.usda"]
        assert index.exists()
        reads.clear()
        scan_library(lib, index_file=index)
        assert reads == []

        _material_file(lib / "paints.usda", with_geometry=True)
        found = {e["name"]: e["category"] for e in scan_library(lib, index_file=index)}
        assert reads == ["paints.usda"]
        assert found["paints"] == "geo"
        assert sorted(p.name for p in lib.iterdir()) == ["paints.usda", "pillow.usda"]


def test_runtime_state_keeps_the_index_in_bowerbot_home():
    """Agent and MCP sessions index classifications in ~/.bowerbot, never in the library."""
    from bowerbot.config import Settings
    from bowerbot.schemas import ConfigPaths
    from bowerbot.state import SceneState

    state = SceneState.from_settings(Settings())
    assert state.library_index == ConfigPaths.LIBRARY_INDEX
    assert state.library_index.parent == ConfigPaths.HOME


def test_a_material_folder_is_listed_as_mtl():
    """A folder asset holding only materials is offered as a material ('mtl')."""
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp)
        (lib / "paints").mkdir()
        _material_file(lib / "paints" / "paints.usda", with_geometry=False)
        (lib / "sofa").mkdir()
        _material_file(lib / "sofa" / "sofa.usda", with_geometry=True)
        found = {e["name"]: e["category"] for e in scan_library(lib)}
        assert found == {"paints": "mtl", "sofa": "package"}
