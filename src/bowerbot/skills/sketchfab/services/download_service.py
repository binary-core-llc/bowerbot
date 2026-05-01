# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Download orchestrator for the Sketchfab skill."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from bowerbot.skills.base import SkillContext, ToolResult
from bowerbot.skills.sketchfab.utils.api_utils import (
    BASE_URL,
    auth_headers,
    safe_file_name,
)

logger = logging.getLogger(__name__)


async def download_model(
    token: str, params: dict[str, Any], ctx: SkillContext,
) -> ToolResult:
    """Download a model in USDZ format into the skill's cache_dir."""
    if ctx.cache_dir is None:
        return ToolResult(
            success=False,
            error="Sketchfab skill has no cache_dir; library_dir not configured.",
        )

    uid = params["uid"]
    name = params["name"]
    safe_name = safe_file_name(name) or uid

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(
            f"{BASE_URL}/models/{uid}/download",
            headers=auth_headers(token),
            timeout=15.0,
        )
        resp.raise_for_status()
        download_info = resp.json()

        usdz = download_info.get("usdz") or {}
        if not usdz.get("url"):
            return ToolResult(
                success=False,
                error=(
                    f"Model '{name}' ({uid}) has no USDZ format available. "
                    "Only USD assets are supported."
                ),
            )

        download_url = usdz["url"]
        file_size = usdz.get("size", 0)
        logger.info("Downloading USDZ (%s bytes) for %s", file_size, name)

        final_path = ctx.cache_dir / f"{safe_name}.usdz"
        resp = await client.get(download_url, timeout=120.0)
        resp.raise_for_status()
        final_path.write_bytes(resp.content)

    logger.info("Downloaded %s to %s", name, final_path)
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
