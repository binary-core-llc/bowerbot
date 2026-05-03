# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""SceneState: the object threaded through every tool handler."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
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
    layer_baselines: dict[Path, tuple[float, str]] = field(default_factory=dict)

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

    def _hash_file(self, path: Path) -> str:
        """Hash a file with blake2b in chunks."""
        h = hashlib.blake2b(digest_size=16)
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
                h.update(chunk)
        return h.hexdigest()

    def _watched_layer_paths(self) -> list[Path]:
        """Discover the scene's full layer stack (root + transitive sublayers)."""
        from bowerbot.utils import stage_utils
        if self.stage_path is None or not self.stage_path.exists():
            return []
        return stage_utils.collect_scene_layer_paths(self.stage_path)

    def mark_saved(self) -> None:
        """Snapshot mtime + hash of every layer in the scene's stack."""
        self.layer_baselines = {}
        for layer_path in self._watched_layer_paths():
            if layer_path.exists():
                self.layer_baselines[layer_path] = (
                    layer_path.stat().st_mtime,
                    self._hash_file(layer_path),
                )

    def detect_external_changes(self) -> bool:
        """Return True if any watched layer changed since the last baseline."""
        if not self.layer_baselines:
            return False
        for layer_path in self._watched_layer_paths():
            baseline = self.layer_baselines.get(layer_path)
            if baseline is None:
                return True
            mtime, digest = baseline
            if not layer_path.exists():
                return True
            if layer_path.stat().st_mtime <= mtime:
                continue
            if self._hash_file(layer_path) != digest:
                return True
        return False
