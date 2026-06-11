# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Dispatcher JSON-schema validation of tool params (agent-runtime parity with MCP)."""

import asyncio
import tempfile
from pathlib import Path

from tests._helpers import exec_tool, make_state


def _state(tmp):
    state, _ = make_state(Path(tmp))
    asyncio.run(exec_tool(state, "create_stage", {"filename": "t"}))
    return state


def test_rejects_wrong_scalar_type():
    """A string where the schema declares a number is rejected before the handler."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _state(tmp)
        r = asyncio.run(exec_tool(state, "place_asset", {
            "asset_file_path": "x.usda", "asset_name": "X", "group": "Props",
            "translate_x": "abc", "translate_y": 0.0, "translate_z": 0.0,
        }))
        assert not r.success
        assert "invalid parameters for place_asset" in r.error


def test_rejects_string_boolean_flag():
    """The string 'false' is rejected for boolean params instead of acting as True."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _state(tmp)
        r = asyncio.run(exec_tool(state, "save_scene_snapshot", {
            "name": "s", "force": "false",
        }))
        assert not r.success
        assert "invalid parameters for save_scene_snapshot" in r.error


def test_rejects_string_vector():
    """A char-decomposable string is rejected for array params."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _state(tmp)
        r = asyncio.run(exec_tool(state, "setup_physics_scene", {
            "gravity_direction": "012",
        }))
        assert not r.success
        assert "invalid parameters for setup_physics_scene" in r.error


def test_missing_required_param_rejected():
    """A call missing a schema-required param is rejected with the curated message."""
    with tempfile.TemporaryDirectory() as tmp:
        state = _state(tmp)
        r = asyncio.run(exec_tool(state, "set_prim_attribute", {
            "prim_path": "/Scene",
        }))
        assert not r.success
        assert "invalid parameters for set_prim_attribute" in r.error
