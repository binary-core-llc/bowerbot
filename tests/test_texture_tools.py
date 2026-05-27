# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tool-layer tests for textures: search_textures, list_textures."""

import asyncio
import tempfile
from pathlib import Path

from tests._helpers import exec_tool, make_state


def _seed_textures(lib_dir: Path) -> None:
    for name, ext in [
        ("studio", ".hdr"),
        ("sunset", ".exr"),
        ("wood_diffuse", ".png"),
        ("marble", ".jpg"),
    ]:
        (lib_dir / f"{name}{ext}").write_bytes(b"fake")


# ── search_textures ──


def test_search_textures_finds_hdri():
    """Finds HDRI textures matching a keyword."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lib_dir = tmp_path / "library"
        lib_dir.mkdir()
        _seed_textures(lib_dir)

        state, _ = make_state(tmp_path)
        state.library_dir = lib_dir

        r = asyncio.run(exec_tool(state, "search_textures", {
            "query": "studio", "category": "hdri",
        }))
        assert r.success, r.error
        assert len(r.data) >= 1


def test_search_textures_no_match():
    """Returns empty when nothing matches."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lib_dir = tmp_path / "library"
        lib_dir.mkdir()
        _seed_textures(lib_dir)

        state, _ = make_state(tmp_path)
        state.library_dir = lib_dir

        r = asyncio.run(exec_tool(state, "search_textures", {
            "query": "nonexistent", "category": "hdri",
        }))
        assert r.success, r.error
        assert len(r.data) == 0


# ── list_textures ──


def test_list_textures_hdri():
    """Lists HDRI textures in the library."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lib_dir = tmp_path / "library"
        lib_dir.mkdir()
        _seed_textures(lib_dir)

        state, _ = make_state(tmp_path)
        state.library_dir = lib_dir

        r = asyncio.run(exec_tool(state, "list_textures", {
            "category": "hdri",
        }))
        assert r.success, r.error
        assert len(r.data) >= 2


def test_list_textures_empty_library():
    """Returns empty for a library with no matching textures."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lib_dir = tmp_path / "library"
        lib_dir.mkdir()

        state, _ = make_state(tmp_path)
        state.library_dir = lib_dir

        r = asyncio.run(exec_tool(state, "list_textures", {
            "category": "hdri",
        }))
        assert r.success, r.error
        assert len(r.data) == 0
