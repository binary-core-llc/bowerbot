# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Light values."""

from pxr import UsdLux

from bowerbot import schemas


class LightUsd:
    """The UsdLux schema class for each light type."""

    CLASSES: dict[str, type] = {
        schemas.LightType.DISTANT: UsdLux.DistantLight,
        schemas.LightType.DOME: UsdLux.DomeLight,
        schemas.LightType.SPHERE: UsdLux.SphereLight,
        schemas.LightType.RECT: UsdLux.RectLight,
        schemas.LightType.DISK: UsdLux.DiskLight,
        schemas.LightType.CYLINDER: UsdLux.CylinderLight,
    }


class LightRules:
    """Which lights may live where, and which inputs are lengths."""

    # Light types that only exist at scene level, never inside an asset.
    SCENE_ONLY_TYPES: frozenset[schemas.LightType] = frozenset({
        schemas.LightType.DOME,
        schemas.LightType.DISTANT,
    })
    # UsdLux inputs measured in stage units (scaled by asset MPU at write time).
    SPATIAL_INPUTS: frozenset[str] = frozenset({
        "inputs:radius",
        "inputs:width",
        "inputs:height",
        "inputs:length",
    })


class LightDefaults:
    """Fallbacks when a light call leaves a value out."""

    # Default vertical offset (meters) above an asset's top surface when
    # placing a prim with no explicit Y position in BOUNDS_OFFSET mode.
    Y_OFFSET = 0.5
