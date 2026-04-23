# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for intake_service: detection and self-contained folder intake."""

import tempfile
from pathlib import Path

import pytest
from pxr import Sdf, Usd, UsdGeom, UsdShade, UsdUtils

from bowerbot.schemas import DetectionOutcome
from bowerbot.services import intake_service


# ── Helpers ──


def _write_geo(path: Path, prim_name: str = "geo") -> None:
    """Write a minimal geometry layer."""
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root = stage.DefinePrim(f"/{prim_name}", "Xform")
    stage.SetDefaultPrim(root)
    UsdGeom.Cube.Define(stage, f"/{prim_name}/Mesh")
    stage.Save()


def _write_root_referencing(path: Path, targets: list[str]) -> None:
    """Write a root layer that references *targets* as sibling assets."""
    refs = ",\n        ".join(f"@{t}@" for t in targets)
    path.write_text(
        (
            "#usda 1.0\n"
            "(\n"
            f'    defaultPrim = "root"\n'
            "    metersPerUnit = 1.0\n"
            "    upAxis = \"Y\"\n"
            f"    subLayers = [\n        {refs}\n    ]\n"
            ")\n"
            'def Xform "root" { }\n'
        ),
        encoding="utf-8",
    )


def _write_material_with_texture(
    layer_path: Path, texture_path: str,
) -> None:
    """Write a Material layer whose shader reads *texture_path*."""
    stage = Usd.Stage.CreateNew(str(layer_path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    scope = stage.DefinePrim("/mtl", "Scope")
    stage.SetDefaultPrim(scope)
    material = UsdShade.Material.Define(stage, "/mtl/surface")
    shader = UsdShade.Shader.Define(stage, "/mtl/surface/tex")
    shader.CreateIdAttr("UsdUVTexture")
    shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(
        Sdf.AssetPath(texture_path),
    )
    out = shader.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
    material.CreateSurfaceOutput().ConnectToSource(out)
    stage.Save()


# ── detect_folder_root ──


def test_detect_canonical_folder():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "table"
        folder.mkdir()
        _write_geo(folder / "table.usda", "table")

        detection = intake_service.detect_folder_root(folder)
        assert detection.outcome is DetectionOutcome.UNAMBIGUOUS
        assert Path(detection.root).name == "table.usda"


def test_detect_single_file_non_canonical():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "table"
        folder.mkdir()
        _write_geo(folder / "something_else.usda", "table")

        detection = intake_service.detect_folder_root(folder)
        assert detection.outcome is DetectionOutcome.UNAMBIGUOUS
        assert Path(detection.root).name == "something_else.usda"


def test_detect_dep_graph_identifies_root():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "table"
        folder.mkdir()
        _write_geo(folder / "geo.usda", "root")
        _write_root_referencing(folder / "root.usda", ["./geo.usda"])

        detection = intake_service.detect_folder_root(folder)
        assert detection.outcome is DetectionOutcome.UNAMBIGUOUS
        assert Path(detection.root).name == "root.usda"


def test_detect_ambiguous_independent_files():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "assorted"
        folder.mkdir()
        _write_geo(folder / "alpha.usda", "alpha")
        _write_geo(folder / "beta.usda", "beta")

        detection = intake_service.detect_folder_root(folder)
        assert detection.outcome is DetectionOutcome.AMBIGUOUS
        assert len(detection.candidates) == 2


def test_detect_empty_folder():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "empty"
        folder.mkdir()

        detection = intake_service.detect_folder_root(folder)
        assert detection.outcome is DetectionOutcome.EMPTY


# ── intake_folder ──


def test_intake_canonical_is_fast_path():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src" / "table"
        src.mkdir(parents=True)
        _write_geo(src / "table.usda", "table")
        project_assets = Path(tmp) / "project_assets"
        project_assets.mkdir()

        report = intake_service.intake_folder(src, project_assets)

        assert report.scene_ref_path == "assets/table/table.usda"
        assert not report.was_renamed
        assert report.files_copied == 1
        assert report.localized_layers == []
        assert report.localized_assets == []
        assert (project_assets / "table" / "table.usda").exists()


def test_intake_non_canonical_canonicalizes_root():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src" / "wall"
        src.mkdir(parents=True)
        _write_geo(src / "geo.usda", "root")
        _write_root_referencing(src / "root.usda", ["./geo.usda"])
        project_assets = Path(tmp) / "project_assets"
        project_assets.mkdir()

        report = intake_service.intake_folder(src, project_assets)

        assert report.was_renamed
        assert report.root_original_name == "root.usda"
        assert report.root_canonical_name == "wall.usda"
        assert (project_assets / "wall" / "wall.usda").exists()
        assert (project_assets / "wall" / "geo.usda").exists()
        assert not (project_assets / "wall" / "root.usda").exists()

        # Composition must still resolve under the new root name.
        layers, _, unresolved = UsdUtils.ComputeAllDependencies(
            str(project_assets / "wall" / "wall.usda"),
        )
        assert not unresolved
        assert len(layers) == 2  # root + geo


def test_intake_localizes_external_texture():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # External texture lives two levels above the source folder.
        shared = tmp / "shared_library"
        shared.mkdir()
        texture = shared / "diffuse.png"
        texture.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        src = tmp / "src" / "wall"
        src.mkdir(parents=True)
        _write_geo(src / "geo.usda", "wall")
        _write_material_with_texture(
            src / "mtl.usda", str(texture.resolve()).replace("\\", "/"),
        )
        _write_root_referencing(src / "wall.usda", ["./geo.usda", "./mtl.usda"])

        project_assets = tmp / "project_assets"
        project_assets.mkdir()

        report = intake_service.intake_folder(src, project_assets)

        assert len(report.localized_assets) == 1
        assert (project_assets / "wall" / "textures" / "diffuse.png").exists()

        layers, assets, unresolved = UsdUtils.ComputeAllDependencies(
            str(project_assets / "wall" / "wall.usda"),
        )
        assert not unresolved
        target = (project_assets / "wall").resolve()
        for asset_path in assets:
            assert Path(asset_path).resolve().is_relative_to(target)


def test_intake_rejects_missing_external_reference():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src" / "wall"
        src.mkdir(parents=True)
        _write_geo(src / "geo.usda", "wall")
        (src / "wall.usda").write_text(
            (
                "#usda 1.0\n"
                "(\n"
                '    defaultPrim = "wall"\n'
                "    metersPerUnit = 1.0\n"
                '    upAxis = "Y"\n'
                "    subLayers = [\n"
                "        @./geo.usda@,\n"
                "        @../does_not_exist/extra.usda@\n"
                "    ]\n"
                ")\n"
                'def Xform "wall" { }\n'
            ),
            encoding="utf-8",
        )
        project_assets = Path(tmp) / "project_assets"
        project_assets.mkdir()

        with pytest.raises(ValueError, match="did not resolve"):
            intake_service.intake_folder(src, project_assets)

        # Rollback must leave no half-created folder behind.
        assert not (project_assets / "wall").exists()


def test_intake_ambiguous_folder_raises():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src" / "furniture"
        src.mkdir(parents=True)
        _write_geo(src / "alpha.usda", "alpha")
        _write_geo(src / "beta.usda", "beta")
        project_assets = Path(tmp) / "project_assets"
        project_assets.mkdir()

        with pytest.raises(ValueError, match="multiple independent"):
            intake_service.intake_folder(src, project_assets)
