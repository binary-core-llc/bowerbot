# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Prompt loading from markdown files."""

from __future__ import annotations

from pathlib import Path


def load_prompt(name: str) -> str:
    """Load a prompt file by name (without extension).

    Args:
        name: Prompt file stem (e.g. ``"core"`` loads ``core.md``).

    Returns:
        The prompt text with trailing whitespace stripped.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    path = Path(__file__).parent / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()
