# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter piles — heaping pieces under a repose cone."""

from __future__ import annotations

import math

import numpy as np

from bowerbot.schemas import (
    ScatterPrototype,
    ScatterRules,
    ScatterSurfaceParams,
    ScatterTuning,
    SurfaceIndex,
)
from bowerbot.schemas.surface import BoolArray, FloatArray, IntArray
from bowerbot.utils import surface_utils
from bowerbot.utils.core.metrics import horizontal_axes, up_vector
from bowerbot.utils.scatter.orientation import quat_axis_angle, quat_mul, quat_rotate
from bowerbot.utils.scatter.regions import plan_to_world, region_circle


def pile_instances(
    rng: np.random.Generator,
    index: SurfaceIndex,
    prototypes: list[ScatterPrototype],
    proto_idx: IntArray,
    scales: FloatArray,
    *,
    up: int,
    center: FloatArray,
    radius: float,
    repose_degrees: float,
    tilt_degrees: float,
) -> tuple[FloatArray, FloatArray, BoolArray, float]:
    """Heap pieces under a repose cone, resting on the ground and on each other."""
    n = proto_idx.shape[0]
    if n > ScatterRules.MAX_PILE_PIECES:
        msg = f"a pile holds at most {ScatterRules.MAX_PILE_PIECES:,} pieces per call."
        raise ValueError(msg)
    axes = list(horizontal_axes(up))
    slope = math.tan(math.radians(repose_degrees))
    orientations = pile_orientations(rng, prototypes, proto_idx, up, tilt_degrees)

    extents = np.array([np.subtract(p.bounds_max, p.bounds_min) for p in prototypes])
    sizes = extents[proto_idx] * scales
    reach = float(sizes.max())
    volume = float(np.prod(sizes, axis=1).sum()) * ScatterTuning.PILE_SOLIDITY
    natural = (3.0 * volume / (math.pi * max(slope, 1e-3))) ** (1.0 / 3.0)
    half = max(radius, 1.5 * natural) + reach
    cell = max(float(sizes.min()) / 4.0, 2.0 * half / ScatterTuning.PILE_GRID)
    dims = int(2.0 * half / cell) + 1
    c_plan = center[axes]
    origin = c_plan - half
    ga = origin[0] + (np.arange(dims) + 0.5) * cell
    gb = origin[1] + (np.arange(dims) + 0.5) * cell
    aa, bb = np.meshgrid(ga, gb, indexing="ij")
    probe = plan_to_world(np.stack([aa.ravel(), bb.ravel()], axis=1), up)
    hit, heights, _ = surface_utils.surface_under(index, probe, mode="top")
    field = np.where(hit, heights, np.nan).reshape(dims, dims)
    if np.isnan(field).all():
        msg = "no surface lies under the pile region; check the region centre and surfaces."
        raise ValueError(msg)
    ground = field.copy()
    distance = np.hypot(aa - c_plan[0], bb - c_plan[1])

    positions = np.zeros((n, 3))
    placed = np.zeros(n, dtype=bool)
    base_radius = radius
    max_radius = half - reach
    for i in range(n):
        proto = prototypes[int(proto_idx[i])]
        pts = quat_rotate(
            np.repeat(orientations[i:i + 1], proto.points.shape[0], axis=0),
            proto.points * scales[i],
        )
        # Piece underside and top per heightfield cell, around a cell-centred pivot.
        da = np.floor(pts[:, axes[0]] / cell + 0.5).astype(np.int64)
        db = np.floor(pts[:, axes[1]] / cell + 0.5).astype(np.int64)
        cells, inverse = np.unique(np.stack([da, db], axis=1), axis=0, return_inverse=True)
        inverse = inverse.ravel()
        under = np.full(cells.shape[0], np.inf)
        over = np.full(cells.shape[0], -np.inf)
        np.minimum.at(under, inverse, pts[:, up])
        np.maximum.at(over, inverse, pts[:, up])
        lowest = float(under.min())

        best: tuple[float, int, int, float] | None = None
        for _ in range(ScatterTuning.PILE_GROWTH_STEPS):
            dist = base_radius * np.sqrt(rng.random(ScatterTuning.PILE_TRIES))
            angle = rng.random(ScatterTuning.PILE_TRIES) * 2.0 * math.pi
            ia = np.floor((c_plan[0] + dist * np.cos(angle) - origin[0]) / cell).astype(np.int64)
            ib = np.floor((c_plan[1] + dist * np.sin(angle) - origin[1]) / cell).astype(np.int64)
            ca = ia[:, None] + cells[None, :, 0]
            cb = ib[:, None] + cells[None, :, 1]
            inside = ((ca >= 0) & (ca < dims) & (cb >= 0) & (cb < dims)).all(axis=1)
            below = field[np.clip(ca, 0, dims - 1), np.clip(cb, 0, dims - 1)]
            valid = inside & ~np.isnan(below).any(axis=1)
            if not valid.any():
                continue
            rest = np.where(valid, (below - under[None, :]).max(axis=1), np.inf)
            env = (
                ground[ia.clip(0, dims - 1), ib.clip(0, dims - 1)]
                + np.maximum(base_radius - distance[ia.clip(0, dims - 1), ib.clip(0, dims - 1)],
                             0.0) * slope
            )
            excess = np.where(valid, rest + lowest - env, np.inf)
            k = int(np.argmin(excess))
            if best is None or excess[k] < best[0]:
                best = (float(excess[k]), int(ia[k]), int(ib[k]), float(rest[k]))
            fits = np.flatnonzero(excess <= 1e-6)
            if fits.size:
                # Settle into the lowest spot that fits.
                k = int(fits[np.argmin(rest[fits] + lowest)])
                best = (float(excess[k]), int(ia[k]), int(ib[k]), float(rest[k]))
                break
            base_radius = min(base_radius * ScatterTuning.PILE_GROWTH, max_radius)
        if best is None:
            continue

        _, pa, pb, rest_height = best
        ca, cb = pa + cells[:, 0], pb + cells[:, 1]
        field[ca, cb] = np.fmax(field[ca, cb], over + rest_height)
        positions[i, axes[0]] = origin[0] + (pa + 0.5) * cell
        positions[i, axes[1]] = origin[1] + (pb + 0.5) * cell
        positions[i, up] = rest_height
        placed[i] = True

    return positions, orientations, placed, base_radius


