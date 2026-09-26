# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""SceneState: the object threaded through every tool handler."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pxr import Ar, Usd

from bowerbot.config import Settings, UpAxis
from bowerbot.utils import inspection_utils, stage_utils

if TYPE_CHECKING:
    from bowerbot.project import Project


@dataclass
class SceneState:
    """Mutable scene-building context shared across tool handlers."""

    up_axis: UpAxis = UpAxis.Y
    meters_per_unit: float = 1.0
    project: Project | None = None
    stage: Usd.Stage | None = None
    stage_path: Path | None = None
    object_count: int = 0
    library_dir: Path | None = None
    projects_dir: Path | None = None
    layer_baselines: dict[Path, tuple[float, str | None]] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Settings) -> SceneState:
        """Build an unbound state with the configured library and projects dirs."""
        return cls(
            library_dir=Path(settings.assets_dir),
            projects_dir=Path(settings.projects_dir),
        )

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
        assets_dir = self.require_project().assets_dir
        assets_dir.mkdir(parents=True, exist_ok=True)
        return assets_dir

    def require_stage(self) -> Usd.Stage:
        """The open scene's stage; raises if no scene is open."""
        return self._open_scene()[0]

    def require_stage_path(self) -> Path:
        """The open scene's file; raises if no scene is open."""
        return self._open_scene()[1]

    def reopen_stage(self) -> Usd.Stage:
        """Reopen the scene from disk so it sees edited asset layers."""
        self.stage = stage_utils.open_stage(self.require_stage_path())
        return self.stage

    def require_project(self) -> Project:
        """The open project; raises if none is open."""
        if self.project is None:
            msg = "No project is open. Create or open a project first."
            raise RuntimeError(msg)
        return self.project

    def require_library_dir(self) -> Path:
        """The configured asset library; raises if none is configured."""
        if self.library_dir is None:
            msg = "No asset library configured. Set 'assets_dir' in config.json."
            raise RuntimeError(msg)
        return self.library_dir

    def require_projects_dir(self) -> Path:
        """The configured projects directory; raises if none is configured."""
        if self.projects_dir is None:
            msg = "No projects directory configured. Set 'projects_dir' in config.json."
            raise RuntimeError(msg)
        return self.projects_dir

    def _open_scene(self) -> tuple[Usd.Stage, Path]:
        """The open stage and its file; raises if no scene is open."""
        if self.stage is None or self.stage_path is None:
            msg = "No scene is open. Create or open a project first."
            raise RuntimeError(msg)
        return self.stage, self.stage_path

    def bind_project(self, project: Project) -> None:
        """Focus this state on *project*: open its scene and count objects."""
        self.project = project
        self.up_axis = project.meta.up_axis
        self.meters_per_unit = project.meta.meters_per_unit
        self.stage_path = project.scene_path
        self.stage = stage_utils.open_stage(project.scene_path)
        self.object_count = len(inspection_utils.list_prims(self.stage))
        self.mark_saved()

    def touch_project(self) -> None:
        """Persist updated_at on the bound project, if any."""
        if self.project is not None:
            self.project.save()

    def _hash_file(self, path: Path) -> str:
        """Hash a file with blake2b."""
        with path.open("rb") as f:
            return hashlib.file_digest(f, lambda: hashlib.blake2b(digest_size=16)).hexdigest()

    def _watched_layer_paths(self) -> list[Path]:
        """Every file the open scene reads: scene.usda and each layer it uses (assets included)."""
        if self.stage_path is None or not self.stage_path.exists():
            return []
        if self.stage is None:
            return [self.stage_path]
        paths: set[Path] = set()
        for layer in self.stage.GetUsedLayers():
            if layer.realPath:
                package_or_file, _ = Ar.SplitPackageRelativePathOuter(layer.realPath)
                paths.add(Path(package_or_file))
        return sorted(paths)

    def _scene_layer_path(self) -> Path | None:
        """The file of the scene's root layer, as the watched paths spell it."""
        if self.stage is not None:
            return Path(self.stage.GetRootLayer().realPath)
        return self.stage_path

    def mark_saved(self) -> None:
        """Snapshot every watched layer: its mtime, plus a content hash for scene.usda."""
        self.layer_baselines = {}
        scene = self._scene_layer_path()
        for layer_path in self._watched_layer_paths():
            if layer_path.exists():
                digest = self._hash_file(layer_path) if layer_path == scene else None
                self.layer_baselines[layer_path] = (layer_path.stat().st_mtime, digest)

    def detect_external_changes(self) -> bool:
        """Return True if any watched layer changed on disk since the last baseline.

        Asset layers compare modification times only (some are tens of MB);
        scene.usda also compares its hash, so touching it without an edit is ignored.
        """
        if not self.layer_baselines:
            return False
        for layer_path in self._watched_layer_paths():
            baseline = self.layer_baselines.get(layer_path)
            exists = layer_path.exists()
            if baseline is None:
                if exists:
                    return True  # appeared since the last baseline
                continue  # still missing, as it was at the last baseline
            mtime, digest = baseline
            if not exists:
                return True
            if layer_path.stat().st_mtime <= mtime:
                continue
            if digest is None or self._hash_file(layer_path) != digest:
                return True
        return False
