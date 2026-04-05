# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the USD Engine pipeline: create → populate → validate → package."""

import tempfile
from pathlib import Path

from bowerbot.engine.scene_graph import SceneGraphBuilder
from bowerbot.engine.stage_writer import StageWriter
from bowerbot.engine.validator import SceneValidator


def test_create_empty_stage():
    """Test 1: Create a bare stage with BowerBot defaults and validate it."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        # Create stage
        writer = StageWriter(meters_per_unit=1.0, up_axis="Y")
        writer.create_stage(stage_path)
        writer.save()

        # Verify file exists
        assert stage_path.exists(), "Stage file was not created"

        # Read it back and check contents
        from pxr import Usd, UsdGeom

        stage = Usd.Stage.Open(str(stage_path))
        assert stage is not None, "Failed to open stage"

        # Check defaults
        assert UsdGeom.GetStageMetersPerUnit(stage) == 1.0
        assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y

        # Check defaultPrim
        default_prim = stage.GetDefaultPrim()
        assert default_prim.IsValid(), "No defaultPrim set"
        assert str(default_prim.GetPath()) == "/Scene"

        # Hierarchy is built on demand — no pre-created groups
        # Verify the stage is clean (only root prim)
        children = default_prim.GetChildren()
        assert len(children) == 0, "Empty stage should have no child prims"

        print("✅ test_create_empty_stage PASSED")


def test_validate_empty_stage():
    """Test 2: Validator should approve a correctly built empty stage."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        writer = StageWriter()
        writer.create_stage(stage_path)
        writer.save()

        validator = SceneValidator()
        result = validator.validate(str(stage_path))

        assert result.is_valid, f"Validation failed: {[i.message for i in result.issues]}"
        assert result.error_count == 0

        print("✅ test_validate_empty_stage PASSED")


def test_scene_graph_grid_layout():
    """Test 3: SceneGraphBuilder computes correct grid positions."""
    builder = SceneGraphBuilder(room_bounds=(10.0, 3.0, 8.0))

    # 4 objects in a grid with 2m spacing
    placements = builder.suggest_grid_layout(count=4, spacing=2.0)

    assert len(placements) == 4, f"Expected 4 placements, got {len(placements)}"

    # All Y values should be 0 (floor)
    for p in placements:
        assert p.translate[1] == 0.0, f"Y should be 0, got {p.translate[1]}"

    # Check that objects are spaced apart
    for i, a in enumerate(placements):
        for j, b in enumerate(placements):
            if i >= j:
                continue
            dx = a.translate[0] - b.translate[0]
            dz = a.translate[2] - b.translate[2]
            dist = (dx**2 + dz**2) ** 0.5
            assert dist >= 1.9, f"Objects {i} and {j} too close: {dist:.2f}m"

    print("✅ test_scene_graph_grid_layout PASSED")
    print(f"   Positions: {[(round(p.translate[0],2), round(p.translate[2],2)) for p in placements]}")


def test_collision_detection():
    """Test 4: Collision checker catches overlapping objects."""
    builder = SceneGraphBuilder()

    # Two boxes at same position — should collide
    assert builder.check_collision(
        pos_a=(0, 0, 0), size_a=(1, 1, 1),
        pos_b=(0, 0, 0), size_b=(1, 1, 1),
    ) is True

    # Two boxes far apart — should not collide
    assert builder.check_collision(
        pos_a=(0, 0, 0), size_a=(1, 1, 1),
        pos_b=(5, 0, 0), size_b=(1, 1, 1),
    ) is False

    # Two boxes just touching — should not collide (edge case)
    assert builder.check_collision(
        pos_a=(0, 0, 0), size_a=(1, 1, 1),
        pos_b=(1, 0, 0), size_b=(1, 1, 1),
    ) is False

    print("✅ test_collision_detection PASSED")


if __name__ == "__main__":
    test_create_empty_stage()
    test_validate_empty_stage()
    test_scene_graph_grid_layout()
    test_collision_detection()
    print("\n🎉 All engine tests passed!")
