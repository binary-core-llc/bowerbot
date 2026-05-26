# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Exploratory scenarios — drive BowerBot like a real user, inspect artifacts."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdPhysics

from tests.agent.runner import AgentScenario, ScenarioContext


def _stage_path(project_dir: Path) -> Path:
    return project_dir / "scene.usda"


def _setup_one_cube(project_dir: Path) -> None:
    stage = Usd.Stage.Open(str(_stage_path(project_dir)))
    UsdGeom.Cube.Define(stage, "/Scene/Block").AddTranslateOp().Set(
        (0.0, 1.0, 0.0),
    )
    stage.Save()


def _setup_two_boxes_in_group(project_dir: Path) -> None:
    stage = Usd.Stage.Open(str(_stage_path(project_dir)))
    for name, x in (("Box_A", -1.5), ("Box_B", 1.5)):
        prim = stage.DefinePrim(f"/Scene/{name}", "Xform")
        UsdGeom.Xformable(prim).AddTranslateOp().Set((x, 1.0, 0.0))
        UsdPhysics.RigidBodyAPI.Apply(prim)
        UsdGeom.Cube.Define(stage, f"/Scene/{name}/Shape")
    stage.DefinePrim("/Scene/Physics", "Xform")
    UsdPhysics.Scene.Define(stage, "/Scene/Physics/PhysicsScene")
    group = UsdPhysics.CollisionGroup.Define(stage, "/Scene/Physics/Movables")
    group.GetCollidersCollectionAPI().CreateIncludesRel().SetTargets(
        [Sdf.Path("/Scene/Box_A"), Sdf.Path("/Scene/Box_B")],
    )
    stage.Save()


def _setup_three_boxes(project_dir: Path) -> None:
    stage = Usd.Stage.Open(str(_stage_path(project_dir)))
    for i, x in enumerate((-2.0, 0.0, 2.0)):
        prim = stage.DefinePrim(f"/Scene/Box_{i + 1:02d}", "Xform")
        UsdGeom.Xformable(prim).AddTranslateOp().Set((x, 1.0, 0.0))
        UsdGeom.Cube.Define(stage, f"/Scene/Box_{i + 1:02d}/Shape")
    stage.Save()


def _setup_with_light_target(project_dir: Path) -> None:
    stage = Usd.Stage.Open(str(_stage_path(project_dir)))
    UsdGeom.Cube.Define(stage, "/Scene/Subject").AddTranslateOp().Set(
        (0.0, 1.0, 0.0),
    )
    stage.Save()


def _no_assertions(ctx: ScenarioContext) -> None:
    """Read-only walkthrough — assertions deferred to artifact inspection."""
    del ctx


vague_random_rotation = AgentScenario(
    name="explore_vague_random_rotation",
    description="User wants 'random' 3D tilt on a box — exercises full xformOp path.",
    tier="explore",
    suites=("smoke", "full"),
    setup=_setup_one_cube,
    prompts=[
        "tilt /Scene/Block on a random angle on all three axes please, "
        "pick the angles yourself",
    ],
    assertions=[_no_assertions],
)


scale_object = AgentScenario(
    name="explore_scale_object",
    description="Conversational 'make twice as big' — requires xformOp:scale.",
    tier="explore",
    suites=("smoke", "full"),
    setup=_setup_one_cube,
    prompts=[
        "make /Scene/Block twice as big on every axis",
    ],
    assertions=[_no_assertions],
)


delete_in_group = AgentScenario(
    name="explore_delete_in_group",
    description="Delete an asset that lives in a collision group; verify integrity.",
    tier="explore",
    suites=("smoke", "full"),
    setup=_setup_two_boxes_in_group,
    prompts=[
        "delete /Scene/Box_A and then show me what's still in the Movables "
        "collision group",
    ],
    assertions=[_no_assertions],
)


warm_sunset_light = AgentScenario(
    name="explore_warm_sunset_light",
    description="Conversational light setup — tests UsdLux attribute setting.",
    tier="explore",
    suites=("smoke", "full"),
    setup=_setup_with_light_target,
    prompts=[
        "add a distant light called Sun and make it look like warm "
        "late-afternoon sunlight hitting /Scene/Subject",
    ],
    assertions=[_no_assertions],
)


iterate_all_boxes = AgentScenario(
    name="explore_iterate_all_boxes",
    description="Apply same change to N prims — tests introspection + iteration.",
    tier="explore",
    suites=("smoke", "full"),
    setup=_setup_three_boxes,
    prompts=[
        "rotate every box in the scene by 45 degrees on Y",
    ],
    assertions=[_no_assertions],
)


ALL = [
    vague_random_rotation,
    scale_object,
    delete_in_group,
    warm_sunset_light,
    iterate_all_boxes,
]
