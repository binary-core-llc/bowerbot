# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Library tools — search and list USD assets in the user's library."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import AssetCategory
from bowerbot.services import library_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState

_CATEGORY_VALUES: list[str] = [c.value for c in AssetCategory] + ["all"]


def search_assets(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Search the user's asset library for USDs matching a query."""
    if state.library_dir is None:
        return ToolResult(
            success=False,
            error="No asset library configured. Set 'assets_dir' in config.json.",
        )
    results = library_service.search_assets(
        state.library_dir,
        params.get("query", ""),
        params.get("category", "all"),
    )
    return ToolResult(success=True, data=results)


def list_assets(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List every USD asset in the user's library, optionally filtered."""
    if state.library_dir is None:
        return ToolResult(
            success=False,
            error="No asset library configured. Set 'assets_dir' in config.json.",
        )
    results = library_service.list_assets(
        state.library_dir, params.get("category", "all"),
    )
    return ToolResult(success=True, data=results)


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
