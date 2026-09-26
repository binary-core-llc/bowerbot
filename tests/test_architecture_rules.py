# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Enforce the code rules in CONTRIBUTING.md.

- One home per concept: ``utils/core`` imports no domain module, and holds
  functions only (plus the standard module logger); its named values live in
  schema classes.
- Bounding boxes come from ``core.bounds``; nothing else builds a ``BBoxCache``.
- No loose values: ``schemas`` hold classes and ``type`` declarations only
  (plus the package ``__all__``).
- One guard: only ``SceneState`` checks whether a scene, project or configured
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



CORE_DIR = ROOT / "src" / "bowerbot" / "utils" / "core"
CORE_MAY_IMPORT = ("bowerbot.schemas", "bowerbot.utils.core")


def test_core_imports_no_domain() -> None:
    offenders = []
    for path in sorted(CORE_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            offenders += [
                f"{path.name}:{node.lineno} {module}"
                for module in modules
                if module.startswith("bowerbot") and not module.startswith(CORE_MAY_IMPORT)
            ]
    assert not offenders, f"utils/core must not import a domain: {offenders}"


MODULE_LOGGER = "logger = logging.getLogger(__name__)"


def test_core_has_no_module_constants() -> None:
    offenders = []
    for path in sorted(CORE_DIR.glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                if ast.unparse(node) != MODULE_LOGGER:
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"named values belong in a schema class, not utils/core: {offenders}"


SCHEMAS_DIR = ROOT / "src" / "bowerbot" / "schemas"


def test_schemas_hold_classes_and_type_declarations_only() -> None:
    offenders = []
    for path in sorted(SCHEMAS_DIR.glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if path.name == "__init__.py" and [ast.unparse(t) for t in targets] == ["__all__"]:
                continue
            offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"use a class for values and `type` for aliases: {offenders}"


BOWERBOT_DIR = ROOT / "src" / "bowerbot"


def test_bounding_boxes_come_from_core_bounds() -> None:
    offenders = [
        f"{path.relative_to(BOWERBOT_DIR)}:{node.lineno}"
        for path in sorted(BOWERBOT_DIR.rglob("*.py"))
        if path != CORE_DIR / "bounds.py"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "BBoxCache"
    ]
    assert not offenders, f"use core.bounds.bbox_cache(): {offenders}"


def test_services_never_call_a_same_named_function_unqualified() -> None:
    """A service named like its util must call the util through its module."""
    offenders = []
    for path in sorted(SERVICES_DIR.glob("*_service.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {f.name for f in tree.body if isinstance(f, ast.FunctionDef)}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in names
            ):
                offenders.append(f"{path.name}:{node.lineno} {node.func.id}()")
    assert not offenders, f"call the util as <module>.{{name}}() instead: {offenders}"
