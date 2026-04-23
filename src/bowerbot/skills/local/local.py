# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Local filesystem skill — searches for USD assets on disk.

Detects ASWF-compliant asset folders (folder with matching root file)
and classifies loose files as geo or mtl by inspecting USD contents.
"""

import logging
from pathlib import Path
from typing import Any

from pxr import Usd, UsdShade

from bowerbot.schemas import AssetCategory, AssetFormat, DetectionOutcome
from bowerbot.services.intake_service import detect_folder_root
from bowerbot.skills.base import Skill, SkillCategory, Tool, ToolResult

logger = logging.getLogger(__name__)

# Extensions that indicate a USD root file
_USD_EXTENSIONS = {f.value for f in AssetFormat}


class LocalSkill(Skill):
    """Searches the assets directory for USD assets.

    Detects ASWF asset folders as single "package" entries and
    classifies loose files as geo or mtl.
    No config needed — the assets_dir is set by the registry.
    """

    name = "local"
    category = SkillCategory.ASSET_PROVIDER

    def get_tools(self) -> list[Tool]:
        categories = [c.value for c in AssetCategory] + ["all"]
        return [
            Tool(
                name="search_assets",
                description=(
                    "Search local directories for USD assets by keyword. "
                    "Returns results classified as 'geo' (geometry), "
                    "'mtl' (materials), or 'package' (ASWF asset folder). "
                    "Use the category to decide the right tool: "
                    "place_asset for geo/package, bind_material for mtl."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Search keyword to match "
                                "against asset names."
                            ),
                        },
                        "category": {
                            "type": "string",
                            "enum": categories,
                            "description": (
                                "Filter by asset category. "
                                "'geo' = geometry, "
                                "'mtl' = material definitions, "
                                "'package' = ASWF asset folders, "
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
                    "Each result includes a category: geo, mtl, or package."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": categories,
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

    # ── Asset Folder Detection ───────────────────────────────────

    @staticmethod
    def _find_asset_folders(root: Path) -> dict[Path, Path]:
        """Detect asset folders under *root* via composition-aware detection.

        A folder is treated as a package when ``detect_folder_root``
        returns an unambiguous root, whether or not the root filename
        matches the folder name. Ambiguous or empty folders are skipped
        and their USD files fall through to the loose-file pass.

        Returns a dict mapping folder path → root file path.
        """
        packages: dict[Path, Path] = {}
        if not root.exists():
            return packages

        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            if entry.name in ("cache", "maps", "materials"):
                continue
            detection = detect_folder_root(entry)
            if detection.outcome is DetectionOutcome.UNAMBIGUOUS and detection.root:
                packages[entry] = Path(detection.root)

        return packages

    @staticmethod
    def _is_inside_package(
        file_path: Path, package_dirs: set[Path],
    ) -> bool:
        """Check if a file lives inside a detected asset folder."""
        for pkg_dir in package_dirs:
            if pkg_dir in file_path.parents:
                return True
        return False

    # ── Classification ───────────────────────────────────────────

    @staticmethod
    def _classify(file_path: Path) -> str:
        """Classify a loose USD file as 'geo' or 'mtl'.

        - **mtl**: contains UsdShade.Material prims
        - **geo**: everything else (meshes, xforms)
        """
        try:
            # Material files define Material prims
            stage = Usd.Stage.Open(str(file_path))
            if stage is not None:
                for prim in stage.Traverse():
                    if prim.IsA(UsdShade.Material):
                        return AssetCategory.MTL.value
        except Exception:
            logger.debug(
                "Could not classify %s, defaulting to geo",
                file_path,
                exc_info=True,
            )

        return AssetCategory.GEO.value

    # ── Scanning ─────────────────────────────────────────────────

    def _scan(
        self, query: str | None = None, category: str = "all",
    ) -> list[dict[str, str]]:
        """Scan assets_dir for packages and loose files.

        If query is provided, filters by keyword match on asset name.
        If category is not 'all', filters by category.
        """
        root = self.assets_dir
        if not root.exists():
            return []

        results: list[dict[str, str]] = []

        # 1. Detect ASWF asset folders first
        packages = self._find_asset_folders(root)
        package_dirs = set(packages.keys())

        for pkg_dir, root_file in packages.items():
            name = pkg_dir.name
            # Match against the folder name (authoritative) and the root
            # filename stem (so non-canonical layouts are still findable
            # by either label).
            haystack = (name.lower(), root_file.stem.lower())
            if query and not any(query.lower() in h for h in haystack):
                continue

            entry = {
                "name": name,
                "path": str(root_file),
                "format": root_file.suffix,
                "category": AssetCategory.PACKAGE.value,
            }
            if category == "all" or category == entry["category"]:
                results.append(entry)

        # 2. Scan loose files (skip anything inside asset folders)
        for f in root.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in _USD_EXTENSIONS:
                continue
            if self._is_inside_package(f, package_dirs):
                continue

            name = f.stem
            if query and query.lower() not in name.lower():
                continue

            entry = {
                "name": name,
                "path": str(f),
                "format": f.suffix,
                "category": self._classify(f),
            }
            if category == "all" or category == entry["category"]:
                results.append(entry)

        return results

    def _search(self, query: str, category: str) -> ToolResult:
        return ToolResult(
            success=True,
            data=self._scan(query=query, category=category),
        )

    def _list_all(self, category: str) -> ToolResult:
        return ToolResult(
            success=True,
            data=self._scan(category=category),
        )

    def validate_config(self) -> bool:
        return True
