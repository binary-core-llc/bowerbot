# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter resting — seating each piece on the ground under its base."""

from __future__ import annotations

import math

import numpy as np

from bowerbot.schemas import (
    ScatterPrototype,
    ScatterTuning,
    SurfaceIndex,
    SurfaceTuning,
)
from bowerbot.schemas.surface import BoolArray, FloatArray, IntArray
from bowerbot.utils import surface_utils
from bowerbot.utils.core.metrics import horizontal_axes, up_vector
from bowerbot.utils.scatter.orientation import quat_rotate
from bowerbot.utils.scatter.prototypes import prototype_bases


def rest_positions(
    contacts: FloatArray,
    orientations: FloatArray,
    scales: FloatArray,
    prototypes: list[ScatterPrototype],
    proto_idx: IntArray,
    up: int,
    *,
    embed: float,
    settle: BoolArray,
    index: SurfaceIndex | None,
) -> FloatArray:
    """Set each piece's base centre on its contact point, then settle and embed it."""
    bmin = np.stack([p.bounds_min for p in prototypes])[proto_idx]
    bmax = np.stack([p.bounds_max for p in prototypes])[proto_idx]
    base_min, base_max = prototype_bases(prototypes, proto_idx)
    base = (base_min + base_max) / 2.0
    up_vec = up_vector(up)
    positions = contacts - quat_rotate(orientations, base * scales)
    if index is not None and settle.any():
        samples = base_samples(
            positions[settle], orientations[settle], scales[settle],
            base_min[settle], base_max[settle], up,
        )
        shift, _ = settle_shift(index, samples, up)
        positions[settle, up] += shift
    height = (bmax[:, up] - bmin[:, up]) * scales[:, up]
    if embed > 0:
        local_up = quat_rotate(orientations, np.broadcast_to(up_vec, contacts.shape))
        positions -= local_up * (embed * height)[:, None]
    return positions


def ground_normals(
    index: SurfaceIndex,
    contacts: FloatArray,
    headings: FloatArray,
    scales: FloatArray,
    base_min: FloatArray,
    base_max: FloatArray,
    fallback: FloatArray,
    up: int,
) -> tuple[FloatArray, BoolArray]:
    """Normal of the ground fitted under each base footprint, else *fallback*."""
    axes = list(horizontal_axes(up))
    center = (base_min + base_max) / 2.0
    positions = contacts - quat_rotate(headings, center * scales)
    samples = base_samples(positions, headings, scales, base_min, base_max, up)
    n, k, _ = samples.shape
    flat = samples.reshape(-1, 3)
    hit, heights, _ = surface_utils.surface_under(
        index, flat, mode="nearest", reference=flat[:, up].copy(),
    )
    w = hit.reshape(n, k).astype(np.float64)
    a = samples[:, :, axes[0]] - contacts[:, None, axes[0]]
    b = samples[:, :, axes[1]] - contacts[:, None, axes[1]]
    h = np.where(hit, heights, 0.0).reshape(n, k) - contacts[:, None, up]
    count = np.maximum(w.sum(axis=1), 1.0)

    def mean(v: FloatArray) -> FloatArray:
        return (w * v).sum(axis=1) / count

    ma, mb, mh = mean(a), mean(b), mean(h)
    caa = mean(a * a) - ma * ma
    cbb = mean(b * b) - mb * mb
    cab = mean(a * b) - ma * mb
    cah = mean(a * h) - ma * mh
    cbh = mean(b * h) - mb * mh
    det = caa * cbb - cab * cab
    fitted = (
        (w.sum(axis=1) >= 3)
        & (det > 1e-6 * (caa + cbb) ** 2 + SurfaceTuning.EPS)
        & (fallback[:, up] >= math.cos(math.radians(ScatterTuning.FIT_MAX_SLOPE_DEGREES)))
    )
    safe = np.where(fitted, det, 1.0)
    normals = np.zeros((n, 3))
    normals[:, axes[0]] = -(cah * cbb - cbh * cab) / safe
    normals[:, axes[1]] = -(cbh * caa - cah * cab) / safe
    normals[:, up] = 1.0
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    return np.where(fitted[:, None], normals, fallback), fitted


def base_samples(
    positions: FloatArray,
    orientations: FloatArray,
    scales: FloatArray,
    base_min: FloatArray,
    base_max: FloatArray,
    up: int,
) -> FloatArray:
    """``(n, k, 3)`` points on each piece's base footprint, in the positions' frame."""
    axes = list(horizontal_axes(up))
    t = np.linspace(0.0, 1.0, ScatterTuning.BASE_GRID)
    ta, tb = (g.ravel() for g in np.meshgrid(t, t, indexing="ij"))
    n, k = positions.shape[0], ta.size
    local = np.repeat(base_min[:, None, :], k, axis=1)
    extent = base_max - base_min
    local[:, :, axes[0]] += ta[None, :] * extent[:, None, axes[0]]
    local[:, :, axes[1]] += tb[None, :] * extent[:, None, axes[1]]
    local *= scales[:, None, :]
    rotated = quat_rotate(np.repeat(orientations, k, axis=0), local.reshape(-1, 3))
    return positions[:, None, :] + rotated.reshape(n, k, 3)


def settle_shift(
    index: SurfaceIndex, samples: FloatArray, up: int,
) -> tuple[FloatArray, BoolArray]:
    """Up shift that lands each piece's highest base sample on the surface."""
    n, k, _ = samples.shape
    flat = samples.reshape(-1, 3)
    hit, heights, _ = surface_utils.surface_under(
        index, flat, mode="nearest", reference=flat[:, up].copy(),
    )
    gap = np.where(hit, flat[:, up] - np.where(hit, heights, 0.0), -np.inf).reshape(n, k)
    worst = gap.max(axis=1)
    supported = np.isfinite(worst)
    return np.where(supported, -worst, 0.0), supported
