# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for tests.

Keeps test files terse by wrapping the ``SceneState`` + dispatcher
wiring behind a couple of factory functions.
"""

from __future__ import annotations

from pathlib import Path

from bowerbot import dispatcher
from bowerbot.config import SceneDefaults
from bowerbot.project import Project
from bowerbot.skills.base import ToolResult
from bowerbot.state import SceneState


def make_state(
    tmp_path: Path,
    project_name: str = "test",
    *,
    scene_defaults: SceneDefaults | None = None,
) -> tuple[SceneState, Project]:
    """Create a fresh project and a ``SceneState`` bound to it."""
    project = Project.create(tmp_path, project_name)
    state = SceneState(scene_defaults=scene_defaults or SceneDefaults())
    state.project = project
    state.stage_path = project.scene_path
    return state, project


async def exec_tool(
    state: SceneState, tool_name: str, params: dict | None = None,
) -> ToolResult:
    """Dispatch a tool call against *state*."""
    return await dispatcher.execute(state, tool_name, params or {})
