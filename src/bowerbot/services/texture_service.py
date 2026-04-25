# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Texture service — orchestrates texture discovery for the texture tools."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import TextureCategory
from bowerbot.state import SceneState
from bowerbot.utils import texture_utils


def list_textures(state: SceneState, params: dict[str, Any]) -> list[dict[str, str]]:
    """List every texture in the user's library, optionally filtered."""
    category = TextureCategory(params.get("category", "all"))
    return texture_utils.find_textures(state.library_dir, category)


def search_textures(state: SceneState, params: dict[str, Any]) -> list[dict[str, str]]:
    """Search the user's library for textures matching a query."""
    category = TextureCategory(params.get("category", "all"))
    return texture_utils.find_textures(
        state.library_dir, category, query=params.get("query", ""),
    )
