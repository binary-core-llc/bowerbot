# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Naming — prim and variant name rules, name sanitizers, unique prim paths."""

from __future__ import annotations

import re

from pxr import Usd

from bowerbot.schemas import NamingRules


def is_valid_prim_name(name: str) -> bool:
    """Whether *name* is a legal USD prim identifier."""
    return re.fullmatch(NamingRules.PRIM_NAME_PATTERN, name) is not None


def validate_prim_name(name: str, label: str) -> None:
    """Raise ``ValueError`` unless *name* is a legal USD prim identifier."""
    if not name:
        raise ValueError(f"{label} name cannot be empty.")
    if not is_valid_prim_name(name):
        raise ValueError(
            f"{label} name {name!r} is not a valid USD prim name; use letters, "
            f"digits and underscores, starting with a letter or underscore.",
        )


def is_valid_variant_name(name: str) -> bool:
    """Reject empty names or names with whitespace / path separators."""
    return bool(name) and not any(c in NamingRules.VARIANT_NAME_FORBIDDEN for c in name)


def validate_variant_name(name: str, label: str = "variant") -> None:
    """Raise ``ValueError`` if ``name`` is not a valid variant identifier."""
    if not is_valid_variant_name(name):
        raise ValueError(f"Invalid {label} name: {name!r}")


def safe_variant_name(name: str) -> str:
    """Replace whitespace and path separators in *name* with underscores."""
    return "".join("_" if c in NamingRules.VARIANT_NAME_FORBIDDEN else c for c in name)


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


def unique_prim_path(stage: Usd.Stage, parent: str, base_name: str) -> str:
    """Return ``<parent>/<base_name>`` or the next free ``<parent>/<base_name>_NN``."""
    direct = f"{parent}/{base_name}"
    if not stage.GetPrimAtPath(direct).IsValid():
        return direct
    n = 2
    while True:
        candidate = f"{parent}/{base_name}_{n:02d}"
        if not stage.GetPrimAtPath(candidate).IsValid():
            return candidate
        n += 1
