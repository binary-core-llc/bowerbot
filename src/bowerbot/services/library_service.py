# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Library service — orchestrates asset discovery for the library tools."""

from __future__ import annotations

from typing import Any

from bowerbot import constants
from bowerbot import scene_state
from bowerbot.utils import authoring


def list_assets(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, object]:
    """List library assets with optional category filter; truncated to *limit*."""
    matches = authoring.library.scan_library(
        state.library_dir, category=params.get("category", "all"),
    )
    return authoring.library.truncate_with_total(
        matches, params.get("limit", constants.LibraryDefaults.SEARCH_LIMIT), state.library_dir,
    )


def search_assets(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, object]:
    """Search the user's library by name across every category; truncated to *limit*."""
    matches = authoring.library.scan_library(
        state.library_dir, query=params.get("query", ""), category="all",
    )
    return authoring.library.truncate_with_total(
        matches, params.get("limit", constants.LibraryDefaults.SEARCH_LIMIT), state.library_dir,
    )
