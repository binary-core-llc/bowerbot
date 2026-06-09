# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Library tools — search and list USD assets in the user's library."""

from __future__ import annotations

from typing import Any

from bowerbot.services import library_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_library_dir
from bowerbot.utils.library_utils import (
    ALL,
    DEFAULT_SEARCH_LIMIT,
    LIBRARY_CATEGORIES,
)

_CATEGORY_VALUES: list[str] = [c.value for c in LIBRARY_CATEGORIES] + [ALL]


def search_assets(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Search the user's asset library for USDs matching a query."""
    if (err := require_library_dir(state)):
        return err
    try:
        data = library_service.search_assets(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def list_assets(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List every USD asset in the user's library, optionally filtered."""
    if (err := require_library_dir(state)):
        return err
    try:
        data = library_service.list_assets(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


TOOLS: list[Tool] = [
    Tool(
        name="search_assets",
        description=(
            "Search the user's asset library by name across every category. "
            "Returns {results: [...], total_matches: int, truncated: bool}. "
            "Each result is {name, path, format, category}: 'path' is the "
            "local file path to load — pass it as asset_file_path to "
            "place_asset for 'geo'/'package' results, or as material_file to "
            "bind_material for 'mtl' results; 'format' is the file suffix "
            "(e.g. '.usda', '.usdz'). If truncated is true, refine the query "
            "— do not ask the user to pick from a partial list."
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
                        f"(default {DEFAULT_SEARCH_LIMIT}, minimum 1)."
                    ),
                    "default": DEFAULT_SEARCH_LIMIT,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="list_assets",
        description=(
            "Browse the user's asset library, optionally filtered by "
            "category. Returns {results: [...], total_matches: int, "
            "truncated: bool}. Each result is {name, path, format, "
            "category}: 'path' is the local file path you pass straight to "
            "place_asset (asset_file_path) for 'geo'/'package' results or to "
            "bind_material (material_file) for 'mtl' results; 'format' is the "
            "USD suffix (e.g. '.usda'). If truncated is true, narrow the "
            "category filter or use search_assets with a query instead."
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
                        f"(default {DEFAULT_SEARCH_LIMIT}, minimum 1)."
                    ),
                    "default": DEFAULT_SEARCH_LIMIT,
                },
            },
        },
    ),
]


HANDLERS = {
    "search_assets": search_assets,
    "list_assets": list_assets,
}
