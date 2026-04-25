# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Library tools — search and list USD assets in the user's library."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import AssetCategory
from bowerbot.services import library_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_library_dir

_CATEGORY_VALUES: list[str] = [c.value for c in AssetCategory] + ["all"]


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
            "Search the user's asset library for USD assets by keyword. "
            "Returns results classified as 'geo' (geometry), 'mtl' "
            "(materials), or 'package' (ASWF asset folder). Use the "
            "category to decide the right tool: place_asset for "
            "geo/package, bind_material for mtl."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword to match against asset names.",
                },
                "category": {
                    "type": "string",
                    "enum": _CATEGORY_VALUES,
                    "description": (
                        "Filter by asset category: 'geo' = geometry, "
                        "'mtl' = material definitions, 'package' = ASWF "
                        "asset folders, 'all' = everything."
                    ),
                    "default": "all",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="list_assets",
        description=(
            "List every USD asset in the user's library. Each result "
            "includes a category: geo, mtl, or package."
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
            },
        },
    ),
]


HANDLERS = {
    "search_assets": search_assets,
    "list_assets": list_assets,
}
