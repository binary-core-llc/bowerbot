# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Sketchfab skill — searches and downloads from the user's account.

Connects to the authenticated user's OWN model library, not the public
marketplace. Users upload curated, production-ready assets to Sketchfab
and BowerBot pulls them down for scene assembly.
"""

from __future__ import annotations

import logging
from typing import Any

from bowerbot.skills.base import (
    Skill,
    SkillCategory,
    SkillConfigError,
    SkillContext,
    Tool,
    ToolResult,
)
from bowerbot.skills.sketchfab.services import (
    download_service,
    search_service,
)
from bowerbot.skills.sketchfab.tools import TOOLS

logger = logging.getLogger(__name__)


class SketchfabSkill(Skill):
    """Connects to a user's Sketchfab account to search and download models.

    Requires a Sketchfab API token. Get one at
    https://sketchfab.com/settings/password.

    This skill searches the user's OWN uploaded models, not the public
    store.
    """

    name = "sketchfab"
    category = SkillCategory.ASSET_PROVIDER
    cache_subdir = "cache/sketchfab"

    def __init__(self, token: str = "", **_: Any) -> None:
        self.token = token

    def get_tools(self) -> list[Tool]:
        return list(TOOLS)

    def validate_config(self) -> None:
        if not self.token:
            msg = (
                "Sketchfab skill is missing an API token. Add one under "
                "skills.sketchfab.config.token in ~/.bowerbot/config.json. "
                "Get a token at https://sketchfab.com/settings/password."
            )
            raise SkillConfigError(msg)

    async def execute(
        self, tool_name: str, params: dict[str, Any], ctx: SkillContext,
    ) -> ToolResult:
        try:
            match tool_name:
                case "search_my_models":
                    return await search_service.search_my_models(self.token, params)
                case "list_my_models":
                    return await search_service.list_my_models(self.token, params)
                case "download_model":
                    return await download_service.download_model(
                        self.token, params, ctx,
                    )
                case _:
                    return ToolResult(
                        success=False, error=f"Unknown tool: {tool_name}",
                    )
        except Exception as e:
            logger.debug("Sketchfab error: %s", tool_name, exc_info=True)
            return ToolResult(success=False, error=str(e))
