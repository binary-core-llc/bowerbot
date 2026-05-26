# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Diagnose service: run every registered check and return a unified report."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import DiagnosticReport
from bowerbot.state import SceneState
from bowerbot.utils import diagnostic_registry_utils

# Side-effect import: registers every core diagnostic check at startup.
from bowerbot.utils import physics_diagnostic_utils as _physics_diagnostic_utils  # noqa: F401, E402


def diagnose(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Run every registered diagnostic check; broad focus falls back to scene-wide."""
    if state.stage is None:
        raise ValueError("No scene stage is open.")
    focus_prim, focus_path = diagnostic_registry_utils.resolve_focus(
        state.stage, params.get("focus"),
    )
    findings = diagnostic_registry_utils.run(state.stage, focus_prim)
    return DiagnosticReport(focus=focus_path, findings=findings).model_dump()
