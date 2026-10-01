# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Per-instance choices: prototype, scale, heading, orientation, and resting on the ground."""

from __future__ import annotations

import math

import numpy as np

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import usd


def pick_prototypes(
    rng: np.random.Generator, weights: list[float], n: int, order: schemas.ScatterAssetOrder,
) -> schemas.IntArray:
    """Prototype index per instance: weighted random, or cycling in order."""
    if order is schemas.ScatterAssetOrder.CYCLE:
        return np.arange(n, dtype=np.int64) % len(weights)
    w = np.asarray(weights, dtype=np.float64)
    return rng.choice(len(weights), size=n, p=w / w.sum()).astype(np.int64)


def random_scales(
    rng: np.random.Generator, scale_range: tuple[float, float], n: int,
) -> schemas.FloatArray:
    """Uniform per-instance scale within *scale_range*, as (n, 3)."""
    low, high = scale_range
    s = rng.uniform(low, high, n) if high > low else np.full(n, low)
    return np.repeat(s[:, None], 3, axis=1)


def random_headings(
    rng: np.random.Generator, n: int, up: int, *, random_yaw: bool,
) -> schemas.FloatArray:
    """Yaw-only rotations about up: uniformly random, or none."""
    yaw = rng.random(n) * 2.0 * math.pi if random_yaw else np.zeros(n)
    return usd.transforms.quat_axis_angle(usd.metrics.up_vector(up), yaw)


def surface_orientations(
    rng: np.random.Generator,
    headings: schemas.FloatArray,
    normals: schemas.FloatArray,
    up: int,
    *,
    align: schemas.ScatterAlign,
    tilt_jitter_degrees: float,
) -> schemas.FloatArray:
    """*headings*, optional random tilt, then (optionally) align to normals."""
    n = int(normals.shape[0])
    up_vec = usd.metrics.up_vector(up)
    q = headings
    if tilt_jitter_degrees > 0:
        axes = usd.metrics.horizontal_axes(up)
        phi = rng.random(n) * 2.0 * math.pi
        axis = np.zeros((n, 3))
        axis[:, axes[0]] = np.cos(phi)
        axis[:, axes[1]] = np.sin(phi)
        tilt = rng.random(n) * math.radians(tilt_jitter_degrees)
        q = usd.transforms.quat_mul(usd.transforms.quat_axis_angle(axis, tilt), q)
    if align is schemas.ScatterAlign.SURFACE:
        q = usd.transforms.quat_mul(usd.transforms.quat_between(up_vec, normals), q)
    return q


def rest_positions(
    contacts: schemas.FloatArray,
    orientations: schemas.FloatArray,
    scales: schemas.FloatArray,
    prototypes: list[schemas.ScatterPrototype],
    proto_idx: schemas.IntArray,
    up: int,
    *,
    embed: float,
    settle: schemas.BoolArray,
    index: schemas.SurfaceIndex | None,
) -> schemas.FloatArray:
    """Set each piece's base centre on its contact point, then settle and embed it."""
    bmin = np.stack([p.bounds_min for p in prototypes])[proto_idx]
    bmax = np.stack([p.bounds_max for p in prototypes])[proto_idx]
    base_min, base_max = prototype_bases(prototypes, proto_idx)
    base = usd.bounds.base_center(base_min, base_max, up)
    up_vec = usd.metrics.up_vector(up)
    positions = contacts - usd.transforms.quat_rotate(orientations, base * scales)
    if index is not None and settle.any():
        samples = base_samples(
            positions[settle], orientations[settle], scales[settle],
            base_min[settle], base_max[settle], up,
        )
        shift, _ = settle_shift(index, samples, up)
        positions[settle, up] += shift
    height = (bmax[:, up] - bmin[:, up]) * scales[:, up]
    if embed > 0:
        local_up = usd.transforms.quat_rotate(orientations, np.broadcast_to(up_vec, contacts.shape))
        positions -= local_up * (embed * height)[:, None]
    return positions


