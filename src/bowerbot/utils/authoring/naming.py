# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Names of BowerBot's files and folders: projects, the scene and its snapshots."""


def safe_project_name(name: str) -> str:
    """Sanitize a string into a project folder name: lowercase, spaces to underscores."""
    cleaned = "".join(
        c for c in name if c.isalnum() or c in "_- "
    ).strip()
    return cleaned.replace(" ", "_").lower()


def safe_file_name(name: str) -> str:
    """Sanitize a string for use as a file or folder name."""
    return "".join(
        c for c in name if c.isalnum() or c in "_-"
    ).strip()
