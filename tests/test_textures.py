# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for texture_service and the search_textures / list_textures tools."""

import asyncio
import tempfile
from pathlib import Path

from bowerbot.config import SceneDefaults
from bowerbot.schemas import TextureCategory
from bowerbot.services import texture_service
from bowerbot.state import SceneState
from bowerbot.tools import texture_tools


def _seed_library(library: Path) -> None:
    """Drop a representative mix of HDRI + image files into *library*."""
    (library / "studio.exr").write_bytes(b"fake")
    (library / "kitchen.hdr").write_bytes(b"fake")
    (library / "wood_diffuse.png").write_bytes(b"fake")
    (library / "metal_normal.jpg").write_bytes(b"fake")
    (library / "tile_roughness.tif").write_bytes(b"fake")
    (library / "notes.txt").write_text("ignored")
    nested = library / "subfolder"
    nested.mkdir()
    (nested / "interior.exr").write_bytes(b"fake")


def test_list_textures_all_categories():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        _seed_library(library)

        results = texture_service.list_textures(library, TextureCategory.ALL)
        names = sorted(r["name"] for r in results)
        assert names == [
            "interior", "kitchen", "metal_normal",
            "studio", "tile_roughness", "wood_diffuse",
        ]


def test_list_textures_hdri_only():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        _seed_library(library)

        results = texture_service.list_textures(library, TextureCategory.HDRI)
        names = sorted(r["name"] for r in results)
        assert names == ["interior", "kitchen", "studio"]
        assert all(r["category"] == "hdri" for r in results)


def test_list_textures_material_only():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        _seed_library(library)

        results = texture_service.list_textures(library, TextureCategory.MATERIAL)
        names = sorted(r["name"] for r in results)
        assert names == ["metal_normal", "tile_roughness", "wood_diffuse"]
        assert all(r["category"] == "material" for r in results)


def test_search_textures_matches_stem():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        _seed_library(library)

        results = texture_service.search_textures(
            library, "wood", TextureCategory.ALL,
        )
        assert [r["name"] for r in results] == ["wood_diffuse"]


def test_search_textures_missing_library_returns_empty():
    results = texture_service.search_textures(
        Path("/does/not/exist"), "anything", TextureCategory.ALL,
    )
    assert results == []


def test_tool_returns_error_when_library_dir_unset():
    state = SceneState(scene_defaults=SceneDefaults(), library_dir=None)
    result = asyncio.run(asyncio.to_thread(
        texture_tools.list_textures, state, {},
    ))
    assert not result.success
    assert "asset library" in result.error.lower()


def test_tool_search_uses_library_dir():
    with tempfile.TemporaryDirectory() as tmp:
        library = Path(tmp)
        _seed_library(library)
        state = SceneState(scene_defaults=SceneDefaults(), library_dir=library)

        result = asyncio.run(asyncio.to_thread(
            texture_tools.search_textures, state,
            {"query": "studio", "category": "hdri"},
        ))
        assert result.success
        assert len(result.data) == 1
        assert result.data[0]["name"] == "studio"
        assert result.data[0]["category"] == "hdri"
