# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Surface values: tolerances and sizes of the triangle queries."""


class SurfaceTuning:
    """Internal knobs of the surface triangle queries."""

    # Smallest length treated as non-zero.
    EPSILON = 1e-9
    # How far outside a triangle (in barycentric terms) still counts as inside.
    BARY_EPSILON = 1e-7
    # Longitude and latitude segments a sphere is triangulated into.
    SPHERE_SEGMENTS = (32, 16)
    # Most cells the vertical-query grid may have.
    MAX_GRID_CELLS = 1 << 20
    # Query points handled per batch.
    QUERY_CHUNK = 200_000
