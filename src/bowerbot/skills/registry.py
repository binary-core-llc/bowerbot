# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""SkillRegistry — discovers and manages all available skills.

Skills are discovered from two sources:
1. Python entry points (group: "bowerbot.skills") — both
   built-in and pip-installed skills register this way.
2. The assembly skill — always loaded as the core skill.

To register a skill via entry points, add to pyproject.toml:

    [project.entry-points."bowerbot.skills"]
    my_skill = "my_package:MySkillClass"

Then ``pip install my-package`` makes the skill available
to BowerBot automatically.
"""

import logging
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from bowerbot.config import Settings
from bowerbot.skills.assembly import AssemblySkill
from bowerbot.skills.base import Skill, ToolResult

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "bowerbot.skills"


class SkillRegistry:
    """Central registry for all BowerBot skills."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(
        self, skill: Skill, assets_dir: Path | None = None,
    ) -> None:
        """Register a skill instance and set its assets_dir."""
        if assets_dir is not None:
            skill.assets_dir = assets_dir
        if skill.validate_config():
            self._skills[skill.name] = skill

    def load_from_settings(self, settings: Settings) -> None:
        """Discover and load all skills.

        Loads skills from Python entry points and registers
        the assembly core skill. Skills are only loaded if
        enabled in the user's settings.
        """
        assets_dir = Path(settings.assets_dir)

        # Discover skills from entry points
        discovered = entry_points(group=ENTRY_POINT_GROUP)
        for ep in discovered:
            skill_name = ep.name
            skill_config = settings.skills.get(skill_name)

            if skill_config and not skill_config.enabled:
                continue

            try:
                skill_cls = ep.load()
                config = (
                    skill_config.config if skill_config else {}
                )
                skill = skill_cls(**config)
                self.register(skill, assets_dir=assets_dir)
                logger.info(
                    "Loaded skill: %s (%s)",
                    skill_name, ep.value,
                )
            except Exception:
                logger.warning(
                    "Failed to load skill: %s (%s)",
                    skill_name,
                    ep.value,
                    exc_info=True,
                )

        # Warn about configured skills that weren't found
        discovered_names = {ep.name for ep in discovered}
        for skill_name, skill_config in settings.skills.items():
            if (
                skill_config.enabled
                and skill_name not in discovered_names
                and skill_name != "assembly"
            ):
                logger.warning(
                    "Skill '%s' is enabled in config but "
                    "not installed. Install it with: "
                    "pip install bowerbot-skill-%s",
                    skill_name,
                    skill_name,
                )

        # Assembly skill is always registered
        assembly = AssemblySkill(
            scene_defaults=settings.scene_defaults,
        )
        self.register(assembly, assets_dir=assets_dir)

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Get all tools from all enabled skills in LLM schema format."""
        tools = []
        for skill_name, skill in self._skills.items():
            for tool in skill.get_tools():
                schema = tool.to_llm_schema()
                schema["function"]["name"] = (
                    f"{skill_name}__{tool.name}"
                )
                tools.append(schema)
        return tools

    def get_skill_prompts(self) -> str:
        """Collect SKILL.md content from all enabled skills."""
        prompts = []
        for skill in self._skills.values():
            prompt = skill.get_skill_prompt()
            if prompt:
                prompts.append(prompt)
        return "\n\n---\n\n".join(prompts)

    async def execute_tool(
        self, qualified_name: str, params: dict[str, Any],
    ) -> ToolResult:
        """Execute a tool by its qualified name (skill__tool_name)."""
        parts = qualified_name.split("__", 1)
        if len(parts) != 2:
            return ToolResult(
                success=False,
                error=f"Invalid tool name: {qualified_name}",
            )

        skill_name, tool_name = parts
        skill = self._skills.get(skill_name)
        if skill is None:
            return ToolResult(
                success=False,
                error=f"Skill not found: {skill_name}",
            )

        return await skill.execute(tool_name, params)

    @property
    def enabled_skills(self) -> list[str]:
        return list(self._skills.keys())

    @property
    def skill_count(self) -> int:
        return len(self._skills)
