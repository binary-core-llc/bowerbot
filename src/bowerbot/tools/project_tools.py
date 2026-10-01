# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Project tools — create / open / list / report the focused project."""

from __future__ import annotations

from typing import Any

from bowerbot import scene_state
from bowerbot import skills
from bowerbot.services import project_service
from bowerbot.tools import _helpers


def list_projects(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """List every project in the projects directory."""
    if (err := _helpers.require_projects_dir(state)):
        return err
    try:
        data = project_service.list_projects(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def create_project(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Create a new project and focus it."""
    if (err := _helpers.require_projects_dir(state)):
        return err
    try:
        data = project_service.create_project(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def open_project(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Open an existing project and focus it."""
    if (err := _helpers.require_projects_dir(state)):
        return err
    try:
        data = project_service.open_project(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def get_current_project(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Report the currently focused project, or none."""
    try:
        data = project_service.get_current_project(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


TOOLS: list[skills.Tool] = [
    skills.Tool(
        name="list_projects",
        description=(
            "List every BowerBot project. Each entry has the project's "
            "name, path, and updated_at (ISO timestamp of last edit); the "
            "result also carries a total count and a top-level current "
            "field naming the focused project (null if none). Use updated_at "
            "to resume the most recently edited project without reading any "
            "files."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    skills.Tool(
        name="create_project",
        description=(
            "Create a new BowerBot project and immediately focus it. "
            "Every subsequent tool call (place_asset, create_light, ...) "
            "operates on this project until another is opened. Use when "
            "the user wants to start a fresh scene. The project's scene "
            "fixes its world up-axis and units up front and every placed "
            "asset is conformed to them, so up_axis and meters_per_unit "
            "are required: ask the user, or match the source you are "
            "reconstructing (an Omniverse/Isaac scene is usually Z-up in "
            "meters; most Maya/web content is Y-up)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Human-readable project name (e.g. 'Coffee Shop'). "
                        "The folder name is derived from it."
                    ),
                },
                "up_axis": {
                    "type": "string",
                    "enum": ["Y", "Z"],
                    "description": (
                        "World up-axis for the scene. 'Z' for "
                        "Omniverse/Isaac/CAD-style sources, 'Y' otherwise."
                    ),
                },
                "meters_per_unit": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": (
                        "Scene units as USD metersPerUnit: 1.0 = meters, "
                        "0.01 = centimeters, 0.001 = millimeters. Must be "
                        "greater than 0."
                    ),
                },
            },
            "required": ["name", "up_axis", "meters_per_unit"],
        },
    ),
    skills.Tool(
        name="open_project",
        description=(
            "Open an existing BowerBot project and focus it. Every "
            "subsequent tool call operates on this project until another "
            "is opened. Returns the project name, path, and object_count "
            "(prims already in the opened scene), so no follow-up call is "
            "needed to learn the scene size. Use when the user wants to "
            "resume or switch to a different project. Call list_projects "
            "first if unsure of the exact name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Name of the project to open (as shown by "
                        "list_projects)."
                    ),
                },
            },
            "required": ["name"],
        },
    ),
    skills.Tool(
        name="get_current_project",
        description=(
            "Report which project is currently focused, including its "
            "path and object count. Returns current=null (with an "
            "explanatory message) when none is focused. Use to confirm "
            "context before authoring."
        ),
        parameters={"type": "object", "properties": {}},
    ),
]


HANDLERS = {
    "list_projects": list_projects,
    "create_project": create_project,
    "open_project": open_project,
    "get_current_project": get_current_project,
}
