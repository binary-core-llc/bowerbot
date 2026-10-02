# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""BowerBot Skills SDK: the contract types and the registry that discovers skills.

External skill packages import from here; these names follow semver.
"""

from bowerbot.skills.base import Skill
from bowerbot.skills.base import SkillCategory
from bowerbot.skills.base import SkillConfigError
from bowerbot.skills.base import SkillContext
from bowerbot.skills.base import Tool
from bowerbot.skills.base import ToolResult
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
