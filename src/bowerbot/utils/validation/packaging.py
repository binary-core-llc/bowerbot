# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USDZ packaging — bundling a stage and its dependencies into one file."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pxr import UsdUtils

from bowerbot.schemas import AssetFormat

logger = logging.getLogger(__name__)


def package_to_usdz(stage_path: str | Path, output_path: str | Path) -> Path:
    """Bundle a stage and its dependencies into a ``.usdz``."""
    stage_path = Path(stage_path)
    output_path = Path(output_path).with_suffix(AssetFormat.USDZ)

    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)

    try:
        success = UsdUtils.CreateNewUsdzPackage(
            str(stage_path.resolve()),
            str(output_path.resolve()),
        )
    finally:
        os.dup2(old_stderr, 2)
        os.close(devnull)
        os.close(old_stderr)

    if not success:
        msg = f"Failed to package {stage_path} into {output_path}"
        raise RuntimeError(msg)

    logger.info("Packaged %s -> %s", stage_path, output_path)
    return output_path
