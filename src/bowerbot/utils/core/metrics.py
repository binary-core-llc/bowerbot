# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Metrics — a stage's up axis and meters per unit, and conforming an asset to a scene."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom

from bowerbot.schemas.surface import FloatArray


def axis_index(up_axis: str) -> int:
    """World axis index of an up-axis name: ``"Y"`` -> 1, ``"Z"`` -> 2."""
    return 2 if up_axis == "Z" else 1


def horizontal_axes(up: int) -> tuple[int, int]:
    """The two world axes spanning the ground plane for up axis *up*."""
    return (0, 2) if up == 1 else (0, 1)


def up_vector(up: int) -> FloatArray:
    """Unit vector along the world up axis."""
    vec = np.zeros(3)
    vec[up] = 1.0
    return vec


def read_stage_metadata(file_path: Path) -> tuple[float, str]:
    """Return ``(metersPerUnit, upAxis)`` for *file_path*."""
    stage = Usd.Stage.Open(str(file_path))
    if stage is None:
        return 1.0, "Y"

    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    up = UsdGeom.GetStageUpAxis(stage)
    up_str = "Y" if up == UsdGeom.Tokens.y else "Z"
    return mpu, up_str


def read_mpu(file_path: Path) -> float:
    """Return ``metersPerUnit`` from any USD file. Defaults to 1.0."""
    mpu, _ = read_stage_metadata(file_path)
    return mpu if mpu > 0 else 1.0


def asset_conform(stage: Usd.Stage, asset_path: str) -> tuple[float, float | None]:
    """Return (unit scale, up-axis X-rotation or None) conforming an asset to the stage."""
    if not os.path.isabs(asset_path):
        stage_dir = os.path.dirname(stage.GetRootLayer().realPath)
        asset_path = os.path.join(stage_dir, asset_path)

    asset_stage = Usd.Stage.Open(asset_path, Usd.Stage.LoadNone)
    if asset_stage is None:
        return 1.0, None

    asset_mpu = UsdGeom.GetStageMetersPerUnit(asset_stage)
    scene_mpu = UsdGeom.GetStageMetersPerUnit(stage)
    unit_scale = 1.0 if scene_mpu == 0 else asset_mpu / scene_mpu

    asset_up = UsdGeom.GetStageUpAxis(asset_stage)
    scene_up = UsdGeom.GetStageUpAxis(stage)
    correction = None
    if asset_up == UsdGeom.Tokens.y and scene_up == UsdGeom.Tokens.z:
        correction = 90.0
    elif asset_up == UsdGeom.Tokens.z and scene_up == UsdGeom.Tokens.y:
        correction = -90.0
    return unit_scale, correction
