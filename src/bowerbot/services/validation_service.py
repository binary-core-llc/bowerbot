# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Validation service — orchestrates scene validation + USDZ packaging."""

from __future__ import annotations

from typing import Any

from bowerbot.state import SceneState
from bowerbot.utils import validation_utils


def validate_scene(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Run the validator against the active stage file."""
    del params
    result = validation_utils.validate_stage(
        state.stage_path,
        expected_meters_per_unit=state.scene_defaults.meters_per_unit,
        expected_up_axis=state.scene_defaults.up_axis,
    )
    return {
        "is_valid": result.is_valid,
        "error_count": result.error_count,
        "issues": [
            {"severity": i.severity.value, "message": i.message, "prim": i.prim_path}
            for i in result.issues
        ],
        "message": (
            "Scene is valid!"
            if result.is_valid
            else f"Found {result.error_count} error(s)."
        ),
    }


def package_scene(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Bundle the active scene into a ``.usdz`` alongside the stage file."""
    for_apple = bool(params.get("for_apple_ar_quick_look", False))

    apple_issues: list[dict[str, Any]] = []
    apple_errors: list[dict[str, Any]] = []
    if for_apple:
        apple_result = validation_utils.validate_for_ar_quick_look(state.stage_path)
        apple_issues = [
            {"severity": i.severity.value, "message": i.message, "prim": i.prim_path}
            for i in apple_result.issues
        ]
        apple_errors = [i for i in apple_issues if i["severity"] == "error"]
        if apple_errors:
            return {
                "usdz_path": None,
                "for_apple_ar_quick_look": True,
                "is_valid_for_apple": False,
                "apple_issues": apple_issues,
                "message": (
                    f"Apple AR Quick Look validation failed with "
                    f"{len(apple_errors)} error(s); refusing to package. "
                    f"Fix the issues or retry with "
                    f"for_apple_ar_quick_look=false to ship a standard "
                    f"USDZ for non-Apple consumers."
                ),
            }

    output_path = state.stage_path.with_suffix(".usdz")
    result_path = validation_utils.package_to_usdz(state.stage_path, output_path)
    return {
        "usdz_path": str(result_path),
        "for_apple_ar_quick_look": for_apple,
        "is_valid_for_apple": for_apple and not apple_errors,
        "apple_issues": apple_issues,
        "message": f"Scene packaged to {result_path}",
    }
