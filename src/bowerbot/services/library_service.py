# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Library service — orchestrates asset discovery for the library tools."""

from __future__ import annotations

from typing import Any

from bowerbot.state import SceneState
from bowerbot.utils import library_utils
from bowerbot.utils.library_utils import DEFAULT_SEARCH_LIMIT


def list_assets(state: SceneState, params: dict[str, Any]) -> dict[str, object]:
    """List library assets with optional category filter; truncated to *limit*."""
    matches = library_utils.scan_library(
        state.library_dir, category=params.get("category", "all"),
    )
    return library_utils.truncate_with_total(
        matches, params.get("limit", DEFAULT_SEARCH_LIMIT),
    )


def search_assets(state: SceneState, params: dict[str, Any]) -> dict[str, object]:
    """Search the user's library by name across every category; truncated to *limit*."""
    matches = library_utils.scan_library(
        state.library_dir, query=params.get("query", ""), category="all",
    )
    return library_utils.truncate_with_total(
        matches, params.get("limit", DEFAULT_SEARCH_LIMIT),
    )
