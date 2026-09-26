# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter on a surface — the random, rows and pile pipelines."""

from __future__ import annotations

import numpy as np

from bowerbot.schemas import (
    ScatterAlign,
    ScatterArrangement,
    ScatterAssetOrder,
    ScatterInstanceSet,
    ScatterPoseParams,
    ScatterPrototype,
    ScatterSurfaceParams,
    ScatterTuning,
    SurfaceIndex,
    SurfaceTriangles,
)
from bowerbot.utils import surface_utils
from bowerbot.utils.scatter.noise import variation_scale
from bowerbot.utils.scatter.orientation import random_headings, surface_orientations
from bowerbot.utils.scatter.pile import pile_instances, pile_setup
from bowerbot.utils.scatter.prototypes import pick_prototypes, prototype_bases, random_scales
from bowerbot.utils.scatter.resting import ground_normals, rest_positions
from bowerbot.utils.scatter.rows import rows_contacts
from bowerbot.utils.scatter.sampling import (
    eligible_share,
    estimate_surface_count,
    require_eligible,
    scatter_surface_points,
    surface_on_accept,
)


def generate_surface_scatter(
    surface: ScatterSurfaceParams,
    pose: ScatterPoseParams,
    *,
    triangles: SurfaceTriangles,
    avoid: SurfaceIndex | None,
    prototypes: list[ScatterPrototype],
    up: int,
    mpu: float,
    seed: int,
) -> tuple[ScatterInstanceSet, list[str]]:
    """Compute every instance of a scatter_on_surface call in world space."""
    rng = np.random.default_rng(seed)
    tri_mask = require_eligible(triangles, up, surface)
    weights = [proto.weight for proto in prototypes]
    warnings: list[str] = []

    if surface.arrangement is ScatterArrangement.PILE:
        index = surface_utils.build_vertical_index(triangles, up, up_facing_only=True)
        count, center, radius = pile_setup(surface)
        proto_idx = pick_prototypes(rng, weights, count, ScatterAssetOrder.RANDOM)
        scales = random_scales(rng, pose.scale_range, count)
        positions, orientations, placed, base_radius = pile_instances(
            rng, index, prototypes, proto_idx, scales,
            up=up, center=center,
            radius=radius, repose_degrees=surface.repose_degrees,
            tilt_degrees=pose.tilt_jitter_degrees or ScatterTuning.PILE_TILT_DEGREES,
        )
        if not placed.all():
            warnings.append(
                f"{int((~placed).sum())} piece(s) found no surface under the pile "
                "region and were skipped.",
            )
        if base_radius > radius * 1.01:
            warnings.append(
                f"{count} pieces don't fit a {surface.repose_degrees:g}-degree "
                f"heap of radius {radius:g}, so it spread to a radius of "
                f"{base_radius:.2f}. Raise the radius or repose_degrees, or lower count.",
            )
        return ScatterInstanceSet(
            proto_indices=proto_idx[placed], positions=positions[placed],
            orientations=orientations[placed], scales=scales[placed],
        ), warnings

    accept = surface_on_accept(
        surface, avoid=avoid, up=up,
        noise_scale=variation_scale(surface, triangles, up), seed=seed,
    )
    if surface.arrangement is ScatterArrangement.ROWS:
        contacts, tris = rows_contacts(rng, surface, triangles, tri_mask, up)
        keep = rng.random(contacts.shape[0]) < accept(contacts, tris)
        contacts, tris = contacts[keep], tris[keep]
    else:
        contacts, tris, warnings = scatter_surface_points(
            rng, triangles, tri_mask, up=up, mpu=mpu, count=surface.count,
            density=surface.density, accept=accept, min_spacing=surface.min_spacing,
        )

    n = contacts.shape[0]
    normals = triangles.normals[tris]
    proto_idx = pick_prototypes(rng, weights, n, ScatterAssetOrder.RANDOM)
    scales = random_scales(rng, pose.scale_range, n)
    headings = random_headings(rng, n, up, random_yaw=pose.random_yaw)
    index = surface_utils.build_vertical_index(triangles, up, up_facing_only=True)
    settle = np.ones(n, dtype=bool)
    if pose.align is ScatterAlign.SURFACE:
        base_min, base_max = prototype_bases(prototypes, proto_idx)
        normals, settle = ground_normals(
            index, contacts, headings, scales, base_min, base_max, normals, up,
        )
    orientations = surface_orientations(
        rng, headings, normals, up, align=pose.align,
        tilt_jitter_degrees=pose.tilt_jitter_degrees,
    )
    positions = rest_positions(
        contacts, orientations, scales, prototypes, proto_idx, up,
        embed=pose.embed, settle=settle, index=index,
    )
    return ScatterInstanceSet(
        proto_indices=proto_idx, positions=positions,
        orientations=orientations, scales=scales,
    ), warnings


def estimate_surface_scatter(
    surface: ScatterSurfaceParams,
    *,
    triangles: SurfaceTriangles,
    avoid: SurfaceIndex | None,
    up: int,
    mpu: float,
    seed: int,
) -> tuple[int, float]:
    """Estimate ``(instances, eligible_area_m2)`` for validate_only."""
    rng = np.random.default_rng(seed)
    tri_mask = require_eligible(triangles, up, surface)
    area_m2 = float((triangles.areas * tri_mask).sum()) * mpu * mpu * eligible_share(
        np.random.default_rng([seed, 1]), surface, triangles, tri_mask, avoid, up,
    )
    if surface.arrangement is ScatterArrangement.PILE:
        count, _, _ = pile_setup(surface)
        return count, area_m2
    accept = surface_on_accept(
        surface, avoid=avoid, up=up,
        noise_scale=variation_scale(surface, triangles, up), seed=seed,
    )
    if surface.arrangement is ScatterArrangement.ROWS:
        contacts, tris = rows_contacts(rng, surface, triangles, tri_mask, up)
        return int(round(float(accept(contacts, tris).sum()))), area_m2
    estimate, _ = estimate_surface_count(
        rng, triangles, tri_mask, mpu=mpu, count=surface.count,
        density=surface.density, accept=accept,
    )
    return estimate, area_m2
