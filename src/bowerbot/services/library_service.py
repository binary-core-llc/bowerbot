# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Library service — orchestrates asset discovery for the library tools."""

from __future__ import annotations

from typing import Any

from bowerbot.state import SceneState
from bowerbot.utils import library_utils


def list_assets(state: SceneState, params: dict[str, Any]) -> list[dict[str, str]]:
    """List every USD asset in the user's library, optionally filtered."""
    return library_utils.scan_library(
        state.library_dir, category=params.get("category", "all"),
    )


def search_assets(state: SceneState, params: dict[str, Any]) -> list[dict[str, str]]:
    """Search the user's library for USD assets matching a query."""
    return library_utils.scan_library(
        state.library_dir,
        query=params.get("query", ""),
        category=params.get("category", "all"),
    )
