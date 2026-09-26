# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""SkillRegistry — discover skills via entry points and route tool calls."""

from __future__ import annotations

import inspect
import logging
from dataclasses import replace
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bowerbot.config import Settings
from bowerbot.logging_setup import log_tool_result
from bowerbot.schemas import SkillRules
from bowerbot.skills.base import (
    Skill,
    SkillConfigError,
    SkillContext,
    Tool,
    ToolResult,
)

if TYPE_CHECKING:
    from bowerbot.state import SceneState

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Central registry for all BowerBot skills."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._not_configured: dict[str, str] = {}
        self._disabled: list[str] = []
        self._library_dir: Path | None = None

    def register(self, skill: Skill) -> None:
        """Register a skill instance after its config validates."""
        skill.validate_config()
        self._skills[skill.name] = skill

    def load_from_settings(self, settings: Settings) -> None:
        """Discover and load every installed skill that config doesn't disable.

        An installed skill is on by default: a missing config block, or
        a block without ``enabled``, loads it. Only ``"enabled": false``
        turns it off.
        """
        self._library_dir = Path(settings.assets_dir)

        discovered = entry_points(group=SkillRules.ENTRY_POINT_GROUP)
        for ep in discovered:
            self._load_one_entry_point(ep, settings)

        discovered_names = {ep.name for ep in discovered}
        for skill_name, skill_config in settings.skills.items():
            if skill_config.enabled and skill_name not in discovered_names:
                logger.warning(
                    "Skill '%s' is enabled in config but not installed. "
                    "Install it with: pip install bowerbot-skill-%s",
                    skill_name, skill_name,
                )

    def _load_one_entry_point(self, ep: Any, settings: Settings) -> None:
        """Instantiate and register a single discovered skill.

        Skips it when config disables it, when the entry-point name
        does not match the skill class's ``name`` attribute, or when
        ``validate_config`` raises ``SkillConfigError``. A skill that
        needs settings nobody gave it yet is noted quietly as not
        configured; settings that fail validation are a warning.
        """
        ep_name = ep.name
        skill_config = settings.skills.get(ep_name)
        if skill_config and not skill_config.enabled:
            self._disabled.append(ep_name)
            return

        config = skill_config.config if skill_config else {}
        try:
            skill_cls = ep.load()
            if not config:
                try:
                    inspect.signature(skill_cls).bind()
                except TypeError as e:
                    self._not_configured[ep_name] = f"its settings are missing ({e})"
                    logger.info(
                        "Skill '%s' is installed but not configured: %s", ep_name, e,
                    )
                    return
            skill = skill_cls(**config)
        except Exception:
            logger.warning(
                "Failed to load skill: %s (%s)",
                ep_name, ep.value, exc_info=True,
            )
            return

        if skill.name != ep_name:
            logger.error(
                "Skill name mismatch: entry point '%s' loaded a skill whose "
                "name attribute is '%s'. The two must match. Skipping.",
                ep_name, skill.name,
            )
            return

        try:
            self.register(skill)
            logger.info("Loaded skill: %s (%s)", ep_name, ep.value)
        except SkillConfigError as e:
            if skill_config and skill_config.config:
                logger.warning(
                    "Skill '%s' is misconfigured and will be skipped: %s",
                    ep_name, e,
                )
                return
            self._not_configured[ep_name] = str(e)
            logger.info(
                "Skill '%s' is installed but not configured: %s",
                ep_name, e,
            )

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Return every enabled skill's tools in LLM schema format."""
        tools = []
        for skill_name, skill in self._skills.items():
            for tool in skill.get_tools():
                schema = tool.to_llm_schema()
                schema["function"]["name"] = f"{skill_name}__{tool.name}"
                tools.append(schema)
        return tools

    def get_tool_definitions(self) -> list[Tool]:
        """Every enabled skill's tools, each named ``<skill>__<tool>`` as clients call it."""
        return [
            replace(tool, name=f"{skill_name}__{tool.name}")
            for skill_name, skill in self._skills.items()
            for tool in skill.get_tools()
        ]

    def get_skill_prompts(self) -> str:
        """Concatenate every enabled skill's SKILL.md content."""
        prompts = [
            p for p in (s.get_skill_prompt() for s in self._skills.values()) if p
        ]
        return "\n\n---\n\n".join(prompts)

    async def execute_tool(
        self,
        qualified_name: str,
        params: dict[str, Any],
        state: SceneState | None = None,
    ) -> ToolResult:
        """Execute a tool by its qualified name (``skill__tool``)."""
        parts = qualified_name.split("__", 1)
        if len(parts) != 2:
            result = ToolResult(
                success=False, error=f"Invalid tool name: {qualified_name}",
            )
            log_tool_result(logger, qualified_name, result)
            return result

        skill_name, tool_name = parts
        skill = self._skills.get(skill_name)
        if skill is None:
            result = ToolResult(
                success=False, error=f"Skill not found: {skill_name}",
            )
            log_tool_result(logger, qualified_name, result)
            return result

        ctx = self._build_context(skill, state)
        try:
            result = await skill.execute(tool_name, params, ctx)
        except Exception as e:
            logger.exception(
                "skill-crash name=%s", qualified_name,
            )
            result = ToolResult(
                success=False,
                error=f"{qualified_name} crashed: {e}",
            )
        log_tool_result(logger, qualified_name, result)
        return result

    def _build_context(
        self, skill: Skill, state: SceneState | None,
    ) -> SkillContext:
        """Build a fresh :class:`SkillContext` for a single tool call."""
        if self._library_dir is None:
            msg = "SkillRegistry.load_from_settings was not called"
            raise RuntimeError(msg)

        cache_dir: Path | None = None
        if skill.cache_subdir:
            cache_dir = self._library_dir / skill.cache_subdir
            cache_dir.mkdir(parents=True, exist_ok=True)

        return SkillContext(
            library_dir=self._library_dir,
            cache_dir=cache_dir,
            project_dir=state.project_dir if state else None,
            scene_path=state.stage_path if state else None,
        )

    @property
    def enabled_skills(self) -> list[str]:
        return list(self._skills.keys())

    @property
    def not_configured_skills(self) -> dict[str, str]:
        """Installed skills that need settings, each with what is missing."""
        return dict(self._not_configured)

    @property
    def disabled_skills(self) -> list[str]:
        """Installed skills that config turns off with ``"enabled": false``."""
        return list(self._disabled)

    @property
    def skill_count(self) -> int:
        return len(self._skills)
