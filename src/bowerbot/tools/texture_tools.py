# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Texture tools — search and list textures in the asset library."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import TextureCategory
from bowerbot.services import texture_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_library_dir

_CATEGORY_VALUES: list[str] = [c.value for c in TextureCategory]


def search_textures(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Search the user's asset library for textures matching a query."""
    if (err := require_library_dir(state)):
        return err
    try:
        data = texture_service.search_textures(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def list_textures(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List every texture in the user's asset library, optionally filtered."""
    if (err := require_library_dir(state)):
        return err
    try:
        data = texture_service.list_textures(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


TOOLS: list[Tool] = [
    Tool(
        name="search_textures",
        description=(
            "Search the asset library for texture files by keyword. "
            "Finds HDRIs (.hdr, .exr) for dome lights and material maps "
            "(.png, .jpg, .tif) for surfaces."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword to match against filenames.",
                },
                "category": {
                    "type": "string",
                    "enum": _CATEGORY_VALUES,
                    "description": (
                        "Filter by category: 'hdri' = .hdr/.exr for dome "
                        "lights, 'material' = .png/.jpg for surfaces, "
                        "'all' = both."
                    ),
                    "default": "all",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="list_textures",
        description=(
            "List every texture in the asset library. Use this to see "
            "what HDRIs and material maps are available."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": _CATEGORY_VALUES,
                    "description": "Filter by category.",
                    "default": "all",
                },
            },
        },
    ),
]


HANDLERS = {
    "search_textures": search_textures,
    "list_textures": list_textures,
}
