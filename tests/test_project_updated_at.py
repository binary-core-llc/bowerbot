# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The project's ``updated_at`` moves when a tool changes a project file, and only then."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade

from tests import _helpers


def _table(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(path))
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, "/table").GetPrim())
    UsdGeom.Cube.Define(stage, "/table/Top")
    stage.Save()
    return path


def _oak(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(path))
    stage.SetDefaultPrim(UsdShade.Material.Define(stage, "/oak").GetPrim())
    stage.Save()
    return path


def test_updated_at_follows_what_changes_on_disk(tmp_path):
    """Tools that write move the date; tools that read, or are refused, leave it alone."""
    state, project = _helpers.make_state(tmp_path)
    library = tmp_path / "library"
    state.library_dir = library
    table, oak = _table(library / "table.usda"), _oak(library / "materials" / "oak.usda")

    def date() -> str:
        return json.loads(project.meta_path.read_text(encoding="utf-8"))["updated_at"]

    def call(tool: str, params: dict, *, moves: bool, succeeds: bool = True) -> dict:
        before = date()
        result = asyncio.run(_helpers.exec_tool(state, tool, params))
        assert result.success is succeeds, f"{tool}: {result.error}"
        assert (date() != before) is moves, f"{tool}: updated_at {'kept' if moves else 'moved'}"
        return result.data or {}

    # The helper builds the state by hand, so the first call sets the starting point.
    asyncio.run(_helpers.exec_tool(state, "create_stage", {"filename": "test"}))
    placed = call("place_asset", {
        "asset_file_path": str(table), "asset_name": "Table", "group": "Furniture",
        "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
    }, moves=True)["prim_path"]
    top = f"{placed}/asset/Top"

    call("list_scene", {}, moves=False)
    call("list_project_assets", {}, moves=False)
    call(
        "move_asset", {"prim_path": "/Scene/Nope", "translate_x": 1.0},
        moves=False, succeeds=False,
    )

    call("bind_material", {"prim_path": top, "material_file": str(oak)}, moves=True)
    call("create_material", {"prim_path": top, "material_name": "paint"}, moves=True)
    call("add_asset_configuration_variant", {
        "prim_path": placed, "variant_set": "top", "variant_name": "off",
        "activations": {top: False},
    }, moves=True)
    call("add_asset_configuration_variant", {
        "prim_path": placed, "variant_set": "top", "variant_name": "on",
        "activations": {top: True},
    }, moves=True)
    call("select_asset_variant", {
        "prim_path": placed, "variant_set": "top", "variant_name": "on",
    }, moves=True)
    call("select_asset_variant", {
        "prim_path": placed, "variant_set": "top", "variant_name": "on",
    }, moves=False)
    call("remove_asset_variant_set", {"prim_path": placed, "variant_set": "top"}, moves=True)
    call("remove_material", {"prim_path": top}, moves=True)
    call("cleanup_unused_materials", {}, moves=False)
    call("rename_prim", {
        "old_path": placed, "new_path": "/Scene/Furniture/Desk",
    }, moves=True)
    call("save_scene_snapshot", {"name": "first"}, moves=True)
