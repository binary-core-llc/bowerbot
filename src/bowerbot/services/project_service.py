# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Project service — create, open, list, and report the focused project."""

from __future__ import annotations

import logging
from typing import Any

from bowerbot.config import UpAxis
from bowerbot.project import Project
from bowerbot.state import SceneState
from bowerbot.utils.naming_utils import safe_project_name

logger = logging.getLogger(__name__)


def list_projects(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every project in the projects directory."""
    projects = Project.list_projects(state.projects_dir)
    return {
        "projects": [
            {
                "name": p.name,
                "path": str(p.path),
                "updated_at": p.meta.updated_at,
            }
            for p in projects
        ],
        "current": state.project.name if state.project else None,
        "count": len(projects),
    }


def create_project(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create a new project and focus it."""
    name = params["name"]
    if "up_axis" not in params or "meters_per_unit" not in params:
        msg = (
            "create_project requires up_axis ('Y' or 'Z') and meters_per_unit "
            "(1.0 = meters, 0.01 = centimeters, 0.001 = millimeters)."
        )
        raise ValueError(msg)
    up_axis = UpAxis(params["up_axis"])
    meters_per_unit = float(params["meters_per_unit"])
    state.projects_dir.mkdir(parents=True, exist_ok=True)
    try:
        project = Project.create(
            state.projects_dir, name,
            up_axis=up_axis, meters_per_unit=meters_per_unit,
        )
    except FileExistsError:
        msg = f"Project '{name}' already exists. Use open_project to open it."
        raise ValueError(msg) from None
    state.bind_project(project)
    logger.info(
        "Created and focused project %s (up_axis=%s, mpu=%s)",
        project.name, up_axis.value, meters_per_unit,
    )
    return {
        "name": project.name,
        "path": str(project.path),
        "up_axis": up_axis.value,
        "meters_per_unit": meters_per_unit,
        "object_count": state.object_count,
        "message": (
            f"Created and opened project '{project.name}' "
            f"({up_axis.value}-up, metersPerUnit={meters_per_unit})."
        ),
    }


def open_project(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Open an existing project and focus it."""
    name = params["name"]
    project_path = state.projects_dir / safe_project_name(name)
    if not (project_path / "project.json").exists():
        available = [p.name for p in Project.list_projects(state.projects_dir)]
        msg = (
            f"Project '{name}' not found. "
            f"Available projects: {available or 'none'}."
        )
        raise ValueError(msg)
    project = Project.load(project_path)
    state.bind_project(project)
    logger.info("Focused project %s", project.name)
    return {
        "name": project.name,
        "path": str(project.path),
        "object_count": state.object_count,
        "message": f"Opened project '{project.name}'.",
    }


def get_current_project(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Report the currently focused project, or none."""
    if state.project is None:
        return {
            "current": None,
            "message": "No project is open. Use create_project or open_project.",
        }
    return {
        "current": state.project.name,
        "path": str(state.project.path),
        "object_count": state.object_count,
        "message": f"Currently working on '{state.project.name}'.",
    }
