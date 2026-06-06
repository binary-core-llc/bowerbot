# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""MCP server runtime: serves BowerBot's tools over stdio or HTTP."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from importlib.metadata import PackageNotFoundError, version

import mcp.types as types
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

from bowerbot import tool_router
from bowerbot.config import McpSettings, Settings, Transport
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
    server: Server = Server("bowerbot", version=_server_version())

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


def _security_settings(mcp: McpSettings) -> TransportSecuritySettings:
    """DNS-rebinding protection: accept only the configured local origin."""
    hosts = {
        f"{mcp.host}:{mcp.port}",
        f"127.0.0.1:{mcp.port}",
        f"localhost:{mcp.port}",
    }
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(hosts),
        allowed_origins=sorted(f"http://{host}" for host in hosts),
    )


def build_app(settings: Settings) -> Starlette:
    """Build the ASGI app that serves the MCP tool surface over HTTP."""
    state = SceneState.from_settings(settings)
    skill_registry = SkillRegistry()
    skill_registry.load_from_settings(settings)
    server = _build_server(state, skill_registry)
    manager = StreamableHTTPSessionManager(
        app=server,
        stateless=True,
        security_settings=_security_settings(settings.mcp),
    )

    async def handle(scope, receive, send) -> None:
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with manager.run():
            logger.info(
                "MCP server ready: %d tool(s), %d skill(s) on %s",
                len(tool_router.combined_tool_schemas(skill_registry)),
                skill_registry.skill_count,
                settings.mcp.path,
            )
            yield

    return Starlette(
        routes=[Mount(settings.mcp.path, app=handle)],
        lifespan=lifespan,
    )


async def _run_stdio(settings: Settings) -> None:
    """Serve the MCP tool surface to a client that spawned us over stdio."""
    state = SceneState.from_settings(settings)
    skill_registry = SkillRegistry()
    skill_registry.load_from_settings(settings)
    server = _build_server(state, skill_registry)
    logger.info(
        "MCP server ready over stdio: %d tool(s), %d skill(s)",
        len(tool_router.combined_tool_schemas(skill_registry)),
        skill_registry.skill_count,
    )
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def serve(settings: Settings) -> None:
    """Run the MCP server (blocking) over the configured transport."""
    if settings.mcp.transport is Transport.HTTP:
        uvicorn.run(
            build_app(settings),
            host=settings.mcp.host,
            port=settings.mcp.port,
        )
    else:
        asyncio.run(_run_stdio(settings))
