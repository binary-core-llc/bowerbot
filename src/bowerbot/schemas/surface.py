# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Surface schemas — world-space triangles and the plan-view grid over them."""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict

type FloatArray = NDArray[np.float64]
type IntArray = NDArray[np.signedinteger[Any]]
type BoolArray = NDArray[np.bool_]


class SurfaceTuning:
    """Internal settings of surface triangulation and queries."""

    # Tolerance for geometric comparisons.
    EPS = 1e-9
    # How far outside a triangle (barycentric) a point may sit and still hit it.
    BARY_EPS = 1e-7
    # Longitude and latitude segments when tessellating a sphere.
    SPHERE_SEGMENTS = (32, 16)
    # Most cells in a surface's plan-view grid.
    MAX_GRID_CELLS = 1 << 20
    # Points queried per batch.
    QUERY_CHUNK = 200_000


class SurfaceTriangles(BaseModel):
    """World-space triangles with unit normals (double-sided faces up) and areas."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    v0: FloatArray
    v1: FloatArray
    v2: FloatArray
    normals: FloatArray
    areas: FloatArray

    @property
    def count(self) -> int:
        return int(self.areas.shape[0])


class SurfaceIndex(BaseModel):
    """Plan-view grid over triangles for fast vertical-line queries."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    triangles: SurfaceTriangles
    up: int
    axes: tuple[int, int]
    origin: FloatArray
    cell: float
    dims: tuple[int, int]
    cell_start: IntArray
    cell_tris: IntArray
