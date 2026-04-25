# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""SceneState — the object threaded through every tool handler.

Holds the project binding, the currently open USD stage, and the
bookkeeping needed to name newly placed prims. Services never hold
state; they take primitives (``Usd.Stage``, ``Path``, etc.) and
tool handlers pull those out of ``SceneState``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pxr import Usd

from bowerbot.config import SceneDefaults

if TYPE_CHECKING:
    from bowerbot.project import Project


@dataclass
class SceneState:
    """Mutable scene-building context shared across tool handlers."""

    scene_defaults: SceneDefaults
    project: Project | None = None
    stage: Usd.Stage | None = None
    stage_path: Path | None = None
    object_count: int = 0
    library_dir: Path | None = None  # user's shared asset library (settings.assets_dir)

    @property
    def assets_dir(self) -> Path | None:
        """Project assets directory, or ``None`` if no project is bound."""
        return self.project.assets_dir if self.project else None

    @property
    def project_dir(self) -> Path | None:
        """Project root directory, or ``None`` if no project is bound."""
        return self.project.path if self.project else None

    def resolve_assets_dir(self) -> Path:
        """Return the project's assets directory, creating it on demand."""
        if self.assets_dir is None:
            msg = "No project set. Use 'bowerbot new' to create a project first."
            raise RuntimeError(msg)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        return self.assets_dir

    def resolve_project_dir(self) -> Path:
        """Return the project's root directory, or raise if unset."""
        if self.project_dir is None:
            msg = "No project set. Use 'bowerbot new' to create a project first."
            raise RuntimeError(msg)
        return self.project_dir

    def touch_project(self) -> None:
        """Persist updated_at on the bound project, if any."""
        if self.project is not None:
            self.project.save()
