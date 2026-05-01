# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot Skills SDK.

This package is the public contract that external skill authors depend
on. It is intentionally small: the contract types, the registry that
discovers skills via entry points, and nothing else. Built-in and
third-party skills are distributed as separate packages and discovered
at runtime; they do **not** live in this directory.

Skill authors import from here, not from submodules:

    from bowerbot.skills import (
        Skill,
        SkillCategory,
        SkillConfigError,
        SkillContext,
        Tool,
        ToolResult,
    )

These names follow semver. Breaking changes are reserved for major
version bumps; external skill packages depend on a compatible bowerbot
range in their own ``pyproject.toml`` and trust this surface.
"""

from bowerbot.skills.base import (
    Skill,
    SkillCategory,
    SkillConfigError,
    SkillContext,
    Tool,
    ToolResult,
)
from bowerbot.skills.registry import SkillRegistry

__all__ = [
    "Skill",
    "SkillCategory",
    "SkillConfigError",
    "SkillContext",
    "SkillRegistry",
    "Tool",
    "ToolResult",
]
