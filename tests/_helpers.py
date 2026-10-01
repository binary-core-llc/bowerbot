# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for tests.

Keeps test files terse by wrapping the ``SceneState`` + dispatcher
wiring behind a couple of factory functions.
"""

from __future__ import annotations

from pathlib import Path

from bowerbot import config
from bowerbot import dispatcher
from bowerbot import project_folder
from bowerbot import scene_state
from bowerbot import skills


def make_state(
    tmp_path: Path,
    project_name: str = "test",
    *,
    up_axis: config.UpAxis = config.UpAxis.Y,
    meters_per_unit: float = 1.0,
) -> tuple[scene_state.SceneState, project_folder.Project]:
    """Create a fresh project and a ``SceneState`` bound to it."""
    project = project_folder.Project.create(
        tmp_path, project_name, up_axis=up_axis, meters_per_unit=meters_per_unit,
    )
    state = scene_state.SceneState(up_axis=up_axis, meters_per_unit=meters_per_unit)
    state.project = project
    state.stage_path = project.scene_path
    return state, project


async def exec_tool(
    state: scene_state.SceneState, tool_name: str, params: dict | None = None,
) -> skills.ToolResult:
    """Dispatch a tool call against *state*."""
    return await dispatcher.execute(state, tool_name, params or {})
