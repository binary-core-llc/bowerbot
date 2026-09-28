# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Camera values."""


class CameraDefaults:
    """Fallbacks when a camera call leaves a value out."""

    # Near and far clipping planes, in meters (converted to stage units).
    CLIPPING_RANGE_METERS = (0.01, 100_000.0)


class CameraTuning:
    """Internal knobs of camera aiming."""

    # A look direction this aligned with the up axis switches to the other up vector.
    UP_ALIGNED_DOT = 0.999
