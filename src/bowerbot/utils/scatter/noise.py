# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter noise — patchy density variation from lattice value noise."""

from __future__ import annotations

import numpy as np

from bowerbot.schemas import (
    ScatterSurfaceParams,
    SurfaceTriangles,
)
from bowerbot.schemas.surface import FloatArray, IntArray
from bowerbot.utils import surface_utils
from bowerbot.utils.scatter.regions import region_plan_bounds


def density_noise(points: FloatArray, scale: float, seed: int) -> FloatArray:
    """Smooth, seeded 3D noise in [0, 1] with features about *scale* across."""
    total = np.zeros(points.shape[0])
    amp_sum = 0.0
    for octave in range(3):
        freq = 2.0 ** octave
        amp = 0.5 ** octave
        offset = 17.31 * (octave + 1)
        total += amp * _value_noise(points * (freq / scale) + offset, seed + octave)
        amp_sum += amp
    n = total / amp_sum
    n = np.clip((n - 0.5) * 2.5 + 0.5, 0.0, 1.0)
    return n * n * (3.0 - 2.0 * n)


def variation_scale(
    surface: ScatterSurfaceParams, triangles: SurfaceTriangles, up: int,
) -> float:
    """Variation feature size: explicit, else a fifth of the covered extent."""
    if surface.variation_scale is not None:
        return surface.variation_scale
    bounds = region_plan_bounds(surface.region, up) or surface_utils.plan_bounds(triangles, up)
    return max(float(np.max(bounds[1] - bounds[0])) / 5.0, 1e-6)


def _value_noise(p: FloatArray, seed: int) -> FloatArray:
    """Trilinear value noise on an integer lattice hashed with *seed*."""
    cell = np.floor(p)
    f = p - cell
    f = f * f * (3.0 - 2.0 * f)
    base = cell.astype(np.int64)
    result = np.zeros(p.shape[0])
    for dx in (0, 1):
        wx = f[:, 0] if dx else 1.0 - f[:, 0]
        for dy in (0, 1):
            wy = f[:, 1] if dy else 1.0 - f[:, 1]
            for dz in (0, 1):
                wz = f[:, 2] if dz else 1.0 - f[:, 2]
                h = _lattice_hash(base[:, 0] + dx, base[:, 1] + dy, base[:, 2] + dz, seed)
                result += wx * wy * wz * h
    return result


def _lattice_hash(ix: IntArray, iy: IntArray, iz: IntArray, seed: int) -> FloatArray:
    """Deterministic hash of lattice coordinates to [0, 1) (splitmix64 finalizer)."""
    h = (
        ix.astype(np.uint64) * np.uint64(0x9E3779B185EBCA87)
        ^ iy.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)
        ^ iz.astype(np.uint64) * np.uint64(0x165667B19E3779F9)
        ^ np.uint64((seed * 0x27D4EB2F165667C5) & 0xFFFFFFFFFFFFFFFF)
    )
    h ^= h >> np.uint64(30)
    h *= np.uint64(0xBF58476D1CE4E5B9)
    h ^= h >> np.uint64(27)
    h *= np.uint64(0x94D049BB133111EB)
    h ^= h >> np.uint64(31)
    top_bits: FloatArray = (h >> np.uint64(11)).astype(np.float64)
    return top_bits / float(1 << 53)
