# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Prompt loading from markdown files."""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Return the text of the prompt file *name* (given without extension)."""
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()
