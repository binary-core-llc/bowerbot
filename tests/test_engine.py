# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the USD services pipeline: create → populate → validate → package."""

import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom

from bowerbot.services import stage_service, validation_service
from bowerbot.services.geometry_service import (
    boxes_overlap,
    suggest_grid_layout,
)


def test_create_empty_stage():
    """stage_service creates a bare stage with BowerBot defaults."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_service.create_stage(stage_path)
        stage_service.save(stage)

        assert stage_path.exists(), "Stage file was not created"

        reopened = Usd.Stage.Open(str(stage_path))
        assert reopened is not None, "Failed to open stage"

        assert UsdGeom.GetStageMetersPerUnit(reopened) == 1.0
        assert UsdGeom.GetStageUpAxis(reopened) == UsdGeom.Tokens.y

        default_prim = reopened.GetDefaultPrim()
        assert default_prim.IsValid(), "No defaultPrim set"
        assert str(default_prim.GetPath()) == "/Scene"

        # Hierarchy is built on demand — no pre-created groups.
        assert len(default_prim.GetChildren()) == 0

        print("test_create_empty_stage PASSED")


def test_validate_empty_stage():
    """Validator approves a correctly built empty stage."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_service.create_stage(stage_path)
        stage_service.save(stage)

        result = validation_service.validate(stage_path)

        assert result.is_valid, f"Validation failed: {[i.message for i in result.issues]}"
        assert result.error_count == 0

        print("test_validate_empty_stage PASSED")


def test_grid_layout():
    """geometry_service.suggest_grid_layout computes correct positions."""
    placements = suggest_grid_layout(
        4, spacing=2.0, room_bounds=(10.0, 3.0, 8.0),
    )

    assert len(placements) == 4

    for p in placements:
        assert p.translate[1] == 0.0

    for i, a in enumerate(placements):
        for j, b in enumerate(placements):
            if i >= j:
                continue
            dx = a.translate[0] - b.translate[0]
            dz = a.translate[2] - b.translate[2]
            dist = (dx**2 + dz**2) ** 0.5
            assert dist >= 1.9, f"Objects {i} and {j} too close: {dist:.2f}m"

    print("test_grid_layout PASSED")


def test_collision_detection():
    """geometry_service.boxes_overlap catches overlapping AABBs."""
    assert boxes_overlap(
        pos_a=(0, 0, 0), size_a=(1, 1, 1),
        pos_b=(0, 0, 0), size_b=(1, 1, 1),
    )
    assert not boxes_overlap(
        pos_a=(0, 0, 0), size_a=(1, 1, 1),
        pos_b=(5, 0, 0), size_b=(1, 1, 1),
    )
    assert not boxes_overlap(
        pos_a=(0, 0, 0), size_a=(1, 1, 1),
        pos_b=(1, 0, 0), size_b=(1, 1, 1),
    )
    print("test_collision_detection PASSED")


if __name__ == "__main__":
    test_create_empty_stage()
    test_validate_empty_stage()
    test_grid_layout()
    test_collision_detection()
    print("\nAll engine tests passed!")
