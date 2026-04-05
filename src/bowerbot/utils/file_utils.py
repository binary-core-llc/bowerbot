# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Filesystem utilities for project file management."""

from __future__ import annotations

import shutil
from pathlib import Path

from bowerbot.schemas import ASWFLayerNames


def copy_texture_to_project(
    source: Path,
    project_dir: Path,
) -> str:
    """Copy a texture file to the project-level textures/ directory.

    Used for scene-level textures like HDRI maps for DomeLights.
    Skips the copy if the destination already exists.

    Args:
        source: Path to the texture file.
        project_dir: Project root directory.

    Returns:
        Relative path from the scene file
        (e.g. ``"./textures/studio.exr"``).
    """
    tex_dir = project_dir / ASWFLayerNames.TEXTURES
    tex_dir.mkdir(parents=True, exist_ok=True)

    local_copy = tex_dir / source.name
    if not local_copy.exists():
        shutil.copy2(source, local_copy)

    return f"./{ASWFLayerNames.TEXTURES}/{source.name}"
