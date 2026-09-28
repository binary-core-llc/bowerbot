# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Texture tools — search and list textures in the asset library."""

from __future__ import annotations

from typing import Any

from bowerbot import scene_state
from bowerbot import schemas
from bowerbot import skills
from bowerbot.services import texture_service
from bowerbot.tools import _helpers

_CATEGORY_VALUES: list[str] = [c.value for c in schemas.TextureCategory]


def search_textures(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """Search the user's asset library for textures matching a query."""
    if (err := _helpers.require_library_dir(state)):
        return err
    try:
        data = texture_service.search_textures(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


def list_textures(state: scene_state.SceneState, params: dict[str, Any]) -> skills.ToolResult:
    """List every texture in the user's asset library, optionally filtered."""
    if (err := _helpers.require_library_dir(state)):
        return err
    try:
        data = texture_service.list_textures(state, params)
    except (ValueError, RuntimeError) as e:
        return skills.ToolResult(success=False, error=str(e))
    return skills.ToolResult(success=True, data=data)


TOOLS: list[skills.Tool] = [
    skills.Tool(
        name="search_textures",
        description=(
            "Search the asset library for texture files by keyword. "
            "Finds HDRIs (.hdr, .exr) for dome lights and material maps "
            "(.png, .jpg, .tif) for surfaces. Returns a list of "
            "{name, path, format, category} entries; 'format' is the "
            "lowercased extension (e.g. '.hdr') and 'category' is 'hdri' "
            "or 'material'. Pass a result's 'path' to the appropriate tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Case-insensitive substring matched against the "
                        "filename without its extension (e.g. 'rock' matches "
                        "rock_diffuse.png)."
                    ),
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
    skills.Tool(
        name="list_textures",
        description=(
            "List every texture in the asset library. Use this to see "
            "what HDRIs and material maps are available. Returns a list of "
            "{name, path, format, category} entries; 'format' is the "
            "lowercased extension (e.g. '.hdr', '.png') and 'category' is "
            "'hdri' or 'material'."
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
