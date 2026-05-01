# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Sketchfab tool definitions surfaced to the LLM."""

from __future__ import annotations

from bowerbot.skills.base import Tool

TOOLS: list[Tool] = [
    Tool(
        name="search_my_models",
        description=(
            "Search YOUR OWN Sketchfab model library by keyword. "
            "Returns models you have uploaded to your account."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search keyword to find models in your library."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (1-24).",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="list_my_models",
        description=(
            "List all models in YOUR Sketchfab account. "
            "Use this to see everything available before searching."
        ),
        parameters={
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (1-24).",
                    "default": 24,
                },
            },
        },
    ),
    Tool(
        name="download_model",
        description=(
            "Download a model from your Sketchfab account by its UID. "
            "Downloads in USDZ format only. "
            "Returns the local file path of the downloaded asset."
        ),
        parameters={
            "type": "object",
            "properties": {
                "uid": {
                    "type": "string",
                    "description": "Sketchfab model UID (from search results).",
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Human-readable name for the downloaded file."
                    ),
                },
            },
            "required": ["uid", "name"],
        },
    ),
]
