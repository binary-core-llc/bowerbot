# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""SkillRegistry — discover skills via entry points and route tool calls."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bowerbot.config import Settings
from bowerbot.skills.base import (
    Skill,
    SkillConfigError,
    SkillContext,
    ToolResult,
)
from bowerbot.utils import diagnostic_registry_utils

if TYPE_CHECKING:
    from bowerbot.state import SceneState

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "bowerbot.skills"


class SkillRegistry:
    """Central registry for all BowerBot skills."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._library_dir: Path | None = None

    def register(self, skill: Skill) -> None:
        """Register a skill instance after its config validates."""
        skill.validate_config()
        self._skills[skill.name] = skill
        skill.register_diagnostic_checks(diagnostic_registry_utils)

    def load_from_settings(self, settings: Settings) -> None:
        """Discover and load all enabled skills from entry points."""
        self._library_dir = Path(settings.assets_dir)

        discovered = entry_points(group=ENTRY_POINT_GROUP)
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

        Skips with a clear log message on any of three failure modes:
        the skill is disabled in config, the entry-point name does not
        match the skill class's ``name`` attribute, or the skill is
        misconfigured (``SkillConfigError``).
        """
        ep_name = ep.name
        skill_config = settings.skills.get(ep_name)
        if skill_config and not skill_config.enabled:
            return

        try:
            skill_cls = ep.load()
            config = skill_config.config if skill_config else {}
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
            logger.warning(
                "Skill '%s' is misconfigured and will be skipped: %s",
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
            return ToolResult(
                success=False, error=f"Invalid tool name: {qualified_name}",
            )

        skill_name, tool_name = parts
        skill = self._skills.get(skill_name)
        if skill is None:
            return ToolResult(success=False, error=f"Skill not found: {skill_name}")

        ctx = self._build_context(skill, state)
        return await skill.execute(tool_name, params, ctx)

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
    def skill_count(self) -> int:
        return len(self._skills)
