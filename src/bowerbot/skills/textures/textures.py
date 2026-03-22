# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Textures skill — searches for texture files on disk.

Finds HDRIs, material maps, and other image-based assets
in configured directories. Separate from the local asset skill
which handles 3D geometry (USD files).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from bowerbot.schemas import HDRIFormat, TextureCategory
from bowerbot.skills.base import Skill, SkillCategory, Tool, ToolResult

logger = logging.getLogger(__name__)


class TexturesSkill(Skill):
    """Searches local directories for texture files.

    Finds HDRIs for dome lights, material maps for surfaces,
    and other image-based assets. Organized separately from
    3D geometry assets.
    """

    name = "textures"
    category = SkillCategory.ASSET_PROVIDER

    def __init__(self, paths: list[str] | None = None) -> None:
        self.search_paths = [Path(p) for p in (paths or [])]

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="search_textures",
                description=(
                    "Search local directories for texture files by keyword. "
                    "Finds HDRIs (.hdr, .exr), material maps (.png, .jpg, .tif), "
                    "and other image files."
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
                            "enum": [c.value for c in TextureCategory],
                            "description": (
                                "Filter by category. "
                                "'hdri' = .hdr/.exr for dome lights. "
                                "'material' = .png/.jpg/.tif for surfaces. "
                                "'all' = everything."
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
                    "List all available texture files in local directories. "
                    "Use this to see what HDRIs and material maps are available."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": [c.value for c in TextureCategory],
                            "description": "Filter by category.",
                            "default": "all",
                        },
                    },
                },
            ),
        ]

    async def execute(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        try:
            category = TextureCategory(params.get("category", "all"))
            match tool_name:
                case "search_textures":
                    return self._search(params.get("query", ""), category)
                case "list_textures":
                    return self._list_all(category)
                case _:
                    return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
        except Exception as e:
            logger.debug(f"Textures error: {tool_name}", exc_info=True)
            return ToolResult(success=False, error=str(e))

    def _classify(self, path: Path) -> str:
        """Classify a texture file as 'hdri' or 'material'."""
        hdri_exts = {f.value for f in HDRIFormat}
        return "hdri" if path.suffix.lower() in hdri_exts else "material"

    def _format_result(self, path: Path) -> dict[str, str]:
        """Format a single texture file for the LLM."""
        return {
            "name": path.stem,
            "path": str(path),
            "format": path.suffix.lower(),
            "category": self._classify(path),
        }

    def _search(self, query: str, category: TextureCategory) -> ToolResult:
        query_lower = query.lower()
        extensions = category.extensions()
        results = []

        for search_path in self.search_paths:
            if not search_path.exists():
                continue
            for f in search_path.rglob("*"):
                if f.suffix.lower() in extensions and query_lower in f.stem.lower():
                    results.append(self._format_result(f))

        return ToolResult(success=True, data=results)

    def _list_all(self, category: TextureCategory) -> ToolResult:
        extensions = category.extensions()
        results = []

        for search_path in self.search_paths:
            if not search_path.exists():
                continue
            for f in search_path.rglob("*"):
                if f.suffix.lower() in extensions:
                    results.append(self._format_result(f))

        return ToolResult(success=True, data=results)

    def validate_config(self) -> bool:
        return len(self.search_paths) > 0
