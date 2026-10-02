# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool dispatcher: collects every tool module's definitions and routes calls to handlers."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import jsonschema

from bowerbot import logging_setup
from bowerbot import scene_state
from bowerbot import skills
from bowerbot.tools import asset_tools
from bowerbot.tools import camera_tools
from bowerbot.tools import library_tools
from bowerbot.tools import light_tools
from bowerbot.tools import material_tools
from bowerbot.tools import physics_tools
from bowerbot.tools import project_tools
from bowerbot.tools import scatter_tools
from bowerbot.tools import stage_tools
from bowerbot.tools import texture_tools
from bowerbot.tools import validation_tools
from bowerbot.tools import variant_tools

logger = logging.getLogger(__name__)

ToolHandler = Callable[
    [scene_state.SceneState, dict[str, Any]],
    skills.ToolResult | Awaitable[skills.ToolResult],
]


def _collect_tools() -> list[skills.Tool]:
    """Flatten every tool module's ``TOOLS`` list into one registry."""
    tools: list[skills.Tool] = []
    tools.extend(project_tools.TOOLS)
    tools.extend(stage_tools.TOOLS)
    tools.extend(asset_tools.TOOLS)
    tools.extend(camera_tools.TOOLS)
    tools.extend(library_tools.TOOLS)
    tools.extend(light_tools.TOOLS)
    tools.extend(material_tools.TOOLS)
    tools.extend(physics_tools.TOOLS)
    tools.extend(scatter_tools.TOOLS)
    tools.extend(texture_tools.TOOLS)
    tools.extend(validation_tools.TOOLS)
    tools.extend(variant_tools.TOOLS)
    return tools


def _collect_handlers() -> dict[str, ToolHandler]:
    """Flatten every tool module's ``HANDLERS`` dict into one registry."""
    handlers: dict[str, ToolHandler] = {}
    for module in (
        project_tools, stage_tools, asset_tools, camera_tools, library_tools,
        light_tools, material_tools, physics_tools, scatter_tools, texture_tools,
        validation_tools, variant_tools,
    ):
        handlers.update(module.HANDLERS)
    return handlers


TOOLS: list[skills.Tool] = _collect_tools()
HANDLERS: dict[str, ToolHandler] = _collect_handlers()


def get_tool_schemas() -> list[dict[str, Any]]:
    """Return all tool definitions in LLM function-calling schema form."""
    return [tool.to_llm_schema() for tool in TOOLS]


def get_tool_names() -> set[str]:
    """Return the set of tool names owned by the dispatcher."""
    return set(HANDLERS.keys())


_TOOLS_BY_NAME: dict[str, skills.Tool] = {t.name: t for t in TOOLS}


async def execute(
    state: scene_state.SceneState, tool_name: str, params: dict[str, Any],
) -> skills.ToolResult:
    """Route a tool call by name to its registered handler."""
    if state.stage is not None and state.detect_external_changes():
        logger.info(
            "External edits detected in %s, reloading before %s",
            state.stage_path, tool_name,
        )
        state.stage.Reload()
        state.mark_saved()

    handler = HANDLERS.get(tool_name)
    if handler is None:
        logger.warning("tool-unknown name=%s", tool_name)
        return skills.ToolResult(
            success=False, error=f"Unknown tool: {tool_name}",
        )

    rejection = _reject_unknown_params(tool_name, params)
    if rejection is None:
        rejection = _reject_invalid_params(tool_name, params)
    if rejection is not None:
        logger.info("tool-bad-params name=%s error=%s", tool_name, rejection)
        return skills.ToolResult(success=False, error=rejection)

    object_count = state.object_count
    scene_before = state.stage_path
    physics_errors_before = state.physics_errors()
    try:
        result = handler(state, params)
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        state.restore_after_failure(object_count)
        raise
    if not result.success:
        state.restore_after_failure(object_count)
    elif physics_errors_before is not None and state.stage_path == scene_before:
        _report_new_physics_errors(state, result, physics_errors_before)

    logging_setup.log_tool_result(logger, tool_name, result)
    state.mark_saved()
    state.note_project_writes()
    return result


def _report_new_physics_errors(
    state: scene_state.SceneState, result: skills.ToolResult, before: set[str],
) -> None:
    """Report in the answer any physics error a call left the scene that it did not have."""
    added = sorted((state.physics_errors() or set()) - before)
    if not added or not isinstance(result.data, dict):
        return
    found = "; ".join(message.rstrip(".") for message in added)
    said = str(result.data.get("message") or "Done").rstrip()
    result.data["physics_errors"] = added
    result.data["message"] = (
        f"{said if said.endswith(('.', '!', '?')) else said + '.'} WARNING: this change left "
        f"the scene with {len(added)} physics error(s) it did not have: {found}. "
        "Undo it or fix the cause."
    )


_VALIDATORS: dict[str, jsonschema.Draft202012Validator] = {}


def _reject_invalid_params(
    tool_name: str, params: dict[str, Any],
) -> str | None:
    """Return an error message if *params* violates the tool's JSON schema."""
    tool = _TOOLS_BY_NAME.get(tool_name)
    if tool is None or not tool.parameters:
        return None
    validator = _VALIDATORS.get(tool_name)
    if validator is None:
        validator = jsonschema.Draft202012Validator(tool.parameters)
        _VALIDATORS[tool_name] = validator
    error = jsonschema.exceptions.best_match(validator.iter_errors(params))
    if error is None:
        return None
    path = ".".join(str(part) for part in error.absolute_path)
    where = f" at '{path}'" if path else ""
    return f"invalid parameters for {tool_name}{where}: {error.message}"


def _reject_unknown_params(
    tool_name: str, params: dict[str, Any],
) -> str | None:
    """Return an error message if *params* has keys the tool does not declare."""
    tool = _TOOLS_BY_NAME.get(tool_name)
    if tool is None:
        return None
    declared = (tool.parameters or {}).get("properties") or {}
    if not declared:
        return None
    unknown = sorted(k for k in params if k not in declared)
    if not unknown:
        return None
    return (
        f"{tool_name} does not accept parameter(s) {unknown}. "
        f"Allowed: {sorted(declared)}. If you need to set an "
        "attribute the tool does not expose (e.g. rotation on the X or "
        "Z axis, scale, colorTemperature), use set_prim_attribute with "
        "the exact attribute name from list_prim_attributes."
    )
