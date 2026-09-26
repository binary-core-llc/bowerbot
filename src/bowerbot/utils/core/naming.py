# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Naming — prim and variant name rules, name sanitizers, unique prim paths."""

from __future__ import annotations

import re
import unicodedata

from pxr import Usd

from bowerbot.schemas import NamingRules


def is_valid_prim_name(name: str) -> bool:
    """Whether *name* is a legal USD prim (or variant-set) identifier."""
    return re.fullmatch(NamingRules.PRIM_NAME_PATTERN, name) is not None


def clean_prim_name(name: str, label: str, *, fallback: str | None = None) -> str:
    """*name* as a legal prim identifier: kept when valid, else cleaned.

    Accents are dropped ("Lámpara" -> ``Lampara``), runs of other characters
    become ``_`` and a leading digit gets a ``_`` prefix ("Key Light" ->
    ``Key_Light``, "3D Table" -> ``_3D_Table``). When nothing usable is left,
    returns *fallback* (for names derived from file names) or raises ``ValueError``.
    """
    if is_valid_prim_name(name):
        return name
    cleaned = re.sub(NamingRules.PRIM_NAME_INVALID, "_", _fold_accents(name)).strip("_")
    if not cleaned and fallback is not None:
        return fallback
    if not cleaned:
        msg = f"{label} name {name!r} has no ASCII letters or digits to build a name from."
        raise ValueError(msg)
    return f"_{cleaned}" if cleaned[0].isdigit() else cleaned


def clean_prim_path(path: str, label: str) -> str:
    """An absolute prim path with every segment cleaned into a legal prim name."""
    if not path.startswith("/"):
        msg = f"{label} {path!r} must be an absolute prim path (e.g. /Scene/Props/Chair)."
        raise ValueError(msg)
    segments = [clean_prim_name(seg, label) for seg in path.strip("/").split("/") if seg.strip()]
    if not segments:
        msg = f"{label} {path!r} names no prim."
        raise ValueError(msg)
    return "/" + "/".join(segments)


def clean_group(group: str) -> str:
    """A group ("Props", or nested "Props/Small") with each segment cleaned into a prim name."""
    segments = [clean_prim_name(seg, "Group") for seg in group.split("/") if seg.strip()]
    if not segments:
        msg = f"group {group!r} names no scope; pass a group such as 'Furniture'."
        raise ValueError(msg)
    return "/".join(segments)


def is_valid_variant_name(name: str) -> bool:
    """Whether *name* is a legal USD variant name."""
    return re.fullmatch(NamingRules.VARIANT_NAME_PATTERN, name) is not None


def clean_variant_name(name: str, label: str = "Variant") -> str:
    """*name* as a legal variant name: kept when valid, else accents are dropped
    and invalid runs become ``_``."""
    if is_valid_variant_name(name):
        return name
    cleaned = re.sub(NamingRules.VARIANT_NAME_INVALID, "_", _fold_accents(name)).strip("_")
    if not cleaned:
        msg = f"{label} name {name!r} has no ASCII letters or digits to build a name from."
        raise ValueError(msg)
    return cleaned


def _fold_accents(name: str) -> str:
    """*name* with accented letters as their base letter (é -> e); other non-ASCII drops."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")


def safe_file_name(name: str) -> str:
    """Sanitize a string for use as a file or folder name."""
    return "".join(
        c for c in name if c.isalnum() or c in "_-"
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


def next_placement_path(stage: Usd.Stage, parent: str, base: str, counter: int) -> tuple[str, int]:
    """``<parent>/<base>_NN`` for the first free NN above *counter*; returns (path, NN)."""
    number = counter + 1
    while stage.GetPrimAtPath(f"{parent}/{base}_{number:02d}").IsValid():
        number += 1
    return f"{parent}/{base}_{number:02d}", number
