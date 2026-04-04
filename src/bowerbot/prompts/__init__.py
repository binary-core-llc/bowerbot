# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Prompt loading for the agent and scene builder.

Prompts are stored as .md files alongside this module. They are
content, not code — prompt engineers can edit them without touching
Python, and diffs stay clean.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Load a prompt file by name (without extension).

    Args:
        name: Prompt file stem (e.g. ``"core"`` loads ``core.md``).

    Returns:
        The prompt text with trailing whitespace stripped.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()
