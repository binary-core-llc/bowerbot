# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Per-tool-category coverage: snapshots, materials, light update/remove, variants."""

from __future__ import annotations

from pathlib import Path

from pxr import Usd, UsdGeom, UsdLux, UsdShade

from tests.agent.runner import AgentScenario, ScenarioContext


def _stage_path(project_dir: Path) -> Path:
    return project_dir / "scene.usda"


def _setup_basic_scene(project_dir: Path) -> None:
    stage = Usd.Stage.Open(str(_stage_path(project_dir)))
    UsdGeom.Cube.Define(stage, "/Scene/Block").AddTranslateOp().Set(
        (0.0, 1.0, 0.0),
    )
    stage.Save()


def _setup_scene_with_light(project_dir: Path) -> None:
    stage = Usd.Stage.Open(str(_stage_path(project_dir)))
    UsdGeom.Cube.Define(stage, "/Scene/Block").AddTranslateOp().Set(
        (0.0, 1.0, 0.0),
    )
    stage.DefinePrim("/Scene/Lighting", "Xform")
    light = UsdLux.RectLight.Define(stage, "/Scene/Lighting/KeyLight")
    light.CreateIntensityAttr(1000.0)
    light.AddTranslateOp().Set((2.0, 3.0, 2.0))
    stage.Save()


def _setup_three_dynamic_bodies(project_dir: Path) -> None:
    stage = Usd.Stage.Open(str(_stage_path(project_dir)))
    for i, y in enumerate((1.0, 3.0, 5.0)):
        prim = stage.DefinePrim(f"/Scene/Box_{i + 1:02d}", "Xform")
        UsdGeom.Xformable(prim).AddTranslateOp().Set((0.0, y, 0.0))
        UsdGeom.Cube.Define(stage, f"/Scene/Box_{i + 1:02d}/Shape")
    plane = UsdGeom.Mesh.Define(stage, "/Scene/Ground")
    plane.CreatePointsAttr([
        (-5.0, 0.0, -5.0), (5.0, 0.0, -5.0),
        (5.0, 0.0, 5.0), (-5.0, 0.0, 5.0),
    ])
    plane.CreateFaceVertexCountsAttr([4])
    plane.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    stage.Save()


def _assert_snapshot_round_trip(ctx: ScenarioContext) -> None:
    called = {tc.tool_name for tc in ctx.all_tool_calls}
    assert "save_scene_snapshot" in called
    assert "list_scene_snapshots" in called or "delete_scene_snapshot" in called


def _assert_material_bound(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    bound = False
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Gprim):
            continue
        mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        if mat:
            bound = True
            break
    assert bound, (
        f"Expected a material binding on some Gprim. Tool calls: "
        f"{[tc.tool_name for tc in ctx.all_tool_calls]}"
    )


def _assert_light_intensity_changed(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    light = stage.GetPrimAtPath("/Scene/Lighting/KeyLight")
    assert light and light.IsValid(), "KeyLight should still exist after dimming"
    intensity = light.GetAttribute("inputs:intensity").Get()
    assert intensity is not None and intensity < 1000.0, (
        f"Expected KeyLight intensity below the seeded 1000; got {intensity}"
    )


def _assert_light_removed(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    light = stage.GetPrimAtPath("/Scene/Lighting/KeyLight")
    assert not (light and light.IsValid()), "KeyLight should be gone"


def _assert_three_rigid_bodies(ctx: ScenarioContext) -> None:
    stage = ctx.stage
    assert stage is not None
    rb = [
        str(p.GetPath()) for p in stage.Traverse()
        if "PhysicsRigidBodyAPI" in p.GetAppliedSchemas()
    ]
    assert len(rb) >= 3, f"Expected at least 3 RigidBody prims, got: {rb}"


snapshot_full_cycle = AgentScenario(
    name="category_snapshot_full_cycle",
    description="Save a named snapshot, list snapshots, delete it.",
    tier="category",
    suites=("smoke", "full"),
    setup=_setup_basic_scene,
    prompts=[
        "save a snapshot of this scene called 'baseline', then show me the "
        "list of snapshots, then delete the 'baseline' snapshot",
    ],
    assertions=[_assert_snapshot_round_trip],
)


material_create_and_bind = AgentScenario(
    name="category_material_create_and_bind",
    description="Place a real library asset, create a procedural material, bind it.",
    tier="category",
    suites=("full",),
    prompts=[
        "find a coffee_chair in my library, place it in the scene under "
        "Furniture, then create a bright red procedural material for it. "
        "If the asset needs transforms baked, go ahead and do that.",
    ],
    assertions=[_assert_material_bound],
)


bind_existing_library_material = AgentScenario(
    name="category_bind_existing_library_material",
    description="Place a real library asset and bind an existing library material.",
    tier="category",
    suites=("full",),
    prompts=[
        "place a long_table from my library under Furniture, then bind "
        "the mtl_wood_varnished material from my library to it. If the "
        "asset needs transforms baked first, go ahead.",
    ],
    assertions=[_assert_material_bound],
)


light_dim = AgentScenario(
    name="category_light_dim",
    description="Dim an existing light to about a quarter intensity.",
    tier="category",
    suites=("smoke", "full"),
    setup=_setup_scene_with_light,
    prompts=[
        "the KeyLight at /Scene/Lighting/KeyLight is too bright, dim it to "
        "about a quarter of what it is now",
    ],
    assertions=[_assert_light_intensity_changed],
)


light_remove = AgentScenario(
    name="category_light_remove",
    description="Ask to remove the KeyLight; ensure it is gone.",
    tier="category",
    suites=("full",),
    setup=_setup_scene_with_light,
    prompts=[
        "remove the KeyLight from the scene",
    ],
    assertions=[_assert_light_removed],
)


goal_make_falling_stack = AgentScenario(
    name="category_goal_make_falling_stack",
    description="Apply rigid bodies + collision so three stacked cubes fall.",
    tier="category",
    suites=("full",),
    setup=_setup_three_dynamic_bodies,
    prompts=[
        "make /Scene/Box_01, /Scene/Box_02, /Scene/Box_03 fall and collide "
        "with the /Scene/Ground when physics simulates. ground should stay "
        "still.",
    ],
    assertions=[_assert_three_rigid_bodies],
)


ALL = [
    snapshot_full_cycle,
    material_create_and_bind,
    bind_existing_library_material,
    light_dim,
    light_remove,
    goal_make_falling_stack,
]
