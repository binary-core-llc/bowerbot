# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Each layer holds only its kind of thing.

- ``utils/`` and ``services/`` hold functions: no values, classes or type
  aliases at module level (``logger`` excepted).
- ``constants/`` holds fixed values, grouped in classes.
- ``schemas/`` holds data shapes (pydantic models, enums, dataclasses) and
  type aliases, never values, and never imports ``pxr``.
"""

from __future__ import annotations

import ast
import dataclasses
import enum
import importlib
import inspect
import re
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "bowerbot"
_VALUE_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_FUNCTION_LAYER_NODES = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef)


def _modules(layer: str) -> list[Path]:
    return sorted(path for path in (PACKAGE / layer).glob("*.py") if path.name != "__init__.py")


def _module_name(path: Path) -> str:
    return "bowerbot." + ".".join(path.relative_to(PACKAGE).with_suffix("").parts)


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def _is_logger(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Assign)
        and [getattr(target, "id", None) for target in node.targets] == ["logger"]
    )


def _assigned_name(node: ast.stmt) -> str | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
    elif isinstance(node, ast.AnnAssign):
        target = node.target
    else:
        return None
    return target.id if isinstance(target, ast.Name) else None


@pytest.mark.parametrize("path", _modules("utils") + _modules("services"), ids=lambda p: p.name)
def test_utils_and_services_hold_only_functions(path: Path) -> None:
    extra = [
        f"line {node.lineno}: {ast.unparse(node).splitlines()[0][:80]}"
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if not isinstance(node, _FUNCTION_LAYER_NODES)
        and not _is_docstring(node)
        and not _is_logger(node)
    ]
    assert not extra, (
        f"{path.name} must hold only functions; move values to constants/ and types "
        "to schemas/:\n" + "\n".join(extra)
    )


@pytest.mark.parametrize("path", _modules("constants"), ids=lambda p: p.name)
def test_constants_hold_values_in_classes(path: Path) -> None:
    problems = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import | ast.ImportFrom) or _is_docstring(node):
            continue
        if not isinstance(node, ast.ClassDef):
            problems.append(f"line {node.lineno}: only classes of values belong here")
            continue
        for item in node.body:
            if _is_docstring(item):
                continue
            name = _assigned_name(item)
            if name is None or not _VALUE_NAME.match(name):
                problems.append(f"{node.name}, line {item.lineno}: only UPPER_CASE values")
    assert not problems, f"{path.name}:\n" + "\n".join(problems)


@pytest.mark.parametrize("path", _modules("schemas"), ids=lambda p: p.name)
def test_schemas_hold_data_shapes_and_types_only(path: Path) -> None:
    module = importlib.import_module(_module_name(path))
    problems = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [
                alias.name for alias in node.names
            ]
            if any(name == "pxr" or name.startswith("pxr.") for name in names):
                problems.append(f"line {node.lineno}: schemas never import pxr")
            continue
        name = _assigned_name(node)
        if name is None:
            continue
        value = getattr(module, name)
        if not isinstance(value, type) and typing.get_origin(value) is None:
            problems.append(f"line {node.lineno}: {name} is a value; move it to constants/")
    for name, cls in vars(module).items():
        if not inspect.isclass(cls) or cls.__module__ != module.__name__:
            continue
        if not (issubclass(cls, BaseModel | enum.Enum) or dataclasses.is_dataclass(cls)):
            problems.append(
                f"{name} is not a pydantic model, enum or dataclass; "
                "a class that only holds values belongs in constants/",
            )
    assert not problems, f"{path.name}:\n" + "\n".join(problems)
