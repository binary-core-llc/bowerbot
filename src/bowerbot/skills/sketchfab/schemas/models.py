# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Schemas for Sketchfab API payloads and download results."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SketchfabModel(BaseModel):
    """One model returned by the Sketchfab ``/me/models`` endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    uid: str
    name: str
    description: str = ""
    url: str = ""
    vertex_count: int | None = None
    face_count: int | None = None
    is_downloadable: bool = False
    tags: list[str] = []
    thumbnail: str | None = None


class DownloadedModel(BaseModel):
    """Result of a successful USDZ download."""

    file_path: str
    format: str
    size_bytes: int
    name: str
    uid: str
    message: str
