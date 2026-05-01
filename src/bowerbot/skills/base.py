# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Skill contract.

Every asset provider, DCC connector, simulation runtime, or storage
backend implements :class:`Skill`. The :class:`SkillRegistry` discovers
skills via Python entry points and routes tool calls to them.

A :class:`SkillContext` is built fresh on each execute call and gives
the skill read-only access to the user's library and the currently
open project / scene without coupling the skill to ``SceneState``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class SkillConfigError(Exception):
    """Raised by :meth:`Skill.validate_config` when a skill is misconfigured.

    The registry catches it, logs the message, and skips the skill so
    the rest of BowerBot keeps running. Skill authors should raise it
    with a clear, actionable message naming the missing or invalid
    setting.
    """


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
    """Read-only execution context passed to :meth:`Skill.execute`.

    Constructed fresh for every tool call so a skill always sees the
    current project and scene state. Skills should treat all paths as
    read-only references and write only into ``cache_dir`` (their own
    download space) or into the project via paths the user opted into.

    Attributes:
        library_dir: User's curated asset library
            (``settings.assets_dir``).
        cache_dir: This skill's download dir
            (``library_dir / cache_subdir``), or ``None`` if the skill
            did not declare a ``cache_subdir``.
        project_dir: Root of the currently open project, or ``None``.
        scene_path: Composed scene file (``<project>/scene.usda``), or
            ``None`` if no scene is open. Skills that need stage
            access call ``Usd.Stage.Open(scene_path)`` themselves to
            get a snapshot they own.
    """

    library_dir: Path
    cache_dir: Path | None = None
    project_dir: Path | None = None
    scene_path: Path | None = None


class Skill(ABC):
    """Base class for all BowerBot skills.

    Concrete skills declare ``name``, ``category``, and (for skills
    that download files) ``cache_subdir``. They implement
    :meth:`get_tools`, :meth:`execute`, and :meth:`validate_config`.

    Skills receive a :class:`SkillContext` on every execute call and
    should never store paths from it across calls; build context is
    rebuilt every time a tool fires so the project / scene reflects
    the user's current state.
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
        """Verify the skill's configuration is complete and valid.

        Raise :class:`SkillConfigError` with a clear message when a
        required setting is missing or wrong. The registry logs the
        message and skips the skill so BowerBot keeps running.
        """

    def get_skill_prompt(self) -> str:
        """Load this skill's ``SKILL.md`` content for the system prompt."""
        module_file = Path(
            __import__(self.__class__.__module__, fromlist=[""]).__file__,
        )
        skill_md = module_file.parent / "SKILL.md"
        if skill_md.exists():
            return skill_md.read_text(encoding="utf-8")
        return ""
