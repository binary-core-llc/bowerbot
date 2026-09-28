# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Layout utils — validate, resolve, and expand batch-placement entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bowerbot import schemas


def validate_layout_entries(
    raw_entries: list[Any],
) -> tuple[list[tuple[int, schemas.LayoutEntry]], list[str]]:
    """Validate raw entries into LayoutEntry models, collecting per-entry problems."""
    valid: list[tuple[int, schemas.LayoutEntry]] = []
    problems: list[str] = []
    for idx, raw in enumerate(raw_entries):
        try:
            valid.append((idx, schemas.LayoutEntry.model_validate(raw)))
        except ValidationError as e:
            problems.extend(_render_entry_error(idx, e))
    return valid, problems


def resolve_layout_asset(
    raw: str,
    *,
    project_dir: Path | None,
    library_dir: Path | None,
) -> Path:
    """Resolve an entry's asset to an existing root file, never falling back to the CWD."""
    path = Path(raw)
    if path.is_absolute():
        candidates = [path]
    else:
        roots = (project_dir, library_dir)
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


def count_entry(entry: schemas.LayoutEntry) -> int:
    """Return how many placements an entry expands to, without materializing them."""
    if entry.transforms is not None:
        return len(entry.transforms)
    pattern = entry.pattern
    if pattern.type == schemas.LayoutPattern.GRID:
        nx, ny, nz = _pad3(pattern.count, 1)
        return nx * ny * nz
    return pattern.count


def expand_entry(entry: schemas.LayoutEntry) -> list[schemas.TransformParams]:
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
    translate: schemas.Vec3, rotate: schemas.Vec3 | None, scale: float | schemas.Vec3 | None,
) -> schemas.TransformParams:
    """Build a TransformParams, letting the schema supply identity rotate/scale."""
    fields: dict[str, schemas.Vec3] = {"translate": translate}
    if rotate is not None:
        fields["rotate"] = rotate
    if scale is not None:
        fields["scale"] = (
            (scale, scale, scale) if isinstance(scale, (int, float)) else scale
        )
    return schemas.TransformParams(**fields)


def _expand_pattern(pattern: schemas.GridPattern | schemas.LinearPattern) -> list[schemas.Vec3]:
    """Generate translate tuples for a grid or linear pattern."""
    ox, oy, oz = pattern.origin
    sx, sy, sz = _pad3(pattern.spacing, 0.0)
    if pattern.type == schemas.LayoutPattern.GRID:
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
