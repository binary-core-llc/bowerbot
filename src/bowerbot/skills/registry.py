# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""SkillRegistry — manages all available skills.

The registry loads skills based on the user's config, validates
their configuration, and provides a unified tool list and skill
prompts to the AgentRuntime.
"""

from pathlib import Path
from typing import Any

from bowerbot.config import Settings
from bowerbot.skills.base import Skill, ToolResult


class SkillRegistry:
    """Central registry for all BowerBot skills."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill, assets_dir: Path | None = None) -> None:
        """Register a skill instance and set its assets_dir."""
        if assets_dir is not None:
            skill.assets_dir = assets_dir
        if skill.validate_config():
            self._skills[skill.name] = skill

    def load_from_settings(self, settings: Settings) -> None:
        """Auto-discover and load skills based on settings."""
        from bowerbot.skills.assembly import AssemblySkill
        from bowerbot.skills.local import LocalSkill
        from bowerbot.skills.sketchfab import SketchfabSkill
        from bowerbot.skills.textures import TexturesSkill

        assets_dir = Path(settings.assets_dir)

        builtin_skills: dict[str, type[Skill]] = {
            "local": LocalSkill,
            "sketchfab": SketchfabSkill,
            "textures": TexturesSkill,
        }

        for skill_name, skill_config in settings.skills.items():
            if not skill_config.enabled:
                continue
            if skill_name in builtin_skills:
                skill_cls = builtin_skills[skill_name]
                skill = skill_cls(**skill_config.config)
                self.register(skill, assets_dir=assets_dir)

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
                schema["function"]["name"] = f"{skill_name}__{tool.name}"
                tools.append(schema)
        return tools

    def get_skill_prompts(self) -> str:
        """Collect SKILL.md content from all enabled skills.

        Returns a combined string of all skill prompts,
        only for skills that are currently active.
        """
        prompts = []
        for skill_name, skill in self._skills.items():
            prompt = skill.get_skill_prompt()
            if prompt:
                prompts.append(prompt)
        return "\n\n---\n\n".join(prompts)

    async def execute_tool(self, qualified_name: str, params: dict[str, Any]) -> ToolResult:
        """Execute a tool by its qualified name (skill__tool_name)."""
        parts = qualified_name.split("__", 1)
        if len(parts) != 2:
            return ToolResult(success=False, error=f"Invalid tool name: {qualified_name}")

        skill_name, tool_name = parts
        skill = self._skills.get(skill_name)
        if skill is None:
            return ToolResult(success=False, error=f"Skill not found: {skill_name}")

        return await skill.execute(tool_name, params)

    @property
    def enabled_skills(self) -> list[str]:
        return list(self._skills.keys())

    @property
    def skill_count(self) -> int:
        return len(self._skills)
