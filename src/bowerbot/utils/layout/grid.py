# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Suggested grid layouts: positions on the floor for a number of objects."""

from __future__ import annotations

import math

from bowerbot.utils import usd


def suggest(
    count: int,
    *,
    spacing: float,
    room_size: tuple[float, float],
    up: int,
) -> list[tuple[float, float, float]]:
    """Compute ``(x, y, z)`` positions for *count* objects in a grid on the floor.

    The grid is centered in a room of *room_size* on the two floor axes of
    up axis *up*; the up coordinate is 0. Lengths are in project units.
    """
    if count <= 0:
        return []

    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    first, second = usd.metrics.horizontal_axes(up)
    first_offset = room_size[0] / 2 - (cols - 1) * spacing / 2
    second_offset = room_size[1] / 2 - (rows - 1) * spacing / 2

    placements: list[tuple[float, float, float]] = []
    for i in range(count):
        position = [0.0, 0.0, 0.0]
        position[first] = first_offset + (i % cols) * spacing
        position[second] = second_offset + (i // cols) * spacing
        placements.append((position[0], position[1], position[2]))
    return placements
