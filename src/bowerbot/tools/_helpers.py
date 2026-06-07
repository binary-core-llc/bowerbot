# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Shared precondition guards for tool handlers."""

from __future__ import annotations

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


def require_library_dir(state: SceneState) -> ToolResult | None:
    """Return an error ToolResult if no library is configured, else ``None``."""
    if state.library_dir is None:
        return ToolResult(
            success=False,
            error="No asset library configured. Set 'assets_dir' in config.json.",
        )
    return None


def require_projects_dir(state: SceneState) -> ToolResult | None:
    """Return an error ToolResult if no projects dir is configured, else ``None``."""
    if state.projects_dir is None:
        return ToolResult(
            success=False,
            error="No projects directory configured. Set 'projects_dir' in config.json.",
        )
    return None
