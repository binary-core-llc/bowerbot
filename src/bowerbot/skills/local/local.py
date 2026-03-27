# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Local filesystem skill — searches for USD assets on disk.

Classifies each file as geometry, material, or look by inspecting
the USD contents. This lets the LLM choose the right tool
(place_asset, bind_material, or apply_look) without guessing.
"""

import logging
from pathlib import Path
from typing import Any

from pxr import Sdf, Usd, UsdShade

from bowerbot.schemas import AssetFormat
from bowerbot.skills.base import Skill, SkillCategory, Tool, ToolResult

logger = logging.getLogger(__name__)


class LocalSkill(Skill):
    """Searches the assets directory for USD files.

    Recursively scans the shared assets_dir for USD-family files
    and classifies each as geometry, material, or look.
    No config needed — the assets_dir is set by the registry.
    """

    name = "local"
    category = SkillCategory.ASSET_PROVIDER

    SUPPORTED_EXTENSIONS = {f.value for f in AssetFormat}

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="search_assets",
                description=(
                    "Search local directories for USD assets by keyword. "
                    "Returns results classified as 'geometry', 'material', "
                    "or 'look'. Use the category to decide the right tool: "
                    "place_asset for geometry, bind_material for materials, "
                    "apply_look for look files."
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
                        "category": {
                            "type": "string",
                            "enum": ["all", "geometry", "material", "look"],
                            "description": (
                                "Filter by asset category. "
                                "'geometry' = 3D meshes, "
                                "'material' = material definitions, "
                                "'look' = look files with bindings, "
                                "'all' = everything."
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
                    "List all available USD assets in local directories. "
                    "Each result includes a category: geometry, material, "
                    "or look."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["all", "geometry", "material", "look"],
                            "description": "Filter by asset category.",
                            "default": "all",
                        },
                    },
                },
            ),
        ]

    async def execute(
        self, tool_name: str, params: dict[str, Any],
    ) -> ToolResult:
        try:
            category = params.get("category", "all")
            match tool_name:
                case "search_assets":
                    return self._search(
                        params.get("query", ""), category,
                    )
                case "list_assets":
                    return self._list_all(category)
                case _:
                    return ToolResult(
                        success=False,
                        error=f"Unknown tool: {tool_name}",
                    )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    @staticmethod
    def _classify(file_path: Path) -> str:
        """Classify a USD file as 'geometry', 'material', or 'look'.

        - **material**: contains UsdShade.Material prims
        - **look**: has sublayers (composes geometry + materials)
        - **geometry**: everything else (meshes, xforms)
        """
        try:
            layer = Sdf.Layer.FindOrOpen(str(file_path))
            if layer is None:
                return "geometry"

            # Look files have sublayers that compose other files
            if layer.subLayerPaths:
                return "look"

            # Material files define Material prims
            stage = Usd.Stage.Open(str(file_path))
            if stage is not None:
                for prim in stage.Traverse():
                    if prim.IsA(UsdShade.Material):
                        return "material"
        except Exception:
            logger.debug(
                "Could not classify %s, defaulting to geometry",
                file_path,
                exc_info=True,
            )

        return "geometry"

    def _format_result(self, file_path: Path) -> dict[str, str]:
        """Format a single USD file with classification."""
        return {
            "name": file_path.stem,
            "path": str(file_path),
            "format": file_path.suffix,
            "category": self._classify(file_path),
        }

    def _search(self, query: str, category: str) -> ToolResult:
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
                entry = self._format_result(f)
                if category == "all" or entry["category"] == category:
                    results.append(entry)
        return ToolResult(success=True, data=results)

    def _list_all(self, category: str) -> ToolResult:
        results = []
        root = self.assets_dir
        if not root.exists():
            return ToolResult(success=True, data=results)
        for f in root.rglob("*"):
            if f.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                entry = self._format_result(f)
                if category == "all" or entry["category"] == category:
                    results.append(entry)
        return ToolResult(success=True, data=results)

    def validate_config(self) -> bool:
        return True
