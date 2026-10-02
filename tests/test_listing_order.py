# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Answers built from folder listings don't depend on the disk's listing order.

The operating system lists a folder's files in no fixed order, and the order
differs between machines. Each test makes the same call twice, once with the
disk's order and once with it reversed, and expects the same answer.
"""

import asyncio
import os
from collections.abc import Callable, Iterator
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom

from bowerbot.utils import authoring
from tests import _helpers


class _ReversedScan:
    """An ``os.scandir`` result in reverse order, usable as a context manager."""

    def __init__(self, entries: list[os.DirEntry[str]]) -> None:
        self._entries: Iterator[os.DirEntry[str]] = reversed(entries)

    def __iter__(self) -> Iterator[os.DirEntry[str]]:
        return self._entries

    def __next__(self) -> os.DirEntry[str]:
        return next(self._entries)

    def __enter__(self) -> "_ReversedScan":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def close(self) -> None:
        return None


def _both_orders(monkeypatch: pytest.MonkeyPatch, call: Callable[[], Any]) -> tuple[Any, Any]:
    """*call*'s answer with the disk's listing order, then with it reversed."""
    disk_order = call()
    listdir, scandir = os.listdir, os.scandir

    def reversed_scandir(path: Any = ".") -> _ReversedScan:
        with scandir(path) as entries:
            return _ReversedScan(list(entries))

    with monkeypatch.context() as patch:
        patch.setattr(os, "listdir", lambda path=".": list(reversed(listdir(path))))
        patch.setattr(os, "scandir", reversed_scandir)
        reversed_order = call()
    return disk_order, reversed_order


def _asset(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{path.stem}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, f"/{path.stem}/Mesh")
    stage.Save()
    return path


def _names(result: Any) -> list[str]:
    assert result.success, result.error
    entries = result.data["results"] if isinstance(result.data, dict) else result.data
    return [entry["name"] for entry in entries]


def test_asset_search_and_listing(tmp_path, monkeypatch):
    """Packages, then loose files, each alphabetical; a limit keeps the first ones."""
    library = tmp_path / "library"
    for rel in ("b_pkg/b_pkg.usda", "a_pkg/a_pkg.usda", "zeta.usda", "materials/mid.usda",
                "alpha.usda"):
        _asset(library / rel)
    state, _ = _helpers.make_state(tmp_path)
    state.library_dir = library

    def listing() -> list[str]:
        return _names(asyncio.run(_helpers.exec_tool(state, "list_assets", {})))

    def limited() -> list[str]:
        return _names(asyncio.run(_helpers.exec_tool(state, "list_assets", {"limit": 3})))

    def search() -> list[str]:
        return _names(asyncio.run(_helpers.exec_tool(state, "search_assets", {"query": "a"})))

    for call in (listing, limited, search):
        disk_order, reversed_order = _both_orders(monkeypatch, call)
        assert disk_order == reversed_order
    assert listing() == ["a_pkg", "b_pkg", "alpha", "mid", "zeta"]
    assert limited() == ["a_pkg", "b_pkg", "alpha"]


def test_texture_search_and_listing(tmp_path, monkeypatch):
    """Textures come back in path order."""
    library = tmp_path / "library"
    for rel in ("hdri/sky_b.hdr", "hdri/sky_a.hdr", "wood.png", "maps/stone.png"):
        (library / rel).parent.mkdir(parents=True, exist_ok=True)
        (library / rel).write_bytes(b"x")
    state, _ = _helpers.make_state(tmp_path)
    state.library_dir = library

    def listing() -> list[str]:
        return _names(asyncio.run(_helpers.exec_tool(state, "list_textures", {})))

    def search() -> list[str]:
        return _names(asyncio.run(_helpers.exec_tool(state, "search_textures", {"query": "sky"})))

    for call in (listing, search):
        disk_order, reversed_order = _both_orders(monkeypatch, call)
        assert disk_order == reversed_order
    assert search() == ["sky_a", "sky_b"]


def test_same_named_textures_are_never_guessed(tmp_path, monkeypatch):
    """With two library textures of one name, a bare name is refused; a path picks its file."""
    library = tmp_path / "library"
    for folder in ("b", "a"):
        (library / folder).mkdir(parents=True)
        (library / folder / "wood.png").write_bytes(folder.encode())
    projects = count()

    def refusal() -> str:
        project = tmp_path / f"project_{next(projects)}"
        project.mkdir()
        with pytest.raises(ValueError, match="names 2 files in the library") as refused:
            authoring.textures.stage_asset_value("wood.png", project, library)
        return str(refused.value)

    disk_order, reversed_order = _both_orders(monkeypatch, refusal)
    assert disk_order == reversed_order
    assert "(a/wood.png, b/wood.png)" in disk_order

    project = tmp_path / "project_by_path"
    project.mkdir()
    for folder in ("b", "a"):
        rel = authoring.textures.stage_asset_value(f"{folder}/wood.png", project, library)
        assert (project / rel).read_bytes() == folder.encode()
    assert sorted(p.name for p in (project / "textures").iterdir()) == ["wood.png", "wood_2.png"]


def test_reference_scans(tmp_path, monkeypatch):
    """Files referencing an asset folder or a texture are listed in path order."""
    for name in ("b", "a"):
        stage = Usd.Stage.CreateNew(str(tmp_path / f"{name}.usda"))
        stage.DefinePrim("/Crate").GetReferences().AddReference("./assets/crate/crate.usda")
        light = stage.DefinePrim("/Sky", "DomeLight")
        light.CreateAttribute("inputs:texture:file", Sdf.ValueTypeNames.Asset).Set(
            "./textures/sky.hdr",
        )
        stage.Save()

    def asset_refs() -> list[str]:
        return authoring.asset_folder.find_files_using(tmp_path, tmp_path / "assets" / "crate")

    def texture_refs() -> list[str]:
        return authoring.asset_folder.find_files_using(
            tmp_path, tmp_path / "textures" / "sky.hdr",
        )

    for call in (asset_refs, texture_refs):
        disk_order, reversed_order = _both_orders(monkeypatch, call)
        assert disk_order == reversed_order == ["a.usda", "b.usda"]


def test_list_materials(tmp_path, monkeypatch):
    """Materials are listed asset folder by asset folder, alphabetically."""
    state, _ = _helpers.make_state(tmp_path)
    asyncio.run(_helpers.exec_tool(state, "create_stage", {"filename": "test"}))
    for name in ("table", "chair"):
        placed = asyncio.run(_helpers.exec_tool(state, "place_asset", {
            "asset_file_path": str(_asset(tmp_path / "sources" / f"{name}.usda")),
            "asset_name": name.title(), "group": "Furniture",
            "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert placed.success, placed.error
        made = asyncio.run(_helpers.exec_tool(state, "create_material", {
            "prim_path": f"{placed.data['prim_path']}/asset/Mesh",
            "material_name": f"{name}_paint",
        }))
        assert made.success, made.error

    def folders() -> list[str]:
        result = asyncio.run(_helpers.exec_tool(state, "list_materials"))
        assert result.success, result.error
        return [material["asset_folder"] for material in result.data["materials"]]

    disk_order, reversed_order = _both_orders(monkeypatch, folders)
    assert disk_order == reversed_order == ["chair", "table"]
