# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Library tools — search and list USD assets in the user's library."""

from __future__ import annotations

from typing import Any

from bowerbot import constants
from bowerbot import scene_state
from bowerbot import skills
from bowerbot.services import library_service
from bowerbot.tools import _helpers

_CATEGORY_VALUES: list[str] = (
    [c.value for c in constants.LibraryRules.CATEGORIES] + [constants.LibraryRules.ANY_CATEGORY]
)


def search_assets(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Search the user's asset library for USDs matching a query."""
    if (err := _helpers.require_library_dir(state)):
        return err
    try:
        data = library_service.search_assets(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def list_assets(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """List every USD asset in the user's library, optionally filtered."""
    if (err := _helpers.require_library_dir(state)):
        return err
    try:
        data = library_service.list_assets(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


TOOLS: list[skills.Tool] = [
    skills.Tool(
        name="search_assets",
        description=(
            "Search the user's asset library by name across every category. "
            "Returns {results: [...], total_matches: int, truncated: bool}. "
            "Each result is {name, path, format, category}: 'path' is the "
            "local file path to load — pass it as asset_file_path to "
            "place_asset for 'geo'/'package' results, or as material_file to "
            "bind_material for 'mtl' results; 'format' is the file suffix "
            "(e.g. '.usda', '.usdz'). A result BowerBot would refuse to place "
            "also has 'cannot_be_used' with the reason: do not place it. If "
            "truncated is true, refine the query — do not ask the user to "
            "pick from a partial list."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword to match against asset names.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        f"Maximum number of results to return "
                        f"(default {constants.LibraryDefaults.SEARCH_LIMIT}, minimum 1)."
                    ),
                    "default": constants.LibraryDefaults.SEARCH_LIMIT,
                },
            },
            "required": ["query"],
        },
    ),
    skills.Tool(
        name="list_assets",
        description=(
            "Browse the user's asset library, optionally filtered by "
            "category. Returns {results: [...], total_matches: int, "
            "truncated: bool}. Each result is {name, path, format, "
            "category}: 'path' is the local file path you pass straight to "
            "place_asset (asset_file_path) for 'geo'/'package' results or to "
            "bind_material (material_file) for 'mtl' results; 'format' is the "
            "USD suffix (e.g. '.usda'). A result BowerBot would refuse to place "
            "also has 'cannot_be_used' with the reason: do not place it. If "
            "truncated is true, narrow the category filter or use "
            "search_assets with a query instead."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": _CATEGORY_VALUES,
                    "description": "Filter by asset category.",
                    "default": "all",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        f"Maximum number of results to return "
                        f"(default {constants.LibraryDefaults.SEARCH_LIMIT}, minimum 1)."
                    ),
                    "default": constants.LibraryDefaults.SEARCH_LIMIT,
                },
            },
        },
    ),
]


HANDLERS = {
    "search_assets": search_assets,
    "list_assets": list_assets,
}
