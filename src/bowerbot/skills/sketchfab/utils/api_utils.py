# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Sketchfab HTTP primitives — auth headers, naming, response shaping."""

from __future__ import annotations

from typing import Any

BASE_URL = "https://api.sketchfab.com/v3"


def auth_headers(token: str) -> dict[str, str]:
    """Build the Authorization header for Sketchfab API calls."""
    return {"Authorization": f"Token {token}"}


def safe_file_name(name: str) -> str:
    """Sanitize a string for use as a download file name."""
    return "".join(c for c in name if c.isalnum() or c in "_-").strip()


def format_model_list(api_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Reduce a ``/me/models`` response to the fields the LLM consumes."""
    results: list[dict[str, Any]] = []
    for model in api_response.get("results", []):
        thumbs = model.get("thumbnails", {}).get("images", [])
        thumbnail = thumbs[0].get("url") if thumbs else None
        results.append({
            "uid": model["uid"],
            "name": model["name"],
            "description": model.get("description", ""),
            "url": model.get("viewerUrl", ""),
            "vertex_count": model.get("vertexCount"),
            "face_count": model.get("faceCount"),
            "is_downloadable": model.get("isDownloadable", False),
            "tags": [t.get("name", "") for t in model.get("tags", [])],
            "thumbnail": thumbnail,
        })
    return results