def pile_orientations(
    rng: np.random.Generator,
    prototypes: list[ScatterPrototype],
    proto_idx: IntArray,
    up: int,
    tilt_degrees: float,
) -> FloatArray:
    """Lay each piece on its flattest side with a random spin and a small tilt."""
    n = int(proto_idx.shape[0])
    up_vec = up_vector(up)
    axes = horizontal_axes(up)
    extents = np.array([np.subtract(p.bounds_max, p.bounds_min) for p in prototypes])[proto_idx]
    thin = np.argmin(extents, axis=1)
    q = np.tile([1.0, 0.0, 0.0, 0.0], (n, 1))
    lay = thin != up
    if lay.any():
        # A quarter turn about the third axis stands the thinnest axis up.
        turn = np.zeros((n, 3))
        turn[np.flatnonzero(lay), 3 - thin[lay] - up] = 1.0
        q[lay] = quat_axis_angle(turn[lay], np.full(int(lay.sum()), math.pi / 2.0))
    flip_axis = np.zeros(3)
    flip_axis[axes[0]] = 1.0
    q = quat_mul(quat_axis_angle(flip_axis, np.where(rng.random(n) < 0.5, math.pi, 0.0)), q)
    q = quat_mul(quat_axis_angle(up_vec, rng.random(n) * 2.0 * math.pi), q)
    phi = rng.random(n) * 2.0 * math.pi
    tilt_axis = np.zeros((n, 3))
    tilt_axis[:, axes[0]] = np.cos(phi)
    tilt_axis[:, axes[1]] = np.sin(phi)
    tilt = rng.random(n) * math.radians(tilt_degrees)
    return quat_mul(quat_axis_angle(tilt_axis, tilt), q)


def pile_setup(surface: ScatterSurfaceParams) -> tuple[int, FloatArray, float]:
    """A pile's piece count, centre and base radius."""
    region = surface.region
    if surface.count is None or region is None or region.polygon is not None:
        msg = "arrangement 'pile' needs a count and a circular region."
        raise ValueError(msg)
    center, radius = region_circle(region)
    return surface.count, center, radius
