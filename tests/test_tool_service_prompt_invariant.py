# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Enforce the tool/service/prompt 1:1:1 invariant.

Every public function in ``src/bowerbot/tools/*_tools.py`` must have a
same-named public function in the matching ``src/bowerbot/services/*_service.py``
and must be mentioned in some ``src/bowerbot/prompts/*.md`` file.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "src" / "bowerbot" / "tools"
SERVICES_DIR = ROOT / "src" / "bowerbot" / "services"
PROMPTS_DIR = ROOT / "src" / "bowerbot" / "prompts"

SKIP_TOOL_FILES = {"__init__.py", "_helpers.py"}
SKIP_SERVICE_FILES = {"__init__.py"}


def _public_functions(path: Path) -> list[str]:
    """Return every top-level function name not prefixed with ``_``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]


def _domain_from_filename(path: Path, suffix: str) -> str:
    """``light_tools.py`` -> ``light`` (suffix=``_tools``)."""
    return path.stem.removesuffix(suffix)


def test_every_tool_has_same_named_service():
    """Each public tool function must have an identically-named service function."""
    mismatches: list[str] = []
    for tool_file in sorted(TOOLS_DIR.glob("*.py")):
        if tool_file.name in SKIP_TOOL_FILES:
            continue
        domain = _domain_from_filename(tool_file, "_tools")
        service_file = SERVICES_DIR / f"{domain}_service.py"
        assert service_file.exists(), (
            f"{tool_file.name} has no matching {service_file.name}"
        )
        tools = set(_public_functions(tool_file))
        services = set(_public_functions(service_file))
        missing_in_service = sorted(tools - services)
        extra_in_service = sorted(services - tools)
        if missing_in_service:
            mismatches.append(
                f"{domain}: tools without same-named service: {missing_in_service}",
            )
        if extra_in_service:
            mismatches.append(
                f"{domain}: service functions without same-named tool: {extra_in_service}",
            )
    assert not mismatches, "tool/service mismatches:\n" + "\n".join(mismatches)


def test_every_tool_is_mentioned_in_some_prompt():
    """Each public tool function must appear by name in at least one prompts/*.md."""
    prompt_text = "\n".join(
        p.read_text(encoding="utf-8") for p in PROMPTS_DIR.glob("*.md")
    )
    undocumented: list[str] = []
    for tool_file in sorted(TOOLS_DIR.glob("*.py")):
        if tool_file.name in SKIP_TOOL_FILES:
            continue
        for name in _public_functions(tool_file):
            if name not in prompt_text:
                undocumented.append(f"{tool_file.name}:{name}")
    assert not undocumented, (
        "tools with no prompt mention:\n" + "\n".join(undocumented)
    )
