# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Packager — bundles USD stages into .usdz archives for distribution."""

import logging
import os
from pathlib import Path

from pxr import UsdUtils

logger = logging.getLogger(__name__)


class Packager:
    """Packages a USD stage and its dependencies into .usdz."""

    def package(self, stage_path: str | Path, output_path: str | Path) -> Path:
        """Create a .usdz package from a stage.

        Uses UsdUtils.CreateNewUsdzPackage to bundle the root layer
        and all of its dependencies into a single .usdz file.
        """
        stage_path = Path(stage_path)
        output_path = Path(output_path).with_suffix(".usdz")

        # Suppress known USD relocation warnings during packaging.
        # These fire when the packager remaps asset paths (e.g. "0/item.usda")
        # and are harmless — the output .usdz is valid.
        # USD writes warnings to stderr via C++, so we redirect at the OS level.
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