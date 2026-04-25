# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Validation and packaging tools."""

from __future__ import annotations

from typing import Any

from bowerbot.services import validation_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage


def validate_scene(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Run scene validation against the active stage."""
    if (err := require_stage(state)):
        return err
    try:
        data = validation_service.validate_scene(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def package_scene(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Bundle the active scene into a ``.usdz``."""
    if (err := require_stage(state)):
        return err
    try:
        data = validation_service.package_scene(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


TOOLS: list[Tool] = [
    Tool(
        name="validate_scene",
        description=(
            "Run validation checks on the current scene. Checks: "
            "defaultPrim, metersPerUnit, upAxis, and reference resolution. "
            "Call this after placing all assets and BEFORE packaging."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    Tool(
        name="package_scene",
        description=(
            "Package the current scene into a .usdz file for distribution. "
            "Call validate_scene first to ensure correctness. "
            "Returns the path to the output .usdz file."
        ),
        parameters={"type": "object", "properties": {}},
    ),
]


HANDLERS = {
    "validate_scene": validate_scene,
    "package_scene": package_scene,
}
