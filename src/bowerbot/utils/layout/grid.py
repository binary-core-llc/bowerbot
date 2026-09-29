# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Suggested grid layouts: ``(x, y, z)`` positions for a number of objects."""

from __future__ import annotations

import math


def suggest(
    count: int,
    *,
    spacing: float = 2.0,
    room_bounds: tuple[float, float, float] = (10.0, 3.0, 8.0),
    center: tuple[float, float] | None = None,
) -> list[tuple[float, float, float]]:
    """Compute ``(x, y, z)`` positions for *count* objects in a grid."""
    if count <= 0:
        return []

    room_width, _, room_depth = room_bounds
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)

    cx = center[0] if center else room_width / 2
    cz = center[1] if center else room_depth / 2

    x_offset = cx - (cols - 1) * spacing / 2
    z_offset = cz - (rows - 1) * spacing / 2

    placements: list[tuple[float, float, float]] = []
    for i in range(count):
        row = i // cols
        col = i % cols
        x = x_offset + col * spacing
        z = z_offset + row * spacing
        placements.append((x, 0.0, z))
    return placements
