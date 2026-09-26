# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for SceneState's external-edit detection."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom

from bowerbot.state import SceneState
from tests._helpers import exec_tool, make_state


def _bump_mtime(path: Path) -> None:
    """Advance the file mtime past the filesystem's resolution boundary."""
    new_mtime = path.stat().st_mtime + 2
    os.utime(path, (new_mtime, new_mtime))


def test_no_changes_when_baseline_unset():
    state = SceneState()
    assert state.detect_external_changes() is False


def test_no_changes_when_stage_path_missing():
    state = SceneState(
        stage_path=Path("/nonexistent/scene.usda"),
    )
    state.mark_saved()
    assert state.detect_external_changes() is False


def test_mark_saved_then_no_changes():
    with tempfile.TemporaryDirectory() as tmp:
        state, project = make_state(Path(tmp))
        asyncio.run(exec_tool(state, "create_stage", {"filename": "scene"}))
        state.mark_saved()
        assert state.detect_external_changes() is False


def test_external_content_change_is_detected():
    with tempfile.TemporaryDirectory() as tmp:
        state, project = make_state(Path(tmp))
        asyncio.run(exec_tool(state, "create_stage", {"filename": "scene"}))
        state.mark_saved()

        state.stage_path.write_text(
            state.stage_path.read_text() + "\n# external edit\n",
            encoding="utf-8",
        )
        _bump_mtime(state.stage_path)

        assert state.detect_external_changes() is True


def test_mtime_bump_without_content_change_is_not_detected():
    with tempfile.TemporaryDirectory() as tmp:
        state, project = make_state(Path(tmp))
        asyncio.run(exec_tool(state, "create_stage", {"filename": "scene"}))
        state.mark_saved()

        _bump_mtime(state.stage_path)

        assert state.detect_external_changes() is False


def test_mark_saved_after_change_resets_baseline():
    with tempfile.TemporaryDirectory() as tmp:
        state, project = make_state(Path(tmp))
        asyncio.run(exec_tool(state, "create_stage", {"filename": "scene"}))
        state.mark_saved()

        state.stage_path.write_text(
            state.stage_path.read_text() + "\n# external edit\n",
            encoding="utf-8",
        )
        _bump_mtime(state.stage_path)
        assert state.detect_external_changes() is True

        state.mark_saved()
        assert state.detect_external_changes() is False


def _placed_box(tmp: str) -> tuple[SceneState, Path, str]:
    """A project with one placed box asset; returns the state, its asset folder, and prim path."""
    tmp_path = Path(tmp)
    state, project = make_state(tmp_path)
    asyncio.run(exec_tool(state, "create_stage", {}))
    source = tmp_path / "box.usda"
    stage = Usd.Stage.CreateNew(str(source))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = UsdGeom.Xform.Define(stage, "/box")
    stage.SetDefaultPrim(root.GetPrim())
    UsdGeom.Cube.Define(stage, "/box/Mesh").GetSizeAttr().Set(1.0)
    stage.Save()
    placed = asyncio.run(exec_tool(state, "place_asset", {
        "asset_file_path": str(source), "asset_name": "box", "group": "Props",
        "translate_x": 0.0, "translate_y": 0.0, "translate_z": 0.0,
    }))
    assert placed.success, placed.error
    return state, project.assets_dir / "box", placed.data["prim_path"]


def _edit_on_disk(path: Path, edit) -> None:
    """Rewrite *path* the way another program would."""
    path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
    _bump_mtime(path)


def test_asset_layer_edited_on_disk_is_seen_by_the_next_call():
    """Asset layers are watched too, not only scene.usda."""
    with tempfile.TemporaryDirectory() as tmp:
        state, asset_dir, box = _placed_box(tmp)
        _edit_on_disk(
            asset_dir / "geo.usda",
            lambda t: re.sub(r"double size = [0-9.]+", "double size = 5", t),
        )
        assert state.detect_external_changes() is True

        mesh = f"{box}/asset/Mesh"
        r = asyncio.run(exec_tool(state, "list_prim_attributes", {"prim_path": mesh}))
        assert r.success, r.error
        size = next(a["value"] for a in r.data["attributes"] if a["name"] == "size")
        assert size == 5.0


def test_bowerbot_edit_keeps_an_external_change_to_the_same_layer():
    """BowerBot reloads before editing, so it never saves a stale copy over the file."""
    with tempfile.TemporaryDirectory() as tmp:
        state, asset_dir, box = _placed_box(tmp)
        red = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": box, "material_name": "red",
        }))
        assert red.success, red.error
        mtl = asset_dir / "mtl.usda"
        _edit_on_disk(mtl, lambda t: t.rstrip() + '\n\ndef Scope "external_marker"\n{\n}\n')

        blue = asyncio.run(exec_tool(state, "create_material", {
            "prim_path": box, "material_name": "blue",
        }))
        assert blue.success, blue.error
        text = mtl.read_text(encoding="utf-8")
        assert "external_marker" in text
        assert "blue" in text


def test_a_deleted_layer_triggers_one_reload_not_one_per_call():
    """A layer missing at the last baseline is not reported again."""
    with tempfile.TemporaryDirectory() as tmp:
        state, asset_dir, _ = _placed_box(tmp)
        (asset_dir / "geo.usda").unlink()
        assert state.detect_external_changes() is True

        state.mark_saved()
        assert state.detect_external_changes() is False
