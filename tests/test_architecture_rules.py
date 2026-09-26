# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Enforce the code rules in CONTRIBUTING.md.

One guard: only ``SceneState`` checks whether a scene, project or configured
folder exists. Services call ``state.require_*()``; tools never touch state.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "src" / "bowerbot" / "tools"
SERVICES_DIR = ROOT / "src" / "bowerbot" / "services"

GUARDED_FIELDS = {"stage", "stage_path", "project", "library_dir", "projects_dir"}


def _state_field(node: ast.AST) -> str | None:
    """``state.<field>`` → field name, when it is one SceneState guards."""
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "state"
        and node.attr in GUARDED_FIELDS
    ):
        return node.attr
    return None


def _checks_missing(test: ast.expr) -> bool:
    """Whether *test* checks a guarded state field for ``None`` or falsiness."""
    for node in ast.walk(test):
        if isinstance(node, ast.Compare) and _state_field(node.left):
            if any(isinstance(c, ast.Constant) and c.value is None for c in node.comparators):
                return True
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            if _state_field(node.operand):
                return True
    return False


def _is_service_call(node: ast.AST) -> bool:
    """Whether *node* is a call like ``camera_service.create_camera(...)``."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id.endswith("_service")
    )


def test_tools_only_pass_state_to_their_service() -> None:
    offenders = []
    for path in sorted(TOOLS_DIR.glob("*_tools.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Name)
                and node.id == "state"
                and isinstance(node.ctx, ast.Load)
                and not _is_service_call(parents[node])
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"tools must pass state straight to their service: {offenders}"


def test_services_never_guard_state_themselves() -> None:
    offenders = []
    for path in sorted(SERVICES_DIR.glob("*_service.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.If)
                and _checks_missing(node.test)
                and any(isinstance(n, ast.Raise) for s in node.body for n in ast.walk(s))
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"use state.require_*() instead of checking and raising: {offenders}"
