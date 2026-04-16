# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Validation and packaging tools."""

from __future__ import annotations

import logging
from typing import Any

from bowerbot.services import packaging_service, validation_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState

logger = logging.getLogger(__name__)


def validate_scene(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Run the scene validator against the active stage file."""
    del params
    if state.stage_path is None:
        return ToolResult(
            success=False,
            error="No stage to validate. Call create_stage first.",
        )

    result = validation_service.validate(
        state.stage_path,
        expected_meters_per_unit=state.scene_defaults.meters_per_unit,
        expected_up_axis=state.scene_defaults.up_axis,
    )

    issues = [
        {"severity": i.severity.value, "message": i.message, "prim": i.prim_path}
        for i in result.issues
    ]
    message = (
        "Scene is valid!"
        if result.is_valid
        else f"Found {result.error_count} error(s)."
    )
    return ToolResult(
        success=True,
        data={
            "is_valid": result.is_valid,
            "error_count": result.error_count,
            "issues": issues,
            "message": message,
        },
    )


def package_scene(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Package the active scene into a ``.usdz`` alongside the stage."""
    del params
    if state.stage_path is None:
        return ToolResult(
            success=False,
            error="No stage to package. Call create_stage first.",
        )

    output_path = state.stage_path.with_suffix(".usdz")
    result_path = packaging_service.package(state.stage_path, output_path)

    logger.info("Packaged scene: %s", result_path)
    return ToolResult(
        success=True,
        data={
            "usdz_path": str(result_path),
            "message": f"Scene packaged to {result_path}",
        },
    )


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
