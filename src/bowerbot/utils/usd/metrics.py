# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""metersPerUnit and upAxis: read them, conform an asset to the scene, world axes."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from pxr import Usd
from pxr import UsdGeom

from bowerbot import schemas

# ── Reading a file's metrics ──


def file_metrics(
    file_path: Path | str, *, default_mpu: float, default_up_axis: str,
) -> tuple[float, str]:
    """``(metersPerUnit, upAxis)`` *file_path* declares; the defaults fill in what it leaves out."""
    stage = Usd.Stage.Open(str(file_path), Usd.Stage.LoadNone)
    if stage is None:
        return default_mpu, default_up_axis
    mpu = (
        UsdGeom.GetStageMetersPerUnit(stage)
        if UsdGeom.StageHasAuthoredMetersPerUnit(stage) else default_mpu
    )
    up_axis = default_up_axis
    if stage.HasAuthoredMetadata(UsdGeom.Tokens.upAxis):
        up_axis = "Y" if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y else "Z"
    return mpu, up_axis

# ── Conforming an asset to the scene ──


def asset_conform(stage: Usd.Stage, asset_path: str) -> tuple[float, float | None]:
    """Return (unit scale, up-axis X-rotation or None) conforming an asset to the stage.

    What the asset leaves undeclared is taken to be the scene's, so it needs no conversion.
    """
    if not os.path.isabs(asset_path):
        stage_dir = os.path.dirname(stage.GetRootLayer().realPath)
        asset_path = os.path.join(stage_dir, asset_path)

    scene_mpu = UsdGeom.GetStageMetersPerUnit(stage)
    scene_up = "Y" if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y else "Z"
    asset_mpu, asset_up = file_metrics(
        asset_path, default_mpu=scene_mpu, default_up_axis=scene_up,
    )
    unit_scale = 1.0 if scene_mpu == 0 else asset_mpu / scene_mpu

    correction = None
    if asset_up == "Y" and scene_up == "Z":
        correction = 90.0
    elif asset_up == "Z" and scene_up == "Y":
        correction = -90.0
    return unit_scale, correction

# ── World axes ──


def axis_index(up_axis: str) -> int:
    """World axis index of an up-axis name: ``"Y"`` -> 1, ``"Z"`` -> 2."""
    return 2 if up_axis == "Z" else 1


def horizontal_axes(up: int) -> tuple[int, int]:
    """The two world axes spanning the ground plane for up axis *up*."""
    return (0, 2) if up == 1 else (0, 1)


def up_vector(up: int) -> schemas.FloatArray:
    """Unit vector along the world up axis."""
    vec = np.zeros(3)
    vec[up] = 1.0
    return vec
