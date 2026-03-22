# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Sketchfab skill — searches and downloads assets from a user's Sketchfab account.

This connects to the authenticated user's OWN model library,
not the public marketplace. Users upload their curated, production-ready
assets to Sketchfab and BowerBot pulls them down for scene assembly.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from bowerbot.skills.base import Skill, SkillCategory, Tool, ToolResult

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sketchfab.com/v3"


class SketchfabSkill(Skill):
    """Connects to a user's Sketchfab account to search and download their models.

    Requires a Sketchfab API token. Get one at:
    https://sketchfab.com/settings/password

    This skill searches the user's OWN uploaded models, not the public store.
    """

    name = "sketchfab"
    category = SkillCategory.ASSET_PROVIDER

    cache_subdir = "cache/sketchfab"

    def __init__(self, token: str = "", **kwargs: Any) -> None:
        self.token = token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self.token}"}

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="search_my_models",
                description=(
                    "Search YOUR OWN Sketchfab model library by keyword. "
                    "Returns models you have uploaded to your account."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Search keyword to find models "
                                "in your library."
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results (1-24).",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="list_my_models",
                description=(
                    "List all models in YOUR Sketchfab account. "
                    "Use this to see everything available before searching."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results (1-24).",
                            "default": 24,
                        },
                    },
                },
            ),
            Tool(
                name="download_model",
                description=(
                    "Download a model from your Sketchfab account by its UID."
                    "Downloads in USDZ format only."
                    "Returns the local file path of the downloaded asset."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "uid": {
                            "type": "string",
                            "description": "Sketchfab model UID (from search results).",
                        },
                        "name": {
                            "type": "string",
                            "description": (
                                "Human-readable name for the "
                                "downloaded file."
                            ),
                        },
                    },
                    "required": ["uid", "name"],
                },
            ),
        ]

    async def execute(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        try:
            match tool_name:
                case "search_my_models":
                    return await self._search_my_models(params)
                case "list_my_models":
                    return await self._list_my_models(params)
                case "download_model":
                    return await self._download_model(params)
                case _:
                    return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
        except Exception as e:
            logger.debug(f"Sketchfab error: {tool_name}", exc_info=True)
            return ToolResult(success=False, error=str(e))

    async def _search_my_models(self, params: dict[str, Any]) -> ToolResult:
        """Search the authenticated user's own models."""

        query = params["query"]
        max_results = min(params.get("max_results", 10), 24)

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/me/models",
                params={
                    "q": query,
                    "count": max_results,
                },
                headers=self._headers(),
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

        return ToolResult(success=True, data=self._format_model_list(data))

    async def _list_my_models(self, params: dict[str, Any]) -> ToolResult:
        """List all models in the user's account."""

        max_results = min(params.get("max_results", 24), 24)

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/me/models",
                params={"count": max_results},
                headers=self._headers(),
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

        return ToolResult(success=True, data=self._format_model_list(data))

    async def _download_model(self, params: dict[str, Any]) -> ToolResult:
        """Download a model in USDZ format only."""

        uid = params["uid"]
        name = params["name"]

        safe_name = "".join(c for c in name if c.isalnum() or c in "_-").strip()
        if not safe_name:
            safe_name = uid

        async with httpx.AsyncClient(follow_redirects=True) as client:
            # Step 1: Get download URLs
            resp = await client.get(
                f"{BASE_URL}/models/{uid}/download",
                headers=self._headers(),
                timeout=15.0,
            )
            resp.raise_for_status()
            download_info = resp.json()

            # Step 2: USDZ only — no fallback
            if "usdz" not in download_info or not download_info["usdz"].get("url"):
                return ToolResult(
                    success=False,
                    error=(
                        f"Model '{name}' ({uid}) has no USDZ format available. "
                        "Only USD assets are supported."
                    ),
                )

            download_url = download_info["usdz"]["url"]
            file_size = download_info["usdz"].get("size", 0)
            logger.info(f"Downloading USDZ ({file_size} bytes) for {name}")

            # Step 3: Download
            final_path = self.cache_dir / f"{safe_name}.usdz"

            resp = await client.get(download_url, timeout=120.0)
            resp.raise_for_status()
            final_path.write_bytes(resp.content)

        logger.info(f"Downloaded {name} to {final_path}")
        return ToolResult(
            success=True,
            data={
                "file_path": str(final_path),
                "format": "usdz",
                "size_bytes": file_size,
                "name": name,
                "uid": uid,
                "message": f"Downloaded {name} (USDZ) to {final_path}",
            },
        )

    def _format_model_list(self, api_response: dict[str, Any]) -> list[dict[str, Any]]:
        """Format the Sketchfab API response into a clean list for the LLM."""
        results = []
        for model in api_response.get("results", []):
            thumbnail = None
            thumbs = model.get("thumbnails", {}).get("images", [])
            if thumbs:
                thumbnail = thumbs[0].get("url")

            results.append({
                "uid": model["uid"],
                "name": model["name"],
                "description": model.get("description", ""),
                "url": model.get("viewerUrl", ""),
                "vertex_count": model.get("vertexCount"),
                "face_count": model.get("faceCount"),
                "is_downloadable": model.get("isDownloadable", False),
                "tags": [t.get("name", "") for t in model.get("tags", [])],
                "thumbnail": thumbnail,
            })
        return results

    def validate_config(self) -> bool:
        return bool(self.token)
