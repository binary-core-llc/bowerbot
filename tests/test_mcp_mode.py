# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for MCP mode: the mode config, the shared router, and the server."""

import asyncio
import tempfile
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from bowerbot import mcp_server, tool_router
from bowerbot.config import McpSettings, Mode, Settings, Transport
from bowerbot.skills.base import SkillCategory, ToolResult
from bowerbot.skills.registry import SkillRegistry
from bowerbot.state import SceneState


def _settings(tmp):
    return Settings(
        projects_dir=Path(tmp) / "scenes",
        assets_dir=Path(tmp) / "assets",
    )


def _server_and_state(tmp):
    settings = _settings(tmp)
    state = SceneState.from_settings(settings)
    registry = SkillRegistry()
    registry.load_from_settings(settings)
    return mcp_server._build_server(state, registry), state


# ── mode config ──


def test_mode_defaults_to_agent():
    """A fresh config is in agent mode."""
    assert Settings().mode is Mode.AGENT


def test_mode_parses_mcp():
    """The mode field accepts 'mcp'."""
    assert Settings(mode="mcp").mode is Mode.MCP


def test_mcp_settings_defaults():
    """MCP server defaults to stdio, with http bound to localhost:8181 at /mcp."""
    s = Settings().mcp
    assert s.transport is Transport.STDIO
    assert s.host == "127.0.0.1"
    assert s.port == 8181
    assert s.path == "/mcp"


def test_mcp_transport_parses_http():
    """The transport field accepts 'http'."""
    assert Settings(mcp={"transport": "http"}).mcp.transport is Transport.HTTP


def test_http_security_locks_to_configured_origin():
    """The HTTP transport enables DNS-rebinding protection scoped to its origin."""
    s = mcp_server._security_settings(McpSettings(host="127.0.0.1", port=8181))
    assert s.enable_dns_rebinding_protection
    assert "127.0.0.1:8181" in s.allowed_hosts
    assert "localhost:8181" in s.allowed_hosts
    assert "http://127.0.0.1:8181" in s.allowed_origins
    assert "http://evil.test" not in s.allowed_origins


def test_mcp_app_mounts_configured_path():
    """build_app mounts the server at the configured path."""
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            mode="mcp",
            mcp={"host": "0.0.0.0", "port": 9000, "path": "/bowerbot"},
            projects_dir=Path(tmp) / "scenes",
            assets_dir=Path(tmp) / "assets",
        )
        app = mcp_server.build_app(settings)
        assert [r.path for r in app.routes] == ["/bowerbot"]


# ── tool_router ──


def test_combined_schemas_include_core_tools():
    """The combined tool list includes core tools."""
    with tempfile.TemporaryDirectory() as tmp:
        registry = SkillRegistry()
        registry.load_from_settings(_settings(tmp))
        names = {
            s["function"]["name"]
            for s in tool_router.combined_tool_schemas(registry)
        }
        assert "create_project" in names
        assert "place_asset" in names


def test_router_dispatches_core_tool():
    """route() sends a core tool to the dispatcher."""
    with tempfile.TemporaryDirectory() as tmp:
        settings = _settings(tmp)
        state = SceneState.from_settings(settings)
        registry = SkillRegistry()
        registry.load_from_settings(settings)
        r = asyncio.run(
            tool_router.route(
                state, registry, "create_project",
                {"name": "R", "up_axis": "Y", "meters_per_unit": 1.0},
            ),
        )
        assert r.success, r.error
        assert state.project.name == "R"


def test_router_dispatches_skill_tool():
    """route() sends a skill-namespaced tool to the registry."""

    class _StubSkill:
        name = "stub"
        cache_subdir = None

        def validate_config(self):
            pass

        def get_tools(self):
            return []

        def get_skill_prompt(self):
            return ""

        @property
        def category(self):
            return SkillCategory.ASSET_PROVIDER

        async def execute(self, tool_name, params, ctx):
            return ToolResult(success=True, data={"echo": tool_name})

    with tempfile.TemporaryDirectory() as tmp:
        state = SceneState.from_settings(_settings(tmp))
        registry = SkillRegistry()
        registry._skills["stub"] = _StubSkill()
        registry._library_dir = Path(tmp)
        r = asyncio.run(
            tool_router.route(state, registry, "stub__ping", {}),
        )
        assert r.success, r.error
        assert r.data == {"echo": "ping"}


# ── MCP server over the protocol ──


async def _list_tools(server):
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        return (await client.list_tools()).tools


async def _call_tool(server, name, args):
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        return await client.call_tool(name, args)


def test_mcp_lists_tools_over_protocol():
    """A connected client sees the core tool surface."""
    with tempfile.TemporaryDirectory() as tmp:
        server, _ = _server_and_state(tmp)
        tools = asyncio.run(_list_tools(server))
        names = {t.name for t in tools}
        assert "create_project" in names
        assert "place_asset" in names
        assert "apply_physics_api" in names


def test_mcp_call_tool_over_protocol():
    """A client call_tool focuses the server's project."""
    with tempfile.TemporaryDirectory() as tmp:
        server, state = _server_and_state(tmp)
        result = asyncio.run(_call_tool(
            server, "create_project",
            {"name": "Proto", "up_axis": "Y", "meters_per_unit": 1.0},
        ))
        assert not result.isError
        assert state.project.name == "Proto"


def test_mcp_call_error_is_flagged():
    """A failing tool call comes back as an MCP error."""
    with tempfile.TemporaryDirectory() as tmp:
        server, _ = _server_and_state(tmp)
        result = asyncio.run(_call_tool(server, "open_project", {"name": "ghost"}))
        assert result.isError
