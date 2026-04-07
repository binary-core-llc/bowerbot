# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Base skill interface.

Every asset provider, DCC connector, or storage backend
implements this interface. The AgentRuntime discovers skills
through the SkillRegistry and exposes their tools to the LLM.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class SkillCategory(StrEnum):
    """What kind of skill this is."""

    ASSET_PROVIDER = "asset_provider"
    DCC = "dcc"
    STORAGE = "storage"


@dataclass
class Tool:
    """A single tool/function that a skill exposes to the LLM."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_llm_schema(self) -> dict[str, Any]:
        """Convert to the OpenAI function-calling schema format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolResult:
    """Result returned from executing a tool."""

    success: bool
    data: Any = None
    error: str | None = None


class Skill(ABC):
    """Base class for all BowerBot skills."""

    name: str
    category: SkillCategory
    cache_subdir: str = ""

    _assets_dir: Path | None = None

    @property
    def assets_dir(self) -> Path:
        """Root asset directory, set by the registry."""
        if self._assets_dir is None:
            msg = "assets_dir not set. Skill must be registered through SkillRegistry."
            raise RuntimeError(msg)
        return self._assets_dir

    @assets_dir.setter
    def assets_dir(self, value: Path) -> None:
        self._assets_dir = value

    @property
    def cache_dir(self) -> Path:
        """Download directory for provider skills (assets_dir / cache_subdir)."""
        if not self.cache_subdir:
            msg = f"Skill '{self.name}' has no cache_subdir defined."
            raise RuntimeError(msg)
        path = self.assets_dir / self.cache_subdir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @abstractmethod
    def get_tools(self) -> list[Tool]:
        """Return the list of tools this skill provides."""

    @abstractmethod
    async def execute(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        """Execute a tool by name with the given parameters."""

    @abstractmethod
    def validate_config(self) -> bool:
        """Check if this skill is properly configured."""

    def get_skill_prompt(self) -> str:
        """Load the SKILL.md file for this skill, if it exists.

        Returns the markdown content to be injected into the system prompt
        when this skill is active. Returns empty string if no SKILL.md found.
        """
        # Look for SKILL.md next to the module file
        module_file = Path(__import__(self.__class__.__module__, fromlist=[""]).__file__)
        skill_md = module_file.parent / "SKILL.md"

        if skill_md.exists():
            return skill_md.read_text(encoding="utf-8")
        return ""
