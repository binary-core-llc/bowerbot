# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for the structured file logging setup."""

from __future__ import annotations

import logging

import pytest

from bowerbot.config import LLMSettings, LoggingSettings, Settings
from bowerbot.logging_setup import (
    configure_logging,
    log_tool_result,
    sanitize,
    session_id,
)
from bowerbot.skills.base import ToolResult


@pytest.fixture(autouse=True)
def _reset_bowerbot_logging():
    """Restore the bowerbot logger after each test (avoid bleed into other suites)."""
    yield
    root = logging.getLogger("bowerbot")
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.propagate = True
    root.setLevel(logging.WARNING)


def _settings_with_logging(tmp_path, monkeypatch, **logging_kwargs) -> Settings:
    """Build a Settings instance with logging routed under *tmp_path*."""
    monkeypatch.setattr("bowerbot.logging_setup.BOWERBOT_HOME", tmp_path)
    return Settings(
        llm=LLMSettings(model="gpt-4.1", api_key="dummy"),
        logging=LoggingSettings(**logging_kwargs),
    )


def test_configure_logging_creates_log_file(tmp_path, monkeypatch):
    settings = _settings_with_logging(tmp_path, monkeypatch)
    log_file = configure_logging(settings)

    assert log_file is not None
    assert log_file == tmp_path / "logs" / "bowerbot.log"
    logger = logging.getLogger("bowerbot.test")
    logger.info("hello")
    for handler in logging.getLogger("bowerbot").handlers:
        handler.flush()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "session-start" in content
    assert "hello" in content
    assert session_id() in content


def test_configure_logging_disabled_returns_none(tmp_path, monkeypatch):
    settings = _settings_with_logging(tmp_path, monkeypatch, enabled=False)
    log_file = configure_logging(settings)
    assert log_file is None

    logger = logging.getLogger("bowerbot.test")
    logger.warning("should not crash")


def test_configure_logging_is_idempotent(tmp_path, monkeypatch):
    settings = _settings_with_logging(tmp_path, monkeypatch)
    configure_logging(settings)
    handlers_first = list(logging.getLogger("bowerbot").handlers)
    configure_logging(settings)
    handlers_second = list(logging.getLogger("bowerbot").handlers)

    # Same number of handlers after second call (old ones get replaced).
    assert len(handlers_first) == len(handlers_second)


def test_configure_logging_does_not_propagate_to_root(tmp_path, monkeypatch):
    settings = _settings_with_logging(tmp_path, monkeypatch)
    configure_logging(settings)
    assert logging.getLogger("bowerbot").propagate is False


def test_sanitize_redacts_secret_keys():
    payload = {
        "api_key": "sk-abc",
        "API_KEY": "sk-def",
        "auth_token": "tok-xyz",
        "password": "hunter2",
        "client_secret": "sssh",
        "prim_path": "/Scene/Foo",
    }
    out = sanitize(payload)
    assert out["api_key"] == "[REDACTED]"
    assert out["API_KEY"] == "[REDACTED]"
    assert out["auth_token"] == "[REDACTED]"
    assert out["password"] == "[REDACTED]"
    assert out["client_secret"] == "[REDACTED]"
    assert out["prim_path"] == "/Scene/Foo"


def test_sanitize_recurses_into_nested_structures():
    payload = {
        "config": {
            "skills": {
                "sketchfab": {"token": "tok123", "enabled": True},
            },
        },
        "items": [
            {"api_key": "leak", "name": "ok"},
        ],
    }
    out = sanitize(payload)
    assert out["config"]["skills"]["sketchfab"]["token"] == "[REDACTED]"
    assert out["config"]["skills"]["sketchfab"]["enabled"] is True
    assert out["items"][0]["api_key"] == "[REDACTED]"
    assert out["items"][0]["name"] == "ok"


