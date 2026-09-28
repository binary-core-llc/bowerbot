# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The golden scenarios cover every tool fully.

Every tool is called and succeeds at least once; every parameter (nested ones
included) and every allowed value is used at least once; and every tool is
refused at least once, except the ones listed in NEVER_REFUSED with the reason.
A tool or parameter added later fails this test until a scenario records it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from bowerbot import dispatcher
from tests.golden.scenarios import SCENARIOS

EXPECTED = Path(__file__).parent / "golden" / "expected"

# Tools no input or state can make refuse today; each is a recorded finding.
NEVER_REFUSED = {
    "compute_grid_layout": "accepts a negative count and spacing",
    "get_current_project": "takes no input; an unknown parameter is not refused",
    "list_projects": "takes no input; an unknown parameter is not refused",
    "list_camera_properties": "takes no input; an unknown parameter is not refused",
}

_OUTCOME = re.compile(
    r"^=== step \d+: (\w+)\n(?:intent:.*\n)?\nSUMMARY\n  call:.*\n  current project:.*\n"
    r"  said: (\w+)",
    re.M,
)


def _schema_params(schema: dict[str, Any], prefix: str = "") -> dict[str, dict[str, Any]]:
    """Every parameter of a tool's schema by dotted name, nested objects and list items too."""
    found: dict[str, dict[str, Any]] = {}
    for key, spec in schema.get("properties", {}).items():
        found[prefix + key] = spec
        nested = spec if spec.get("type") == "object" else spec.get("items")
        if isinstance(nested, dict) and "properties" in nested:
            found.update(_schema_params(nested, f"{prefix}{key}."))
    return found


def _usage() -> tuple[dict[str, set[str]], dict[tuple[str, str], set[Any]]]:
    """The parameters and enum values the scenarios send, per tool."""
    tools = {tool.name: tool for tool in dispatcher.TOOLS}
    used: dict[str, set[str]] = defaultdict(set)
    values: dict[tuple[str, str], set[Any]] = defaultdict(set)

    def walk(tool: str, prefix: str, value: Any, schema: dict[str, Any] | None) -> None:
        if isinstance(value, dict):
            properties = (schema or {}).get("properties", {})
            for key, item in value.items():
                if key == "translate" and not prefix:
                    used[tool].update({"translate_x", "translate_y", "translate_z"})
                    continue
                used[tool].add(prefix + key)
                walk(tool, f"{prefix}{key}.", item, properties.get(key))
        elif isinstance(value, list | tuple):
            items = (schema or {}).get("items")
            for item in value:
                walk(tool, prefix, item, items if isinstance(items, dict) else None)
        elif isinstance(value, str | bool) and schema and "enum" in schema:
            values[(tool, prefix.rstrip("."))].add(value)

    for scenario in SCENARIOS:
        if scenario.open_project:
            used["create_project"].update({"name", "up_axis", "meters_per_unit"})
            values[("create_project", "up_axis")].update(c.up_axis for c in scenario.conventions)
        for step in scenario.steps:
            walk(step.tool, "", step.params, tools[step.tool].parameters)
    return used, values


def _outcomes() -> tuple[set[str], set[str]]:
    succeeded: set[str] = set()
    refused: set[str] = set()
    for path in EXPECTED.rglob("*.txt"):
        for tool, said in _OUTCOME.findall(path.read_text(encoding="utf-8")):
            (succeeded if said == "ok" else refused).add(tool)
    return succeeded, refused


def test_every_parameter_and_value_of_every_tool_is_recorded() -> None:
    used, values = _usage()
    gaps = []
    for tool in dispatcher.TOOLS:
        for name, spec in _schema_params(tool.parameters).items():
            if name not in used[tool.name]:
                gaps.append(f"{tool.name}: parameter {name} is never used")
            for option in spec.get("enum", []):
                if option not in values[(tool.name, name)]:
                    gaps.append(f"{tool.name}: {name}={option!r} is never used")
    assert not gaps, "\n".join(gaps)


def test_every_tool_succeeds_and_is_refused_in_a_recording() -> None:
    succeeded, refused = _outcomes()
    names = {tool.name for tool in dispatcher.TOOLS}
    gaps = [f"{name} never succeeds" for name in sorted(names - succeeded)]
    gaps += [
        f"{name} is never refused" for name in sorted(names - refused - set(NEVER_REFUSED))
    ]
    stale = sorted(set(NEVER_REFUSED) & refused)
    gaps += [f"{name} is refused now: take it off NEVER_REFUSED" for name in stale]
    assert not gaps, "\n".join(gaps)
