# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for SceneState's external-edit detection."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from bowerbot.config import SceneDefaults
from bowerbot.state import SceneState
from tests._helpers import exec_tool, make_state


def _bump_mtime(path: Path) -> None:
    """Advance the file mtime past the filesystem's resolution boundary."""
    new_mtime = path.stat().st_mtime + 2
    os.utime(path, (new_mtime, new_mtime))


def test_no_changes_when_baseline_unset():
    state = SceneState(scene_defaults=SceneDefaults())
    assert state.detect_external_changes() is False


def test_no_changes_when_stage_path_missing():
    state = SceneState(
        scene_defaults=SceneDefaults(),
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
