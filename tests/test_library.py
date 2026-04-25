# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for library_service and the search_assets / list_assets tools."""

import asyncio
import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom, UsdShade

from bowerbot.config import SceneDefaults
from bowerbot.services import asset_service
from bowerbot.state import SceneState
from bowerbot.tools import library_tools
from bowerbot.utils import library_utils


# ── Helpers ──


def _write_geo(path: Path, prim_name: str = "geo") -> None:
    """Write a minimal geometry layer at *path* with a default prim."""
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{prim_name}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, f"/{prim_name}/Mesh")
    stage.Save()


def _write_material(path: Path, name: str = "wood") -> None:
    """Write a minimal material layer at *path*."""
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    scope = stage.DefinePrim("/mtl", "Scope")
    stage.SetDefaultPrim(scope)
    UsdShade.Material.Define(stage, f"/mtl/{name}")
    stage.Save()


def _write_root_with_sublayer(path: Path, sublayer: str) -> None:
    """Write a USD root file that sublayers *sublayer* (relative)."""
    path.write_text(
        (
            "#usda 1.0\n"
            "(\n"
            f'    defaultPrim = "root"\n'
            "    metersPerUnit = 1.0\n"
            '    upAxis = "Y"\n'
            f"    subLayers = [@{sublayer}@]\n"
            ")\n"
            'def Xform "root" { }\n'
        ),
        encoding="utf-8",
    )


# ── list_assets / search_assets ──


def test_list_assets_finds_packages_and_loose_files():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        # Canonical package
        (library / "table").mkdir()
        _write_geo(library / "table" / "table.usda", "table")
        # Loose geometry
        _write_geo(library / "chair.usda", "chair")
        # Loose material
        _write_material(library / "wood_mtl.usda")

        results = library_utils.scan_library(library)
        names = sorted(r["name"] for r in results)
        assert names == ["chair", "table", "wood_mtl"]

        by_name = {r["name"]: r["category"] for r in results}
        assert by_name["table"] == "package"
        assert by_name["chair"] == "geo"
        assert by_name["wood_mtl"] == "mtl"


def test_search_assets_matches_folder_or_root_stem():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        (library / "wall").mkdir()
        _write_geo(library / "wall" / "geo.usda", "wall")
        _write_root_with_sublayer(library / "wall" / "root.usda", "./geo.usda")

        # Folder name match
        by_folder = library_utils.scan_library(library, query="wall")
        assert [r["name"] for r in by_folder] == ["wall"]

        # Root stem match (non-canonical filename)
        by_stem = library_utils.scan_library(library, query="root")
        assert [r["name"] for r in by_stem] == ["wall"]


def test_list_assets_filters_by_category():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        _write_geo(library / "thing.usda", "thing")
        _write_material(library / "wood.usda")

        geo_only = library_utils.scan_library(library, category="geo")
        assert [r["name"] for r in geo_only] == ["thing"]

        mtl_only = library_utils.scan_library(library, category="mtl")
        assert [r["name"] for r in mtl_only] == ["wood"]


# ── find_package_for ──


def test_find_package_for_canonical_package():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        (library / "table").mkdir()
        root = library / "table" / "table.usda"
        _write_geo(root, "table")

        assert library_utils.find_package_for(root, library) == library / "table"


def test_find_package_for_non_canonical_root():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        (library / "wall").mkdir()
        _write_geo(library / "wall" / "geo.usda", "wall")
        root = library / "wall" / "root.usda"
        _write_root_with_sublayer(root, "./geo.usda")

        assert library_utils.find_package_for(root, library) == library / "wall"


def test_find_package_for_loose_file_at_library_root_returns_none():
    """The library root is never a package — files there are loose."""
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        loose = library / "table.usda"
        _write_geo(loose, "table")

        assert library_utils.find_package_for(loose, library) is None


def test_find_package_for_outside_library_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp) / "library"
        library.mkdir()
        elsewhere = Path(tmp) / "elsewhere"
        elsewhere.mkdir()
        outside = elsewhere / "thing.usda"
        _write_geo(outside, "thing")

        assert library_utils.find_package_for(outside, library) is None


# ── prepare_asset routing (the bug we're fixing) ──


def test_prepare_asset_loose_at_library_root_does_not_intake_library():
    """Single-USD library root must NOT be intaken as a package (PR #78 bug)."""
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp) / "library"
        library.mkdir()
        # Library has exactly one top-level USD; this is the trigger case.
        _write_geo(library / "table.usda", "table")
        # Plus a subfolder with more content (would amplify the bug).
        (library / "stuff").mkdir()
        _write_geo(library / "stuff" / "extra.usda", "extra")

        project_assets = Path(tmp) / "project_assets"
        project_assets.mkdir()

        report = asset_service.prepare_asset(
            library / "table.usda", project_assets,
            library_dir=library,
        )

        # Wrapped as a fresh ASWF folder, not the entire library.
        assert report.scene_ref_path == "assets/table/table.usda"
        assert (project_assets / "table" / "table.usda").exists()
        # The unrelated subfolder must NOT have been pulled in.
        assert not (project_assets / "library").exists()
        assert not (project_assets / "stuff").exists()


def test_prepare_asset_inside_package_intakes_the_folder():
    """Files inside a real package folder still trigger full intake."""
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp) / "library"
        library.mkdir()
        (library / "wall").mkdir()
        _write_geo(library / "wall" / "geo.usda", "wall")
        _write_root_with_sublayer(library / "wall" / "root.usda", "./geo.usda")

        project_assets = Path(tmp) / "project_assets"
        project_assets.mkdir()

        report = asset_service.prepare_asset(
            library / "wall" / "root.usda", project_assets,
            library_dir=library,
        )

        # Folder intake + canonicalization happened.
        assert report.was_renamed
        assert report.root_canonical_name == "wall.usda"
        assert (project_assets / "wall" / "wall.usda").exists()
        assert (project_assets / "wall" / "geo.usda").exists()


# ── library_tools wiring ──


def test_tool_search_uses_library_dir():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        _write_geo(library / "chair.usda", "chair")
        _write_geo(library / "table.usda", "table")
        state = SceneState(scene_defaults=SceneDefaults(), library_dir=library)

        result = asyncio.run(asyncio.to_thread(
            library_tools.search_assets, state, {"query": "chair"},
        ))
        assert result.success
        assert len(result.data) == 1
        assert result.data[0]["name"] == "chair"


def test_tool_returns_error_when_library_dir_unset():
    state = SceneState(scene_defaults=SceneDefaults(), library_dir=None)
    result = asyncio.run(asyncio.to_thread(
        library_tools.list_assets, state, {},
    ))
    assert not result.success
    assert "asset library" in result.error.lower()
