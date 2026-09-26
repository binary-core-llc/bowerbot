# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Validation service — orchestrates scene validation + USDZ packaging."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import AssetFormat
from bowerbot.state import SceneState
from bowerbot.utils import validation


def validate_scene(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Run the validator against the active stage file."""
    del params
    return validation.stage.stage_report(
        state.require_stage_path(),
        expected_meters_per_unit=state.meters_per_unit,
        expected_up_axis=state.up_axis,
    )


def package_scene(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Validate the active scene, then bundle it into a ``.usdz`` beside the stage file.

    Errors from ``validate_scene`` refuse the package unless ``force`` is set.
    """
    stage_path = state.require_stage_path()
    for_apple = bool(params.get("for_apple_ar_quick_look", False))
    force = bool(params.get("force", False))

    checked = validation.stage.stage_report(
        stage_path,
        expected_meters_per_unit=state.meters_per_unit,
        expected_up_axis=state.up_axis,
    )
    if checked["error_count"] and not force:
        return {
            "usdz_path": None,
            "for_apple_ar_quick_look": for_apple,
            "is_valid_for_apple": False,
            "apple_issues": [],
            "validation": checked,
            "message": (
                f"validate_scene found {checked['error_count']} error(s); refusing "
                f"to package. Fix them, or ask the user whether to package anyway "
                f"(force=true)."
            ),
        }

    apple_issues: list[dict[str, Any]] = []
    apple_errors: list[dict[str, Any]] = []
    if for_apple:
        apple_result = validation.ar_quick_look.validate_for_ar_quick_look(stage_path)
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
                "validation": checked,
                "message": (
                    f"Apple AR Quick Look validation failed with "
                    f"{len(apple_errors)} error(s); refusing to package. "
                    f"Fix the issues or retry with "
                    f"for_apple_ar_quick_look=false to ship a standard "
                    f"USDZ for non-Apple consumers."
                ),
            }

    output_path = stage_path.with_suffix(AssetFormat.USDZ)
    result_path = validation.packaging.package_to_usdz(stage_path, output_path)
    return {
        "usdz_path": str(result_path),
        "for_apple_ar_quick_look": for_apple,
        "is_valid_for_apple": for_apple and not apple_errors,
        "apple_issues": apple_issues,
        "validation": checked,
        "message": (
            f"Scene packaged to {result_path}"
            + (f" despite {checked['error_count']} validation error(s)"
               if checked["error_count"] else "")
            + "."
        ),
    }
