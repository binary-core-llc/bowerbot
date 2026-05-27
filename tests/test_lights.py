# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test scene-level USD light creation via stage_utils."""

import tempfile
from pathlib import Path

from pxr import Usd, UsdLux

from bowerbot.schemas import LightParams, LightType
from bowerbot.utils import (
    inspection_utils,
    light_utils,
    stage_utils,
)


def test_create_sphere_light():
    """Create a SphereLight and verify its attributes."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_utils.create_stage(stage_path)

        light = LightParams(
            light_type=LightType.SPHERE,
            translate=(5.0, 2.5, 4.0),
            attributes={
                "inputs:intensity": 500.0,
                "inputs:color": (1.0, 0.9, 0.8),
                "inputs:radius": 0.1,
            },
        )
        light_utils.create_light(stage, "/Scene/Lighting/Key_Light_01", light)
        stage_utils.save_stage(stage)

        reopened = Usd.Stage.Open(str(stage_path))
        prim = reopened.GetPrimAtPath("/Scene/Lighting/Key_Light_01")
        assert prim.IsValid(), "Light prim not found"
        assert prim.GetTypeName() == "SphereLight"

        sphere = UsdLux.SphereLight(prim)
        assert sphere.GetIntensityAttr().Get() == 500.0
        assert abs(sphere.GetRadiusAttr().Get() - 0.1) < 1e-6


def test_create_distant_light():
    """Create a DistantLight with angle and verify."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_utils.create_stage(stage_path)

        light = LightParams(
            light_type=LightType.DISTANT,
            rotate=(-45.0, 0.0, 0.0),
            attributes={
                "inputs:intensity": 500.0,
                "inputs:angle": 0.53,
            },
        )
        light_utils.create_light(stage, "/Scene/Lighting/Sun_01", light)
        stage_utils.save_stage(stage)

        reopened = Usd.Stage.Open(str(stage_path))
        prim = reopened.GetPrimAtPath("/Scene/Lighting/Sun_01")
        assert prim.IsValid(), "DistantLight prim not found"
        assert prim.GetTypeName() == "DistantLight"

        distant = UsdLux.DistantLight(prim)
        assert abs(distant.GetAngleAttr().Get() - 0.53) < 1e-5


def test_create_rect_light():
    """Create a RectLight with width and height."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_utils.create_stage(stage_path)

        light = LightParams(
            light_type=LightType.RECT,
            translate=(5.0, 2.7, 4.0),
            attributes={
                "inputs:intensity": 1000.0,
                "inputs:width": 1.5,
                "inputs:height": 0.8,
            },
        )
        light_utils.create_light(stage, "/Scene/Lighting/Ceiling_Panel_01", light)
        stage_utils.save_stage(stage)

        reopened = Usd.Stage.Open(str(stage_path))
        prim = reopened.GetPrimAtPath("/Scene/Lighting/Ceiling_Panel_01")
        assert prim.IsValid()

        rect = UsdLux.RectLight(prim)
        assert abs(rect.GetWidthAttr().Get() - 1.5) < 1e-6
        assert abs(rect.GetHeightAttr().Get() - 0.8) < 1e-6


def test_list_prims_includes_lights():
    """inspection_utils.list_prims returns lights with type and attributes."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_utils.create_stage(stage_path)

        light = LightParams(
            light_type=LightType.SPHERE,
            translate=(3.0, 2.0, 3.0),
            attributes={
                "inputs:intensity": 800.0,
                "inputs:color": (1.0, 0.95, 0.9),
            },
        )
        light_utils.create_light(stage, "/Scene/Lighting/Spot_01", light)
        stage_utils.save_stage(stage)

        prims = inspection_utils.list_prims(stage)
        assert len(prims) == 1, f"Expected 1 prim, got {len(prims)}"

        light_entry = prims[0]
        assert light_entry["light_type"] == "SphereLight"
        assert light_entry["position"]["x"] == 3.0
        assert light_entry["intensity"] == 800.0
        assert "bounds" not in light_entry


def test_create_multiple_light_types():
    """Create several different light types in one scene."""
    with tempfile.TemporaryDirectory() as tmp:
        stage_path = Path(tmp) / "test_scene.usda"

        stage = stage_utils.create_stage(stage_path)

        lights = [
            (
                "/Scene/Lighting/Sun",
                LightParams(
                    light_type=LightType.DISTANT,
                    attributes={"inputs:intensity": 500.0},
                ),
            ),
            (
                "/Scene/Lighting/Fill",
                LightParams(
                    light_type=LightType.RECT,
                    translate=(5.0, 2.7, 4.0),
                    attributes={
                        "inputs:intensity": 1000.0,
                        "inputs:width": 2.0,
                        "inputs:height": 1.0,
                    },
                ),
            ),
            (
                "/Scene/Lighting/Accent",
                LightParams(
                    light_type=LightType.DISK,
                    translate=(2.0, 2.5, 2.0),
                    attributes={
                        "inputs:intensity": 600.0,
                        "inputs:radius": 0.2,
                    },
                ),
            ),
        ]

        for prim_path, light in lights:
            light_utils.create_light(stage, prim_path, light)
        stage_utils.save_stage(stage)

        prims = inspection_utils.list_prims(stage)
        assert len(prims) == 3, f"Expected 3 lights, got {len(prims)}"

        types = {p["light_type"] for p in prims}
        assert types == {"DistantLight", "RectLight", "DiskLight"}
