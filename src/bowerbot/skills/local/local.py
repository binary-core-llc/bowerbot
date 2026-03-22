# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Local filesystem skill — searches for USD assets on disk."""

from typing import Any

from bowerbot.schemas import AssetFormat
from bowerbot.skills.base import Skill, SkillCategory, Tool, ToolResult


class LocalSkill(Skill):
    """Searches the assets directory for 3D geometry files.

    Recursively scans the shared assets_dir for USD-family files.
    No config needed — the assets_dir is set by the registry.
    """

    name = "local"
    category = SkillCategory.ASSET_PROVIDER

    SUPPORTED_EXTENSIONS = {f".{f.value}" for f in AssetFormat}

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="search_assets",
                description=(
                    "Search local directories for 3D assets "
                    "by keyword."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Search keyword to match "
                                "against filenames."
                            ),
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="list_assets",
                description=(
                    "List all available 3D assets in local "
                    "directories."
                ),
                parameters={"type": "object", "properties": {}},
            ),
        ]

    async def execute(
        self, tool_name: str, params: dict[str, Any],
    ) -> ToolResult:
        try:
            match tool_name:
                case "search_assets":
                    return self._search(params.get("query", ""))
                case "list_assets":
                    return self._list_all()
                case _:
                    return ToolResult(
                        success=False,
                        error=f"Unknown tool: {tool_name}",
                    )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _search(self, query: str) -> ToolResult:
        query_lower = query.lower()
        results = []
        root = self.assets_dir
        if not root.exists():
            return ToolResult(success=True, data=results)
        for f in root.rglob("*"):
            if (
                f.suffix.lower() in self.SUPPORTED_EXTENSIONS
                and query_lower in f.stem.lower()
            ):
                results.append({
                    "name": f.stem,
                    "path": str(f),
                    "format": f.suffix,
                })
        return ToolResult(success=True, data=results)

    def _list_all(self) -> ToolResult:
        results = []
        root = self.assets_dir
        if not root.exists():
            return ToolResult(success=True, data=results)
        for f in root.rglob("*"):
            if f.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                results.append({
                    "name": f.stem,
                    "path": str(f),
                    "format": f.suffix,
                })
        return ToolResult(success=True, data=results)

    def validate_config(self) -> bool:
        return True
