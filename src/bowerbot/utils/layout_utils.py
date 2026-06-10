# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Layout utils — parse, validate, resolve, and expand batch-placement entries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bowerbot.schemas import (
    LAYOUT_FILE_VERSION,
    GridPattern,
    LayoutEntry,
    LayoutPattern,
    LinearPattern,
    TransformParams,
)
from bowerbot.utils.naming_utils import is_valid_prim_name, safe_prim_name

Vec3 = tuple[float, float, float]


def resolve_layout_file(raw: str, project_dir: Path | None) -> Path:
    """Resolve a layout_file argument to an existing file, absolute or project-relative."""
    path = Path(raw)
    candidates = [path] if path.is_absolute() else (
        [project_dir / raw] if project_dir is not None else []
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(c) for c in candidates) or "no project open"
    msg = (
        f"layout_file '{raw}' not found (searched: {searched}). "
        f"Pass an absolute path or a project-relative path."
    )
    raise ValueError(msg)


def parse_layout_file(file: Path) -> list[Any]:
    """Read a versioned layout JSON file and return its raw placements list."""
    try:
        data = json.loads(file.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        msg = f"layout_file is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}"
        raise ValueError(msg) from e
    except UnicodeDecodeError as e:
        msg = "layout_file is not UTF-8 encoded; re-save the file as UTF-8."
        raise ValueError(msg) from e
    except OSError as e:
        msg = f"layout_file could not be read: {e}"
        raise ValueError(msg) from e
    if not isinstance(data, dict):
        msg = 'layout_file must be an object: {"version": 1, "placements": [...]}.'
        raise ValueError(msg)
    version = data.get("version")
    if version != LAYOUT_FILE_VERSION:
        msg = (
            f"unsupported layout_file version {version!r}; "
            f"this BowerBot reads version {LAYOUT_FILE_VERSION}."
        )
        raise ValueError(msg)
    placements = data.get("placements")
    if not isinstance(placements, list) or not placements:
        msg = "layout_file needs a non-empty 'placements' list."
        raise ValueError(msg)
    return placements


def validate_layout_entries(
    raw_entries: list[Any],
) -> tuple[list[tuple[int, LayoutEntry]], list[str]]:
    """Validate raw entries into LayoutEntry models, collecting per-entry problems."""
    valid: list[tuple[int, LayoutEntry]] = []
    problems: list[str] = []
    for idx, raw in enumerate(raw_entries):
        try:
            valid.append((idx, LayoutEntry.model_validate(raw)))
        except ValidationError as e:
            problems.extend(_render_entry_error(idx, e))
    return valid, problems


def resolve_layout_asset(
    raw: str,
    *,
    layout_dir: Path | None,
    project_dir: Path | None,
    library_dir: Path | None,
) -> Path:
    """Resolve an entry's asset to an existing root file, never falling back to the CWD."""
    path = Path(raw)
    if path.is_absolute():
        candidates = [path]
    else:
        roots = (layout_dir, project_dir, library_dir)
        candidates = [root / raw for root in roots if root is not None]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    for candidate in candidates:
        if candidate.is_dir():
            msg = (
                f"'{raw}' is a folder ({candidate}); reference the asset's root "
                f"file instead (e.g. '{candidate.name}/{candidate.name}.usda')."
            )
            raise ValueError(msg)
    searched = ", ".join(str(c) for c in candidates) or "no roots available"
    msg = f"asset '{raw}' not found (searched: {searched})."
    raise ValueError(msg)


def scene_group_path(group: str) -> str:
    """Build the /Scene scope path for a group, sanitizing each nested segment."""
    segments = [name for seg in group.split("/") if (name := safe_prim_name(seg))]
    if not segments:
        msg = "a layout entry 'group' must name a non-empty scene scope."
        raise ValueError(msg)
    for segment in segments:
        if not is_valid_prim_name(segment):
            msg = (
                f"group segment '{segment}' is not a valid USD prim name "
                f"(it must start with a letter or underscore)."
            )
            raise ValueError(msg)
    return "/Scene/" + "/".join(segments)


def count_entry(entry: LayoutEntry) -> int:
    """Return how many placements an entry expands to, without materializing them."""
    if entry.transforms is not None:
        return len(entry.transforms)
    pattern = entry.pattern
    if pattern.type == LayoutPattern.GRID:
        nx, ny, nz = _pad3(pattern.count, 1)
        return nx * ny * nz
    return pattern.count


def expand_entry(entry: LayoutEntry) -> list[TransformParams]:
    """Expand one validated entry into per-instance transforms."""
    if entry.transforms is not None:
        return [
            _transform(
                item.translate,
                item.rotate if item.rotate is not None else entry.rotate,
                item.scale if item.scale is not None else entry.scale,
            )
            for item in entry.transforms
        ]
    return [
        _transform(translate, entry.rotate, entry.scale)
        for translate in _expand_pattern(entry.pattern)
    ]


def _render_entry_error(idx: int, error: ValidationError) -> list[str]:
    """Render one entry's ValidationError as indexed problem lines."""
    lines: list[str] = []
    for err in error.errors():
        loc = ".".join(str(part) for part in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        prefix = f"placements[{idx}]" + (f".{loc}" if loc else "")
        lines.append(f"{prefix}: {msg}")
    return lines


def _transform(
    translate: Vec3, rotate: Vec3 | None, scale: float | Vec3 | None,
) -> TransformParams:
    """Build a TransformParams, letting the schema supply identity rotate/scale."""
    fields: dict[str, Vec3] = {"translate": translate}
    if rotate is not None:
        fields["rotate"] = rotate
    if scale is not None:
        fields["scale"] = (
            (scale, scale, scale) if isinstance(scale, (int, float)) else scale
        )
    return TransformParams(**fields)


def _expand_pattern(pattern: GridPattern | LinearPattern) -> list[Vec3]:
    """Generate translate tuples for a grid or linear pattern."""
    ox, oy, oz = pattern.origin
    sx, sy, sz = _pad3(pattern.spacing, 0.0)
    if pattern.type == LayoutPattern.GRID:
        nx, ny, nz = _pad3(pattern.count, 1)
        return [
            (ox + i * sx, oy + j * sy, oz + k * sz)
            for k in range(nz)
            for j in range(ny)
            for i in range(nx)
        ]
    return [
        (ox + i * sx, oy + i * sy, oz + i * sz)
        for i in range(pattern.count)
    ]


def _pad3(values: tuple, fill: float | int) -> tuple:
    """Pad a 2-tuple to 3 with the identity value for the missing axis."""
    return (*values, fill) if len(values) == 2 else tuple(values)
