# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test scene-level USD light creation via stage_service."""

import tempfile
from pathlib import Path

from pxr import Usd, UsdLux

from bowerbot.schemas import LightParams, LightType
from bowerbot.services import stage_service


def test_create_sphere_light():
    """Create a SphereLight and verify its attributes."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_service.create_stage(stage_path)

        light = LightParams(
            light_type=LightType.SPHERE,
            intensity=500.0,
            color=(1.0, 0.9, 0.8),
            translate=(5.0, 2.5, 4.0),
            radius=0.1,
        )
        stage_service.create_light(stage, "/Scene/Lighting/Key_Light_01", light)
        stage_service.save(stage)

        reopened = Usd.Stage.Open(str(stage_path))
        prim = reopened.GetPrimAtPath("/Scene/Lighting/Key_Light_01")
        assert prim.IsValid(), "Light prim not found"
        assert prim.GetTypeName() == "SphereLight"

        sphere = UsdLux.SphereLight(prim)
        assert sphere.GetIntensityAttr().Get() == 500.0
        assert abs(sphere.GetRadiusAttr().Get() - 0.1) < 1e-6

        print("test_create_sphere_light PASSED")


def test_create_distant_light():
    """Create a DistantLight with angle and verify."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_service.create_stage(stage_path)

        light = LightParams(
            light_type=LightType.DISTANT,
            intensity=500.0,
            rotate=(-45.0, 0.0, 0.0),
            angle=0.53,
        )
        stage_service.create_light(stage, "/Scene/Lighting/Sun_01", light)
        stage_service.save(stage)

        reopened = Usd.Stage.Open(str(stage_path))
        prim = reopened.GetPrimAtPath("/Scene/Lighting/Sun_01")
        assert prim.IsValid(), "DistantLight prim not found"
        assert prim.GetTypeName() == "DistantLight"

        distant = UsdLux.DistantLight(prim)
        assert abs(distant.GetAngleAttr().Get() - 0.53) < 1e-5

        print("test_create_distant_light PASSED")


def test_create_rect_light():
    """Create a RectLight with width and height."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_service.create_stage(stage_path)

        light = LightParams(
            light_type=LightType.RECT,
            intensity=1000.0,
            translate=(5.0, 2.7, 4.0),
            width=1.5,
            height=0.8,
        )
        stage_service.create_light(stage, "/Scene/Lighting/Ceiling_Panel_01", light)
        stage_service.save(stage)

        reopened = Usd.Stage.Open(str(stage_path))
        prim = reopened.GetPrimAtPath("/Scene/Lighting/Ceiling_Panel_01")
        assert prim.IsValid()

        rect = UsdLux.RectLight(prim)
        assert abs(rect.GetWidthAttr().Get() - 1.5) < 1e-6
        assert abs(rect.GetHeightAttr().Get() - 0.8) < 1e-6

        print("test_create_rect_light PASSED")


def test_list_prims_includes_lights():
    """stage_service.list_prims returns lights with type and attributes."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_service.create_stage(stage_path)

        light = LightParams(
            light_type=LightType.SPHERE,
            intensity=800.0,
            color=(1.0, 0.95, 0.9),
            translate=(3.0, 2.0, 3.0),
        )
        stage_service.create_light(stage, "/Scene/Lighting/Spot_01", light)
        stage_service.save(stage)

        prims = stage_service.list_prims(stage)
        assert len(prims) == 1, f"Expected 1 prim, got {len(prims)}"

        light_entry = prims[0]
        assert light_entry["light_type"] == "SphereLight"
        assert light_entry["position"]["x"] == 3.0
        assert light_entry["intensity"] == 800.0
        assert "bounds" not in light_entry  # lights have no geometry bounds

        print("test_list_prims_includes_lights PASSED")


def test_create_multiple_light_types():
    """Create several different light types in one scene."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_service.create_stage(stage_path)

        lights = [
            (
                "/Scene/Lighting/Sun",
                LightParams(light_type=LightType.DISTANT, intensity=500.0),
            ),
            (
                "/Scene/Lighting/Fill",
                LightParams(
                    light_type=LightType.RECT,
                    intensity=1000.0,
                    width=2.0, height=1.0,
                    translate=(5.0, 2.7, 4.0),
                ),
            ),
            (
                "/Scene/Lighting/Accent",
                LightParams(
                    light_type=LightType.DISK,
                    intensity=600.0,
                    radius=0.2,
                    translate=(2.0, 2.5, 2.0),
                ),
            ),
        ]

        for prim_path, light in lights:
            stage_service.create_light(stage, prim_path, light)
        stage_service.save(stage)

        prims = stage_service.list_prims(stage)
        assert len(prims) == 3, f"Expected 3 lights, got {len(prims)}"

        types = {p["light_type"] for p in prims}
        assert types == {"DistantLight", "RectLight", "DiskLight"}

        print("test_create_multiple_light_types PASSED")


if __name__ == "__main__":
    test_create_sphere_light()
    test_create_distant_light()
    test_create_rect_light()
    test_list_prims_includes_lights()
    test_create_multiple_light_types()
    print("\nAll light tests passed!")
