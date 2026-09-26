# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Skill schemas — how BowerBot discovers installed skills."""


class SkillRules:
    """What makes an installed package a BowerBot skill."""

    # Entry-point group a skill package registers its Skill class under.
    ENTRY_POINT_GROUP = "bowerbot.skills"