def test_sanitize_truncates_long_strings():
    long_val = "x" * 500
    out = sanitize({"some_field": long_val})
    assert len(out["some_field"]) < len(long_val)
    assert out["some_field"].endswith("[+300]")


def test_logger_writes_with_session_prefix(tmp_path, monkeypatch):
    settings = _settings_with_logging(tmp_path, monkeypatch)
    log_file = configure_logging(settings)

    logger = logging.getLogger("bowerbot.dispatcher")
    logger.info("tool-call name=test params={}")
    for handler in logging.getLogger("bowerbot").handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if "tool-call" in line]
    assert lines
    sid = session_id()
    assert any(sid in line for line in lines)


def test_log_tool_result_ok(caplog):
    """Success result emits tool-ok with the tool name."""
    logger = logging.getLogger("bowerbot.test")
    with caplog.at_level(logging.INFO, logger="bowerbot.test"):
        log_tool_result(
            logger, "create_light", ToolResult(success=True, data={}),
        )
    msgs = [r.message for r in caplog.records]
    assert any("tool-ok name=create_light" in m for m in msgs)


def test_log_tool_result_error(caplog):
    """Failure result emits tool-error with the error message."""
    logger = logging.getLogger("bowerbot.test")
    with caplog.at_level(logging.INFO, logger="bowerbot.test"):
        log_tool_result(
            logger, "create_light",
            ToolResult(success=False, error="boom"),
        )
    msgs = [r.message for r in caplog.records]
    assert any(
        "tool-error name=create_light" in m and "boom" in m
        for m in msgs
    )


def test_skill_tool_call_logs_uniformly_with_core(caplog):
    """Skill tool calls produce identical tool-ok / tool-error lines."""
    import asyncio

    from bowerbot.skills.base import SkillCategory
    from bowerbot.skills.registry import SkillRegistry

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
            if tool_name == "ok":
                return ToolResult(success=True, data={"hi": "there"})
            return ToolResult(success=False, error="bad request")

    registry = SkillRegistry()
    registry._skills["stub"] = _StubSkill()
    registry._library_dir = tmp = __import__("pathlib").Path(".")
    del tmp

    with caplog.at_level(logging.INFO, logger="bowerbot.skills.registry"):
        asyncio.run(registry.execute_tool("stub__ok", {}))
        asyncio.run(registry.execute_tool("stub__bad", {}))

    msgs = [r.message for r in caplog.records]
    assert any("tool-ok name=stub__ok" in m for m in msgs)
    assert any(
        "tool-error name=stub__bad" in m and "bad request" in m
        for m in msgs
    )


def test_skill_crash_logs_tool_error(caplog):
    """A skill that raises gets converted to a tool-error log line."""
    import asyncio

    from bowerbot.skills.base import SkillCategory
    from bowerbot.skills.registry import SkillRegistry

    class _CrashSkill:
        name = "crashy"
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
            raise RuntimeError("kaboom")

    registry = SkillRegistry()
    registry._skills["crashy"] = _CrashSkill()
    registry._library_dir = __import__("pathlib").Path(".")

    with caplog.at_level(logging.INFO, logger="bowerbot.skills.registry"):
        result = asyncio.run(registry.execute_tool("crashy__any", {}))

    assert result.success is False
    assert "kaboom" in result.error
    msgs = [r.message for r in caplog.records]
    assert any("tool-error name=crashy__any" in m for m in msgs)


def test_rotating_handler_respects_max_bytes(tmp_path, monkeypatch):
    settings = _settings_with_logging(
        tmp_path, monkeypatch, max_bytes=1024, backup_count=2,
    )
    log_file = configure_logging(settings)

    logger = logging.getLogger("bowerbot.test")
    payload = "x" * 200
    for _ in range(20):
        logger.info("filler %s", payload)
    for handler in logging.getLogger("bowerbot").handlers:
        handler.flush()

    rotated = list((tmp_path / "logs").glob("bowerbot.log*"))
    assert log_file in rotated
    assert len(rotated) >= 2
