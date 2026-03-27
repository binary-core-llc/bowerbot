# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test dependency resolution and material discovery."""

import tempfile
from pathlib import Path

from pxr import Usd, UsdGeom, UsdShade

from bowerbot.engine.dependency_resolver import DependencyResolver


# ── Helpers ──────────────────────────────────────────────────────


def create_test_geometry(directory: Path, name: str) -> Path:
    """Create a simple USD geometry asset."""
    path = directory / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{name}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, f"/{name}/Mesh")
    stage.Save()
    return path


def create_test_material(directory: Path, name: str) -> Path:
    """Create a material .usda file under /mtl/<name>."""
    path = directory / f"mtl_{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    scope = stage.DefinePrim("/mtl", "Scope")
    stage.SetDefaultPrim(scope)
    UsdShade.Material.Define(stage, f"/mtl/{name}")
    stage.Save()
    return path


def create_test_look_file(
    directory: Path,
    look_name: str,
    geometry_file: str,
    material_files: list[str],
) -> Path:
    """Create a look .usda that sublayers geometry + materials."""
    path = directory / f"{look_name}.usda"
    sub_layers = ",\n        ".join(
        f"@{m}@" for m in material_files + [geometry_file]
    )
    content = f"""#usda 1.0
(
    defaultPrim = "root"
    metersPerUnit = 1.0
    subLayers = [
        {sub_layers}
    ]
    upAxis = "Y"
)
"""
    path.write_text(content, encoding="utf-8")
    return path


# ── Dependency Resolver Tests ────────────────────────────────────


def test_resolver_finds_sublayers():
    """DependencyResolver finds all sublayered files."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mat_dir = tmp_path / "materials"
        mat_dir.mkdir()

        create_test_geometry(tmp_path, "table")
        create_test_material(mat_dir, "wood")
        create_test_material(mat_dir, "metal")
        look = create_test_look_file(
            tmp_path, "table_look", "table.usda",
            ["materials/mtl_wood.usda", "materials/mtl_metal.usda"],
        )

        resolver = DependencyResolver()
        found, missing = resolver.resolve(look)
        dep_names = {d.name for d in found}

        assert "table_look.usda" in dep_names
        assert "table.usda" in dep_names
        assert "mtl_wood.usda" in dep_names
        assert "mtl_metal.usda" in dep_names
        assert len(found) == 4
        assert len(missing) == 0


def test_resolver_handles_missing_file():
    """DependencyResolver reports missing dependencies."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        look = tmp_path / "look.usda"
        look.write_text(
            '#usda 1.0\n(\n    subLayers = [@missing.usda@]\n)\n',
            encoding="utf-8",
        )

        resolver = DependencyResolver()
        found, missing = resolver.resolve(look)
        assert len(found) == 1
        assert found[0].name == "look.usda"
        assert len(missing) == 1
        assert missing[0].name == "missing.usda"


def test_resolver_handles_circular():
    """DependencyResolver does not loop on circular sublayer references."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        a = tmp_path / "a.usda"
        b = tmp_path / "b.usda"
        a.write_text(
            '#usda 1.0\n(\n    subLayers = [@b.usda@]\n)\n',
            encoding="utf-8",
        )
        b.write_text(
            '#usda 1.0\n(\n    subLayers = [@a.usda@]\n)\n',
            encoding="utf-8",
        )

        resolver = DependencyResolver()
        found, missing = resolver.resolve(a)
        assert len(found) == 2


def test_resolver_find_first_material():
    """find_first_material returns the prim path of the first Material."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mat = create_test_material(tmp_path, "wood")

        result = DependencyResolver.find_first_material(mat)
        assert result == "/mtl/wood"
