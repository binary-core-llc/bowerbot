# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""MCP server runtime: exposes BowerBot's tools to an MCP client over stdio."""

from __future__ import annotations

import asyncio
import json
import logging
from importlib.metadata import PackageNotFoundError, version

import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from bowerbot import tool_router
from bowerbot.config import Settings
from bowerbot.skills.registry import SkillRegistry
from bowerbot.state import SceneState

logger = logging.getLogger(__name__)


def _server_version() -> str:
    """Installed bowerbot version, or a placeholder when not packaged."""
    try:
        return version("bowerbot")
    except PackageNotFoundError:
        return "0.0.0"


def _to_mcp_tools(schemas: list[dict]) -> list[types.Tool]:
    """Convert litellm function schemas into MCP tool definitions."""
    tools: list[types.Tool] = []
    for schema in schemas:
        fn = schema["function"]
        tools.append(types.Tool(
            name=fn["name"],
            description=fn.get("description", ""),
            inputSchema=fn.get(
                "parameters", {"type": "object", "properties": {}},
            ),
        ))
    return tools


def _build_server(state: SceneState, skill_registry: SkillRegistry) -> Server:
    """Wire the list-tools and call-tool handlers onto a new MCP server."""
    server = Server("bowerbot")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return _to_mcp_tools(tool_router.combined_tool_schemas(skill_registry))

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict,
    ) -> list[types.TextContent]:
        result = await tool_router.route(
            state, skill_registry, name, arguments or {},
        )
        if not result.success:
            raise RuntimeError(result.error or f"{name} failed")
        return [
            types.TextContent(
                type="text", text=json.dumps(result.data, default=str),
            ),
        ]

    return server


async def _serve(settings: Settings) -> None:
    """Run the stdio MCP server until the client disconnects."""
    state = SceneState.from_settings(settings)
    skill_registry = SkillRegistry()
    skill_registry.load_from_settings(settings)
    server = _build_server(state, skill_registry)

    logger.info(
        "MCP server starting: %d tool(s), %d skill(s)",
        len(tool_router.combined_tool_schemas(skill_registry)),
        skill_registry.skill_count,
    )
    async with stdio_server() as (read, write):
        await server.run(
            read,
            write,
            InitializationOptions(
                server_name="bowerbot",
                server_version=_server_version(),
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def serve(settings: Settings) -> None:
    """Run the MCP server (blocking) until the client disconnects."""
    asyncio.run(_serve(settings))
