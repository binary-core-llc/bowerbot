# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test project management."""

import tempfile
from pathlib import Path

from bowerbot.project import Project, ProjectMeta


def test_create_project():
    """Test 1: Create a new project."""
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp)
        project = Project.create(projects_dir, "Coffee Shop")

        assert project.path.exists()
        assert project.path.name == "coffee_shop"
        assert project.assets_dir.exists()
        assert project.meta_path.exists()
        assert project.name == "Coffee Shop"
        assert project.scene_path == project.path / "scene.usda"
        assert project.scene_path.exists()

        print(f"✅ test_create_project PASSED — {project.path}")


def test_load_project():
    """Test 2: Load an existing project."""
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp)
        original = Project.create(projects_dir, "Test Scene")

        loaded = Project.load(original.path)
        assert loaded.name == "Test Scene"
        assert loaded.scene_path == original.scene_path

        print("✅ test_load_project PASSED")


def test_save_updates_timestamp():
    """Test 3: Saving updates the updated_at timestamp."""
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp)
        project = Project.create(projects_dir, "Timestamp Test")

        original_time = project.meta.updated_at
        project.save()

        reloaded = Project.load(project.path)
        assert reloaded.meta.updated_at >= original_time

        print("✅ test_save_updates_timestamp PASSED")


def test_detect_project():
    """Test 4: Detect a project from a subdirectory."""
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp)
        project = Project.create(projects_dir, "Detect Me")

        # Detect from the project root
        found = Project.detect(project.path)
        assert found is not None
        assert found.name == "Detect Me"

        # Detect from the assets subdirectory
        found = Project.detect(project.assets_dir)
        assert found is not None
        assert found.name == "Detect Me"

        # Detect from unrelated directory — should return None
        found = Project.detect(projects_dir)
        assert found is None

        print("✅ test_detect_project PASSED")


def test_list_projects():
    """Test 5: List all projects."""
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp)
        Project.create(projects_dir, "Alpha")
        Project.create(projects_dir, "Beta")
        Project.create(projects_dir, "Gamma")

        projects = Project.list_projects(projects_dir)
        names = [p.name for p in projects]

        assert len(projects) == 3
        assert "Alpha" in names
        assert "Beta" in names
        assert "Gamma" in names

        print(f"✅ test_list_projects PASSED — {names}")


def test_duplicate_project_fails():
    """Test 6: Can't create two projects with same name."""
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp)
        Project.create(projects_dir, "Unique")

        try:
            Project.create(projects_dir, "Unique")
            assert False, "Should have raised FileExistsError"
        except FileExistsError:
            pass

        print("✅ test_duplicate_project_fails PASSED")


if __name__ == "__main__":
    test_create_project()
    test_load_project()
    test_save_updates_timestamp()
    test_detect_project()
    test_list_projects()
    test_duplicate_project_fails()
    print("\n🎉 All project tests passed!")
