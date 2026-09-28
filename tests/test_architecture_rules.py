# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Each layer holds only its kind of thing.

- ``utils/`` and ``services/`` hold functions: no values, classes or type
  aliases at module level (``logger`` excepted). Every utils module and group
  opens with a docstring saying what it owns.
- ``utils/usd/`` holds USD building blocks: a module there reaches other utils
  only through ``usd``, never a module outside the group.
- ``utils/authoring/`` holds BowerBot's authoring model: a module there uses
  ``usd`` and ``authoring``, never ``features``.
- ``constants/`` holds fixed values, grouped in classes.
- ``schemas/`` holds data shapes (pydantic models, enums, dataclasses) and
  type aliases, never values, and never imports ``pxr``.

And everywhere, in the package and its tests, BowerBot code is imported as
modules: ``from bowerbot import schemas`` then ``schemas.LightParams``, and
``from bowerbot import utils`` then ``utils.lights.create_light``. Only the
package ``__init__`` files that re-export names import them directly.
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

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "bowerbot"
_REEXPORTS = {
    PACKAGE / name / "__init__.py" for name in ("constants", "schemas", "skills", "utils")
}
_OWN_CODE = ("bowerbot", "tests")
_VALUE_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_FUNCTION_LAYER_NODES = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef)


def _modules(layer: str) -> list[Path]:
    return sorted(path for path in (PACKAGE / layer).glob("*.py") if path.name != "__init__.py")


def _utils_modules() -> list[Path]:
    """Every utils module, the group folders included."""
    return sorted(
        path for path in (PACKAGE / "utils").rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    )


def _utils_id(path: Path) -> str:
    return path.relative_to(PACKAGE / "utils").as_posix()


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


@pytest.mark.parametrize(
    "path",
    _utils_modules() + _modules("services"),
    ids=lambda p: p.relative_to(PACKAGE).as_posix(),
)
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


def _submodule(package: str, name: str) -> object | None:
    """``package.name`` when it is a module, else None (it is a function, class or value)."""
    try:
        return importlib.import_module(f"{package}.{name}")
    except ModuleNotFoundError:
        return None


def _own_code_files() -> list[Path]:
    files = [*PACKAGE.rglob("*.py"), *(ROOT / "tests").rglob("*.py")]
    return sorted(path for path in files if "__pycache__" not in path.parts)


def _imported_modules(tree: ast.Module) -> dict[str, object]:
    """Names this file binds to BowerBot or test modules, with the module each one is."""
    modules = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(_OWN_CODE):
            for alias in node.names:
                value = _submodule(node.module, alias.name)
                if value is not None:
                    modules[alias.asname or alias.name] = value
    return modules


@pytest.mark.parametrize(
    "path", _own_code_files(), ids=lambda p: p.relative_to(ROOT).as_posix(),
)
def test_code_imports_modules_not_names(path: Path) -> None:
    if path in _REEXPORTS:
        return
    problems = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith(_OWN_CODE):
            continue
        for alias in node.names:
            if alias.name.startswith("__"):
                continue
            if _submodule(node.module, alias.name) is None:
                problems.append(
                    f"line {node.lineno}: imports {alias.name} from {node.module}; import the "
                    f"module and write <module>.{alias.name}",
                )
    assert not problems, f"{path.relative_to(ROOT)}:\n" + "\n".join(problems)


@pytest.mark.parametrize(
    "path", _own_code_files(), ids=lambda p: p.relative_to(ROOT).as_posix(),
)
def test_every_module_reference_exists(path: Path) -> None:
    """``utils.lights.create_light`` and the like must name something that exists.

    A misspelled reference would otherwise only fail when that line runs.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = _imported_modules(tree)
    problems = set()
    for node in ast.walk(tree):
        chain: list[str] = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            chain.insert(0, current.attr)
            current = current.value
        if not chain or not isinstance(current, ast.Name) or current.id not in modules:
            continue
        value = modules[current.id]
        for name in chain:
            if not (inspect.ismodule(value) or inspect.isclass(value)):
                break
            if not hasattr(value, name):
                problems.add(f"line {node.lineno}: {current.id}.{'.'.join(chain)} does not exist")
                break
            value = getattr(value, name)
    assert not problems, f"{path.relative_to(ROOT)}:\n" + "\n".join(sorted(problems))


@pytest.mark.parametrize(
    "path",
    _utils_modules() + sorted((PACKAGE / "utils").rglob("__init__.py")),
    ids=_utils_id,
)
def test_utils_modules_and_groups_say_what_they_own(path: Path) -> None:
    docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    assert docstring, f"utils/{_utils_id(path)} needs a docstring saying what it owns"


_UTILS_GROUPS = {"usd", "authoring", "features"}


@pytest.mark.parametrize(
    "path", _own_code_files(), ids=lambda p: p.relative_to(ROOT).as_posix(),
)
def test_utils_groups_are_imported_as_groups(path: Path) -> None:
    """Code imports a group (``from bowerbot.utils import usd``), then calls ``usd.naming.x(...)``.

    Never a module inside a group, and never a group through the package
    (``utils.usd``). Only the utils package's own ``__init__`` files import its
    modules directly.
    """
    if path.name == "__init__.py" and (PACKAGE / "utils") in path.parents:
        return
    problems = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module == "bowerbot.utils":
            for alias in node.names:
                if alias.name not in _UTILS_GROUPS:
                    problems.add(f"line {node.lineno}: imports {alias.name}; import its group")
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("bowerbot.utils."):
            problems.add(f"line {node.lineno}: imports from {node.module}; import the group")
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "utils"
            and node.attr in _UTILS_GROUPS
        ):
            problems.add(f"line {node.lineno}: utils.{node.attr}; import the group instead")
    assert not problems, f"{path.relative_to(ROOT)}:\n" + "\n".join(sorted(problems))


@pytest.mark.parametrize(
    "path", sorted((PACKAGE / "utils" / "usd").glob("*.py")), ids=_utils_id,
)
def test_usd_building_blocks_use_only_their_group(path: Path) -> None:
    """A ``usd/`` module reaches other utils only through ``usd``."""
    problems = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ImportFrom):
            continue
        names = [alias.name for alias in node.names]
        if node.module == "bowerbot" and "utils" in names:
            problems.append(f"line {node.lineno}: imports all of utils; import usd instead")
        if node.module == "bowerbot.utils" and set(names) - {"usd"}:
            problems.append(f"line {node.lineno}: imports {names} from utils; only usd is allowed")
    assert not problems, f"utils/{_utils_id(path)}:\n" + "\n".join(problems)


@pytest.mark.parametrize(
    "path", sorted((PACKAGE / "utils" / "authoring").glob("*.py")), ids=_utils_id,
)
def test_authoring_never_uses_features(path: Path) -> None:
    """An ``authoring/`` module uses ``usd`` and ``authoring``, never a feature."""
    problems = [
        f"line {node.lineno}: imports {alias.name} from utils; only usd and authoring are allowed"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module == "bowerbot.utils"
        for alias in node.names
        if alias.name not in {"usd", "authoring"}
    ]
    assert not problems, f"utils/{_utils_id(path)}:\n" + "\n".join(problems)
