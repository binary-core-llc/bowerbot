# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Texture service — orchestrates texture discovery for the texture tools."""

from __future__ import annotations

from typing import Any

from bowerbot import scene_state
from bowerbot import schemas
from bowerbot.utils import authoring


def list_textures(state: scene_state.SceneState, params: dict[str, Any]) -> list[dict[str, str]]:
    """List every texture in the user's library, optionally filtered."""
    category = schemas.TextureCategory(params.get("category", "all"))
    return authoring.library.find_textures(state.library_dir, category)


def search_textures(state: scene_state.SceneState, params: dict[str, Any]) -> list[dict[str, str]]:
    """Search the user's library for textures matching a query."""
    category = schemas.TextureCategory(params.get("category", "all"))
    return authoring.library.find_textures(
        state.library_dir, category, query=params.get("query", ""),
    )
