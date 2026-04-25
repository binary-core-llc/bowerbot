# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the core stage primitives + validation + grid layout."""

import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom

from bowerbot.utils import stage_utils, validation_utils
from bowerbot.utils.geometry_utils import suggest_grid_layout


def test_create_empty_stage():
    """stage_utils.create_stage produces a stage with BowerBot defaults."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_utils.create_stage(stage_path)
        stage_utils.save_stage(stage)

        assert stage_path.exists()

        reopened = Usd.Stage.Open(str(stage_path))
        assert reopened is not None
        assert UsdGeom.GetStageMetersPerUnit(reopened) == 1.0
        assert UsdGeom.GetStageUpAxis(reopened) == UsdGeom.Tokens.y

        default_prim = reopened.GetDefaultPrim()
        assert default_prim.IsValid()
        assert str(default_prim.GetPath()) == "/Scene"
        assert len(default_prim.GetChildren()) == 0


def test_validate_empty_stage():
    """validation_utils.validate_stage approves a correctly built empty stage."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"
        stage = stage_utils.create_stage(stage_path)
        stage_utils.save_stage(stage)

        result = validation_utils.validate_stage(stage_path)
        assert result.is_valid, [i.message for i in result.issues]
        assert result.error_count == 0


def test_grid_layout():
    """geometry_utils.suggest_grid_layout returns N (x, y, z) tuples."""
    placements = suggest_grid_layout(
        4, spacing=2.0, room_bounds=(10.0, 3.0, 8.0),
    )

    assert len(placements) == 4
    for p in placements:
        assert p[1] == 0.0

    for i, a in enumerate(placements):
        for j, b in enumerate(placements):
            if i >= j:
                continue
            dx = a[0] - b[0]
            dz = a[2] - b[2]
            dist = (dx**2 + dz**2) ** 0.5
            assert dist >= 1.9, f"Objects {i} and {j} too close: {dist:.2f}m"
