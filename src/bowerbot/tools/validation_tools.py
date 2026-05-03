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
            "If the user is shipping the .usdz to Apple consumer paths "
            "(iOS Files / Safari / iMessage AR Quick Look, macOS Quick "
            "Look, Vision Pro), pass for_apple_ar_quick_look=true so "
            "BowerBot validates the strict Apple subset (PNG/JPEG only, "
            "UsdPreviewSurface required, no UDIM, etc.) before packaging. "
            "Default off — the standard USDZ output works for Omniverse, "
            "Isaac Sim, Unreal, Unity, web viewers, and most other USD "
            "consumers without restriction. Returns the path to the .usdz "
            "and any Apple-validation issues if applicable."
        ),
        parameters={
            "type": "object",
            "properties": {
                "for_apple_ar_quick_look": {
                    "type": "boolean",
                    "description": (
                        "If true, run Apple consumer USDZ validation "
                        "(AR Quick Look subset) before packaging and "
                        "refuse on errors. Ask the user about the target "
                        "before flipping this on."
                    ),
                    "default": False,
                },
            },
        },
    ),
]


HANDLERS = {
    "validate_scene": validate_scene,
    "package_scene": package_scene,
}
