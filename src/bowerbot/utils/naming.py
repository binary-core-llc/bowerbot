# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Name sanitization utilities.

Consistent rules for generating safe names across the codebase:
- File/folder names: alphanumeric, underscores, hyphens
- USD prim names: alphanumeric, underscores only (per USD spec)
- Project names: same as file names, with spaces converted to underscores
"""


def safe_file_name(name: str) -> str:
    """Sanitize a string for use as a file or folder name."""
    return "".join(
        c for c in name if c.isalnum() or c in "_-"
    ).strip()


def safe_prim_name(name: str) -> str:
    """Sanitize a string for use as a USD prim name.

    USD prim names only allow alphanumeric characters and
    underscores — no hyphens, spaces, or special characters.
    """
    return "".join(
        c for c in name if c.isalnum() or c == "_"
    ).strip()


def safe_project_name(name: str) -> str:
    """Sanitize a string for use as a project folder name.

    Allows spaces during sanitization, then converts them to
    underscores and lowercases the result.
    """
    cleaned = "".join(
        c for c in name if c.isalnum() or c in "_- "
    ).strip()
    return cleaned.replace(" ", "_").lower()
