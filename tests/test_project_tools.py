# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for project lifecycle: create, open, list, current."""

import asyncio
import tempfile
from pathlib import Path

from bowerbot.state import SceneState
from tests._helpers import exec_tool


def _state(tmp):
    tmp_path = Path(tmp)
    state = SceneState(projects_dir=tmp_path / "scenes")
    return tmp_path, state


def _create(state, name):
    """Create a project through the tool with the required axis + units."""
    return asyncio.run(exec_tool(
        state, "create_project",
        {"name": name, "up_axis": "Y", "meters_per_unit": 1.0},
    ))


# ── create_project ──


def test_create_project_focuses_it():
    """Creating a project binds the state to it."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state = _state(tmp)
        r = _create(state, "Coffee Shop")
        assert r.success, r.error
        assert r.data["name"] == "Coffee Shop"
        assert state.project is not None
        assert state.project.name == "Coffee Shop"
        assert state.stage is not None


def test_create_project_makes_folder():
    """Creating a project writes a project.json on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path, state = _state(tmp)
        _create(state, "kitchen")
        assert (tmp_path / "scenes" / "kitchen" / "project.json").exists()


def test_create_project_duplicate_refused():
    """Creating a project that already exists returns an error."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state = _state(tmp)
        _create(state, "dup")
        r = _create(state, "dup")
        assert not r.success
        assert "already exists" in r.error


def test_create_project_requires_axis_and_units():
    """create_project refuses without up_axis and meters_per_unit."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state = _state(tmp)
        r = asyncio.run(exec_tool(state, "create_project", {"name": "bare"}))
        assert not r.success
        assert "up_axis" in r.error


def test_create_project_no_projects_dir():
    """Without a projects dir, create_project is refused."""
    with tempfile.TemporaryDirectory():
        state = SceneState()
        r = _create(state, "x")
        assert not r.success


# ── open_project ──


def test_open_project_focuses_it():
    """Opening an existing project focuses the state."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state = _state(tmp)
        _create(state, "alpha")
        # Drop focus, then re-open.
        state.project = None
        state.stage = None
        r = asyncio.run(exec_tool(state, "open_project", {"name": "alpha"}))
        assert r.success, r.error
        assert state.project.name == "alpha"
        assert state.stage is not None


def test_open_project_nonexistent():
    """Opening a project that does not exist returns an error."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state = _state(tmp)
        r = asyncio.run(exec_tool(state, "open_project", {"name": "ghost"}))
        assert not r.success
        assert "not found" in r.error


def test_open_project_switches_focus():
    """Opening a different project rebinds the focus."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state = _state(tmp)
        _create(state, "one")
        _create(state, "two")
        assert state.project.name == "two"
        r = asyncio.run(exec_tool(state, "open_project", {"name": "one"}))
        assert r.success, r.error
        assert state.project.name == "one"


# ── list_projects ──


def test_list_projects_empty():
    """No projects yet returns an empty list."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state = _state(tmp)
        r = asyncio.run(exec_tool(state, "list_projects"))
        assert r.success, r.error
        assert r.data["count"] == 0
        assert r.data["current"] is None


def test_list_projects_flags_current():
    """list_projects flags the focused project."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state = _state(tmp)
        _create(state, "a")
        _create(state, "b")
        r = asyncio.run(exec_tool(state, "list_projects"))
        assert r.success, r.error
        assert r.data["count"] == 2
        assert r.data["current"] == "b"
        names = {p["name"] for p in r.data["projects"]}
        assert names == {"a", "b"}


# ── get_current_project ──


def test_get_current_project_none():
    """Reports no project when none is focused."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state = _state(tmp)
        r = asyncio.run(exec_tool(state, "get_current_project"))
        assert r.success, r.error
        assert r.data["current"] is None


def test_get_current_project_after_create():
    """Reports the focused project after create."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state = _state(tmp)
        _create(state, "focused")
        r = asyncio.run(exec_tool(state, "get_current_project"))
        assert r.success, r.error
        assert r.data["current"] == "focused"


# ── authoring guard interplay ──


def test_authoring_without_project_is_refused():
    """A place/author tool refuses when no project is focused."""
    with tempfile.TemporaryDirectory() as tmp:
        _, state = _state(tmp)
        r = asyncio.run(exec_tool(state, "list_scene"))
        assert not r.success
