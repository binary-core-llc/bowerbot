# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""SceneState: the object threaded through every tool handler."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pxr import Usd

from bowerbot.config import SceneDefaults

if TYPE_CHECKING:
    from bowerbot.project import Project


_HASH_CHUNK_SIZE = 65536


@dataclass
class SceneState:
    """Mutable scene-building context shared across tool handlers."""

    scene_defaults: SceneDefaults
    project: Project | None = None
    stage: Usd.Stage | None = None
    stage_path: Path | None = None
    object_count: int = 0
    library_dir: Path | None = None
    stage_last_save_mtime: float | None = None
    stage_last_save_hash: str | None = None

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

    def _compute_stage_hash(self) -> str | None:
        """Hash the on-disk stage file, or None if it does not exist."""
        if self.stage_path is None or not self.stage_path.exists():
            return None
        h = hashlib.blake2b(digest_size=16)
        with self.stage_path.open("rb") as f:
            for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
                h.update(chunk)
        return h.hexdigest()

    def mark_saved(self) -> None:
        """Record the current on-disk stage as the baseline."""
        if self.stage_path is None or not self.stage_path.exists():
            self.stage_last_save_mtime = None
            self.stage_last_save_hash = None
            return
        self.stage_last_save_mtime = self.stage_path.stat().st_mtime
        self.stage_last_save_hash = self._compute_stage_hash()

    def detect_external_changes(self) -> bool:
        """Return True if the stage file changed since the last baseline."""
        if self.stage_path is None or not self.stage_path.exists():
            return False
        if self.stage_last_save_mtime is None or self.stage_last_save_hash is None:
            return False
        if self.stage_path.stat().st_mtime <= self.stage_last_save_mtime:
            return False
        return self._compute_stage_hash() != self.stage_last_save_hash