def prototype_bases(
    prototypes: list[schemas.ScatterPrototype], proto_idx: schemas.IntArray,
) -> tuple[schemas.FloatArray, schemas.FloatArray]:
    """Per-instance ``(base_min, base_max)`` of each instance's prototype."""
    base_min = np.stack([p.base_min for p in prototypes])[proto_idx]
    base_max = np.stack([p.base_max for p in prototypes])[proto_idx]
    return base_min, base_max


def ground_normals(
    index: schemas.SurfaceIndex,
    contacts: schemas.FloatArray,
    headings: schemas.FloatArray,
    scales: schemas.FloatArray,
    base_min: schemas.FloatArray,
    base_max: schemas.FloatArray,
    fallback: schemas.FloatArray,
    up: int,
) -> tuple[schemas.FloatArray, schemas.BoolArray]:
    """Normal of the ground fitted under each base footprint, else *fallback*."""
    axes = list(usd.metrics.horizontal_axes(up))
    center = usd.bounds.base_center(base_min, base_max, up)
    positions = contacts - usd.transforms.quat_rotate(headings, center * scales)
    samples = base_samples(positions, headings, scales, base_min, base_max, up)
    n, k, _ = samples.shape
    flat = samples.reshape(-1, 3)
    hit, heights, _ = usd.surface.surface_under(
        index, flat, mode="nearest", reference=flat[:, up].copy(),
    )
    w = hit.reshape(n, k).astype(np.float64)
    a = samples[:, :, axes[0]] - contacts[:, None, axes[0]]
    b = samples[:, :, axes[1]] - contacts[:, None, axes[1]]
    h = np.where(hit, heights, 0.0).reshape(n, k) - contacts[:, None, up]
    count = np.maximum(w.sum(axis=1), 1.0)

    def mean(v: schemas.FloatArray) -> schemas.FloatArray:
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
        & (det > 1e-6 * (caa + cbb) ** 2 + constants.SurfaceTuning.EPSILON)
        & (fallback[:, up] >= math.cos(math.radians(constants.ScatterTuning.FIT_MAX_SLOPE_DEGREES)))
    )
    safe = np.where(fitted, det, 1.0)
    normals = np.zeros((n, 3))
    normals[:, axes[0]] = -(cah * cbb - cbh * cab) / safe
    normals[:, axes[1]] = -(cbh * caa - cah * cab) / safe
    normals[:, up] = 1.0
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    return np.where(fitted[:, None], normals, fallback), fitted


def base_samples(
    positions: schemas.FloatArray,
    orientations: schemas.FloatArray,
    scales: schemas.FloatArray,
    base_min: schemas.FloatArray,
    base_max: schemas.FloatArray,
    up: int,
) -> schemas.FloatArray:
    """``(n, k, 3)`` points on each piece's base footprint, in the positions' frame."""
    axes = list(usd.metrics.horizontal_axes(up))
    t = np.linspace(0.0, 1.0, constants.ScatterTuning.BASE_GRID)
    ta, tb = (g.ravel() for g in np.meshgrid(t, t, indexing="ij"))
    n, k = positions.shape[0], ta.size
    local = np.repeat(base_min[:, None, :], k, axis=1)
    extent = base_max - base_min
    local[:, :, axes[0]] += ta[None, :] * extent[:, None, axes[0]]
    local[:, :, axes[1]] += tb[None, :] * extent[:, None, axes[1]]
    local *= scales[:, None, :]
    rotated = usd.transforms.quat_rotate(np.repeat(orientations, k, axis=0), local.reshape(-1, 3))
    return positions[:, None, :] + rotated.reshape(n, k, 3)


def settle_shift(
    index: schemas.SurfaceIndex, samples: schemas.FloatArray, up: int,
) -> tuple[schemas.FloatArray, schemas.BoolArray]:
    """Up shift that lands each piece's highest base sample on the surface."""
    n, k, _ = samples.shape
    flat = samples.reshape(-1, 3)
    hit, heights, _ = usd.surface.surface_under(
        index, flat, mode="nearest", reference=flat[:, up].copy(),
    )
    gap = np.where(hit, flat[:, up] - np.where(hit, heights, 0.0), -np.inf).reshape(n, k)
    worst = gap.max(axis=1)
    supported = np.isfinite(worst)
    return np.where(supported, -worst, 0.0), supported
