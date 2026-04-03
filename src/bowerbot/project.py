# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Project management — one folder, one scene.

A project is a self-contained directory with everything needed
to build and resume a scene:

    my_project/
      project.json     ← Metadata and state
      scene.usda       ← The USD stage
      scene.usdz       ← Packaged output
      assets/          ← Assets used by this project
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from bowerbot.engine.stage_writer import StageWriter
from bowerbot.utils.naming import safe_project_name


class ProjectMeta(BaseModel):
    """Metadata stored in project.json."""

    name: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scene_file: str = "scene.usda"


class Project:
    """A BowerBot project — one folder, one scene.

    Handles creating, loading, saving, and providing paths.
    Delegates USD operations to the engine layer.
    """

    def __init__(self, path: Path, meta: ProjectMeta) -> None:
        self.path = path
        self.meta = meta

    @property
    def name(self) -> str:
        return self.meta.name

    @property
    def scene_path(self) -> Path:
        return self.path / self.meta.scene_file

    @property
    def assets_dir(self) -> Path:
        return self.path / "assets"

    @property
    def meta_path(self) -> Path:
        return self.path / "project.json"

    @property
    def usdz_path(self) -> Path:
        return self.scene_path.with_suffix(".usdz")

    def save(self) -> None:
        """Save project metadata to project.json."""
        self.meta.updated_at = datetime.now(timezone.utc).isoformat()
        self.meta_path.write_text(
            json.dumps(self.meta.model_dump(), indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def create(projects_dir: Path, name: str) -> Project:
        """Create a new project directory and initialize it."""
        safe_name = safe_project_name(name)
        if not safe_name:
            safe_name = "untitled"

        project_path = projects_dir / safe_name
        if project_path.exists():
            msg = f"Project already exists: {project_path}"
            raise FileExistsError(msg)

        # Create directory structure
        project_path.mkdir(parents=True)
        (project_path / "assets").mkdir()

        # Create and save metadata
        meta = ProjectMeta(name=name)
        project = Project(path=project_path, meta=meta)
        project.save()

        # Create empty scene file
        StageWriter.create_empty_scene(project.scene_path)

        return project

    @staticmethod
    def load(project_path: Path) -> Project:
        """Load an existing project from a directory.

        Ensures the project's on-disk state is valid:
        missing directories or scene files are recreated.
        """
        meta_path = project_path / "project.json"
        if not meta_path.exists():
            msg = (
                f"Not a BowerBot project: "
                f"{project_path} (no project.json)"
            )
            raise FileNotFoundError(msg)

        raw = json.loads(
            meta_path.read_text(encoding="utf-8"),
        )
        meta = ProjectMeta(**raw)
        project = Project(path=project_path, meta=meta)

        # Ensure project invariants
        project.assets_dir.mkdir(parents=True, exist_ok=True)
        StageWriter.create_empty_scene(project.scene_path)

        return project

    @staticmethod
    def detect(directory: Path) -> Project | None:
        """Try to detect a project in the given directory or parents."""
        current = directory.resolve()
        while current != current.parent:
            if (current / "project.json").exists():
                return Project.load(current)
            current = current.parent
        return None

    @staticmethod
    def list_projects(projects_dir: Path) -> list[Project]:
        """List all projects in a directory."""
        if not projects_dir.exists():
            return []

        projects = []
        for child in sorted(projects_dir.iterdir()):
            if child.is_dir() and (child / "project.json").exists():
                try:
                    projects.append(Project.load(child))
                except Exception:
                    continue
        return projects
