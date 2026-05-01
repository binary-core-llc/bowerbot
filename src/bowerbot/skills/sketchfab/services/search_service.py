# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Search and list orchestrators for the Sketchfab skill."""

from __future__ import annotations

from typing import Any

import httpx

from bowerbot.skills.base import ToolResult
from bowerbot.skills.sketchfab.utils.api_utils import (
    BASE_URL,
    auth_headers,
    format_model_list,
)


async def search_my_models(token: str, params: dict[str, Any]) -> ToolResult:
    """Search the authenticated user's own Sketchfab library."""
    query = params["query"]
    max_results = min(params.get("max_results", 10), 24)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/me/models",
            params={"q": query, "count": max_results},
            headers=auth_headers(token),
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
    return ToolResult(success=True, data=format_model_list(data))


async def list_my_models(token: str, params: dict[str, Any]) -> ToolResult:
    """List every model in the authenticated user's account."""
    max_results = min(params.get("max_results", 24), 24)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/me/models",
            params={"count": max_results},
            headers=auth_headers(token),
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
    return ToolResult(success=True, data=format_model_list(data))
