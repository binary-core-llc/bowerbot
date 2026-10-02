# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Skill contract: the base class, its tool and result types, and the per-call context."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
from pathlib import Path
from typing import Any


class SkillConfigError(Exception):
    """Raised by ``Skill.validate_config`` when a skill is misconfigured; the registry skips it."""


class SkillCategory(StrEnum):
    """What kind of skill this is."""

    ASSET_PROVIDER = "asset_provider"
    DCC = "dcc"
    STORAGE = "storage"
    SIMULATION = "simulation"


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


@dataclass(frozen=True)
class SkillContext:
    """Read-only context passed to ``Skill.execute``, rebuilt on every call.

    ``library_dir`` is the user's asset library and ``cache_dir`` the skill's download
    folder (None without a ``cache_subdir``); ``project_dir`` and ``scene_path`` are the
    open project and its scene (None when nothing is open).
    """

    library_dir: Path
    cache_dir: Path | None = None
    project_dir: Path | None = None
    scene_path: Path | None = None


class Skill(ABC):
    """Base class for all BowerBot skills.

    Subclasses set ``name``, ``category`` and optionally ``cache_subdir``, and
    implement ``get_tools``, ``execute`` and ``validate_config``.
    """

    name: str
    category: SkillCategory
    cache_subdir: str = ""

    @abstractmethod
    def get_tools(self) -> list[Tool]:
        """Return the list of tools this skill provides."""

    @abstractmethod
    async def execute(
        self, tool_name: str, params: dict[str, Any], ctx: SkillContext,
    ) -> ToolResult:
        """Execute a tool by name with the given parameters."""

    @abstractmethod
    def validate_config(self) -> None:
        """Raise ``SkillConfigError`` when a required setting is missing or wrong."""

    def get_skill_prompt(self) -> str:
        """Load this skill's ``SKILL.md`` content for the system prompt."""
        module_file = Path(
            __import__(self.__class__.__module__, fromlist=[""]).__file__,
        )
        skill_md = module_file.parent / "SKILL.md"
        if skill_md.exists():
            return skill_md.read_text(encoding="utf-8")
        return ""

