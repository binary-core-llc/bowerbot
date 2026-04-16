# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for tool handlers."""

from __future__ import annotations

from pathlib import Path

from bowerbot.skills.base import ToolResult
from bowerbot.state import SceneState


def require_stage(state: SceneState) -> ToolResult | None:
    """Return an error ToolResult if no stage is open, else ``None``."""
    if state.stage is None or state.stage_path is None:
        return ToolResult(
            success=False,
            error="No stage open. Call create_stage first.",
        )
    return None


def require_project(state: SceneState) -> ToolResult | None:
    """Return an error ToolResult if no project is bound, else ``None``."""
    if state.project is None:
        return ToolResult(success=False, error="No project open.")
    return None


def resolve_assets_dir(state: SceneState) -> Path:
    """Return the project's assets directory, creating it on demand."""
    if state.assets_dir is None:
        msg = "No project set. Use 'bowerbot new' to create a project first."
        raise RuntimeError(msg)
    state.assets_dir.mkdir(parents=True, exist_ok=True)
    return state.assets_dir


def resolve_project_dir(state: SceneState) -> Path:
    """Return the project's root directory, or raise if unset."""
    if state.project_dir is None:
        msg = "No project set. Use 'bowerbot new' to create a project first."
        raise RuntimeError(msg)
    return state.project_dir
