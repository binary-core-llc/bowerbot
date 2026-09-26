# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Validation and packaging tools."""

from __future__ import annotations

from typing import Any

from bowerbot.services import validation_service
from bowerbot.skills.base import Tool, ToolEffect, ToolResult
from bowerbot.state import SceneState


def validate_scene(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Run scene validation against the active stage."""
    try:
        data = validation_service.validate_scene(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def package_scene(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Bundle the active scene into a ``.usdz``."""
    try:
        data = validation_service.package_scene(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


TOOLS: list[Tool] = [
    Tool(
        name="validate_scene",
        effect=ToolEffect.READ,
        description=(
            "Run validation checks on the current scene. Checks: "
            "defaultPrim, metersPerUnit, upAxis, reference and sublayer "
            "resolution, material bindings, and referenced-asset variant "
            "integrity, AND runs USD's UsdValidation framework (the engine "
            "behind usdchecker). Call this after placing all assets and "
            "BEFORE packaging. Returns {is_valid: bool, error_count: int, "
            "message: str, issues: [{severity: 'error'|'warning'|'info', "
            "message: str, prim: str|null}]}. error_count counts only "
            "error-severity issues (there is no separate warning count), so "
            "filter issues by severity to separate errors (must fix) from "
            "warnings/info (advisory); 'prim' is the offending prim path "
            "(null for stage-level checks and unresolved sublayers)."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    Tool(
        name="package_scene",
        description=(
            "Package the current scene into a .usdz file for distribution. "
            "It runs validate_scene first and, when that finds errors, does "
            "not package (usdz_path null, the findings in 'validation'); "
            "force=true packages anyway, and is the user's decision. "
            "If the user is shipping the .usdz to Apple consumer paths "
            "(iOS Files / Safari / iMessage AR Quick Look, macOS Quick "
            "Look, Vision Pro), pass for_apple_ar_quick_look=true so "
            "BowerBot validates the strict Apple subset (PNG/JPEG only, "
            "UsdPreviewSurface required, no UDIM, etc.) before packaging. "
            "Default off — the standard USDZ output works for Omniverse, "
            "Isaac Sim, Unreal, Unity, web viewers, and most other USD "
            "consumers without restriction. Returns {usdz_path (or null when "
            "validation refused), for_apple_ar_quick_look (echo of the "
            "flag), is_valid_for_apple (bool), apple_issues (list of "
            "{severity, message, prim}, empty unless the flag was set), "
            "validation (the validate_scene result), message}."
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
                "force": {
                    "type": "boolean",
                    "description": (
                        "Package even when validate_scene finds errors. Only "
                        "after the user has seen the errors and agreed."
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
