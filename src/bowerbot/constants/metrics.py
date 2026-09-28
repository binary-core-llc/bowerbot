# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Stage metrics values: up axes and units."""

from pxr import Gf


class MetricsUsd:
    """Gf vectors for each up axis."""

    # World up vector for a stage's up axis.
    UP_VECTORS = {"Y": Gf.Vec3d(0, 1, 0), "Z": Gf.Vec3d(0, 0, 1)}
