# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""How a golden scenario is written: named steps of tool calls, convention-neutral.

Positions are in meters with Y up; ``$name`` names an earlier result, ``$lib`` the library.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass(frozen=True)
class Convention:
    """A project's up axis and units."""

    key: str
    up_axis: str
    meters_per_unit: float


Y_M = Convention("y_m", "Y", 1.0)
Z_CM = Convention("z_cm", "Z", 0.01)
CONVENTIONS = (Y_M, Z_CM)


@dataclass(frozen=True)
class Meters:
    """A length in meters, written in the project's units when the step runs."""

    value: float


@dataclass(frozen=True)
class Point:
    """A point in meters, Y up: ``x`` right, ``up``, ``depth`` toward the viewer."""

    x: float
    up: float
    depth: float


def at(x: float, up: float = 0.0, depth: float = 0.0) -> dict[str, Point]:
    """``translate_x/y/z`` params for a point, converted to the project's convention.

    A :class:`Point` under any other key becomes an ``[x, y, z]`` list.
    """
    return {"translate": Point(x, up, depth)}


def in_convention(point: Point, convention: Convention) -> tuple[float, float, float]:
    """*point* in *convention*'s axes and units (Z up maps (x, up, depth) to (x, -depth, up))."""
    x, y, z = (
        (point.x, point.up, point.depth) if convention.up_axis == "Y"
        else (point.x, -point.depth, point.up)
    )
    scale = 1.0 / convention.meters_per_unit
    return (round(x * scale, 9) + 0.0, round(y * scale, 9) + 0.0, round(z * scale, 9) + 0.0)


@dataclass(frozen=True)
class Step:
    """One tool call; *save* keeps a result field under a name later steps use as ``$name``."""

    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    save: str | None = None
    save_key: str = "prim_path"
    note: str = ""


@dataclass(frozen=True)
class Scenario:
    """A named sequence of steps, run once per convention, starting with ``create_project``."""

    name: str
    description: str
    steps: tuple[Step, ...]
    conventions: tuple[Convention, ...] = CONVENTIONS
    open_project: bool = True
    library: bool = True
