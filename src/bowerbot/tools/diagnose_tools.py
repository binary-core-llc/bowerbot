# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Diagnose tool surface; one tool dispatches to every registered subsystem check."""

from __future__ import annotations

from typing import Any

from bowerbot.services import diagnose_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage


def diagnose(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Run every registered diagnostic check; surface evidence, not speculation."""
    if (err := require_stage(state)):
        return err
    try:
        data = diagnose_service.diagnose(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


TOOLS: list[Tool] = [
    Tool(
        name="diagnose",
        description=(
            "Run every registered diagnostic check against the open scene "
            "and return structured findings. Use this whenever the user "
            "asks 'why doesn't X work?' or describes broken behaviour. "
            "OMIT focus on the first call for broken-behaviour questions: "
            "the failure usually lives in a related prim (a joint, a "
            "binding, a constraint), not the prim the user named. A "
            "scene-wide sweep finds it. Use focus only when narrowing a "
            "specific prim that is already known to be broken. Each "
            "finding has check_id, subsystem, status (ok/fail/skip), "
            "severity, message, prim_path, evidence, and fix_hint. Read "
            "the failed findings and act on them; do not speculate from "
            "what list_scene returns."
        ),
        parameters={
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": (
                        "Optional prim path to focus the diagnosis on. "
                        "Omit for a scene-wide sweep."
                    ),
                },
            },
        },
    ),
]


HANDLERS = {
    "diagnose": diagnose,
}
