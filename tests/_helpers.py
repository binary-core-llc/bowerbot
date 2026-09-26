# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for tests.

Keeps test files terse by wrapping the ``SceneState`` + dispatcher
wiring behind a couple of factory functions.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

from bowerbot import dispatcher
from bowerbot.project import Project
from bowerbot.skills.base import ToolResult
from bowerbot.state import SceneState


def make_state(
    tmp_path: Path,
    project_name: str = "test",
) -> tuple[SceneState, Project]:
    """Create a fresh project and a ``SceneState`` bound to it.

    *tmp_path* doubles as the asset library, so assets the tests write there
    can be placed.
    """
    project = Project.create(tmp_path, project_name)
    state = SceneState(library_dir=tmp_path)
    state.project = project
    state.stage_path = project.scene_path
    return state, project


async def exec_tool(
    state: SceneState, tool_name: str, params: dict | None = None,
) -> ToolResult:
    """Dispatch a tool call against *state*."""
    return await dispatcher.execute(state, tool_name, params or {})


def _stage(path: Path, up: str = "Y", mpu: float = 1.0) -> Usd.Stage:
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, mpu)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z if up == "Z" else UsdGeom.Tokens.y)
    return stage


def _box(path: Path, size: tuple[float, float, float], *, up: str = "Y", mpu: float = 1.0,
         parts: tuple[str, ...] = ("Mesh",), name: str | None = None) -> None:
    stage = _stage(path, up, mpu)
    name = name or path.stem
    stage.SetDefaultPrim(stage.DefinePrim(f"/{name}", "Xform"))
    for part in parts:
        cube = UsdGeom.Cube.Define(stage, f"/{name}/{part}")
        cube.GetSizeAttr().Set(1.0)
        cube.AddScaleOp().Set(Gf.Vec3f(*size))
    stage.Save()


def _png(path: Path, seed: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + seed * 16)


def _textured_material(stage: Usd.Stage, path: str, texture: str) -> UsdShade.Material:
    material = UsdShade.Material.Define(stage, path)
    tex = UsdShade.Shader.Define(stage, f"{path}/tex")
    tex.CreateIdAttr("UsdUVTexture")
    tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture)
    surface = UsdShade.Shader.Define(stage, f"{path}/surface")
    surface.CreateIdAttr("UsdPreviewSurface")
    surface.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
        tex.ConnectableAPI(), "rgb",
    )
    material.CreateSurfaceOutput().ConnectToSource(surface.ConnectableAPI(), "surface")
    return material


def build_library(lib: Path) -> None:
    """A small library: boxes in several units and axes, a lamp folder with a textured
    material, a folder of textured materials, an HDRI and a texture."""
    lib.mkdir(parents=True)
    _box(lib / "table.usda", (1.2, 0.1, 0.8), parts=("Top", "Leg"))
    _box(lib / "chair.usda", (0.5, 0.5, 0.5))
    _box(lib / "chair_cm.usda", (50.0, 50.0, 50.0), mpu=0.01)
    _box(lib / "post.usda", (0.2, 0.2, 1.0), up="Z")
    _box(lib / "crate.usda", (0.3, 0.3, 0.3))
    _box(lib / "stone.usda", (0.2, 0.2, 0.2))
    _box(lib / "ground.usda", (10.0, 0.1, 10.0))

    lamp = lib / "lamp"
    lamp.mkdir()
    _png(lamp / "maps" / "shade.png", b"shade")
    _box(lamp / "geo.usda", (0.4, 0.6, 0.4), parts=("Base", "Shade"), name="lamp")
    mtl = _stage(lamp / "mtl.usda")
    mtl.SetDefaultPrim(mtl.OverridePrim("/lamp"))
    cloth = _textured_material(mtl, "/lamp/mtl/cloth", "./maps/shade.png")
    UsdShade.MaterialBindingAPI.Apply(mtl.OverridePrim("/lamp/Shade")).Bind(cloth)
    mtl.Save()
    root = _stage(lamp / "lamp.usda")
    root_prim = UsdGeom.Xform.Define(root, "/lamp").GetPrim()
    root.SetDefaultPrim(root_prim)
    root_prim.GetReferences().AddReference("./mtl.usda")
    root_prim.GetPayloads().AddPayload("./geo.usda")
    root.Save()

    wood = lib / "woodmat"
    wood.mkdir()
    _png(wood / "maps" / "wood.png", b"wood")
    materials = _stage(wood / "woodmat.usda")
    materials.SetDefaultPrim(materials.DefinePrim("/Materials", "Scope"))
    _textured_material(materials, "/Materials/wood", "./maps/wood.png")
    materials.Save()

    _png(lib / "hdri" / "sky.png", b"sky")
    _png(lib / "textures" / "glow.png", b"glow")


def library_state(tmp_path: Path, *, up: str = "Y", mpu: float = 1.0) -> SceneState:
    """A state over a fresh :func:`build_library` and a new project in it."""
    library = tmp_path / "library"
    build_library(library)
    state = SceneState(library_dir=library, projects_dir=tmp_path / "projects")
    created = asyncio.run(dispatcher.execute(state, "create_project", {
        "name": "test", "up_axis": up, "meters_per_unit": mpu,
    }))
    assert created.success, created.error
    return state
