# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The asset library every golden scenario uses, built by code with fixed content."""

from __future__ import annotations

from pathlib import Path

from pxr import Gf
from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade
from pxr import UsdUtils

# A tiny, fixed PNG (1x1 pixel) and HDR payload: real image bytes, so file
# copies and hashes are stable.
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63f8cfc0f01f0005000201a5e0e4ec"
    "0000000049454e44ae426082",
)
HDR_BYTES = b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 1\n\x80\x80\x80\x80"


def _stage(path: Path, *, up: str = "Y", mpu: float = 1.0) -> Usd.Stage:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y if up == "Y" else UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, mpu)
    return stage


def _bare_stage(path: Path) -> Usd.Stage:
    """A stage that declares no up axis and no metersPerUnit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return Usd.Stage.CreateNew(str(path))


def _box(stage: Usd.Stage, path: str, center: tuple[float, float, float],
         size: tuple[float, float, float]) -> None:
    """A cube of *size* (x, y, z extents) centred at *center*."""
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(1.0)
    xf = UsdGeom.Xformable(cube)
    xf.AddTranslateOp().Set(Gf.Vec3d(*center))
    xf.AddScaleOp().Set(Gf.Vec3f(*size))


def _root(stage: Usd.Stage, name: str) -> None:
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, f"/{name}").GetPrim())


def _material(stage: Usd.Stage, path: str, color: tuple[float, float, float],
              texture: str | None = None) -> UsdShade.Material:
    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/PreviewSurface")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    if texture is not None:
        reader = UsdShade.Shader.Define(stage, f"{path}/Diffuse")
        reader.CreateIdAttr("UsdUVTexture")
        reader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture)
    return material


def build_library(root: Path) -> Path:
    """Write the golden asset library under *root* and return it.

    - ``table.usda``: a table with a Top and two Legs (Y-up, meters).
    - ``chair.usda``: a chair with a Seat and a Back (Y-up, meters).
    - ``chair_cm.usda``: the same chair authored in centimeters.
    - ``post_z.usda``: a post authored Z-up.
    - ``unfrozen.usda``: a box whose root carries a translate and scale (an
      unfrozen DCC export).
    - ``rooted_mesh.usda``: a cube that is itself the root prim (no Xform).
    - ``path_curve.usda``: a linear BasisCurves path for scatter_along_path.
    - ``crate.usda``: a single box.
    - ``ground.usda``: a 10 x 10 m ground mesh (a surface for scatter and drops).
    - ``lamp/``: an ASWF folder (root + ``geo.usda`` + textured ``mtl.usda``
      + ``maps/``) with a low-detail ``geo_low.usda`` beside it.
    - ``lamp_lod/``: a folder whose root ships its own LOD variant set
      (``shipped_lod``: high = ``geo.usda``, low = ``geo_low.usda``).
    - ``materials/oak.usda``, ``materials/steel.usda``: material library files.
    - ``hdri/studio.hdr``, ``textures/wood_diffuse.png``: an HDRI and a texture.
    - ``gem.usdz``: a packaged asset.
    - ``bare.usda``: a box that declares no up axis and no metersPerUnit.
    - ``bare_kit/``: an ASWF folder (root + ``geo.usda``) that declares neither.
    """
    root.mkdir(parents=True, exist_ok=True)

    table = _stage(root / "table.usda")
    _root(table, "table")
    _box(table, "/table/Top", (0.0, 0.75, 0.0), (1.2, 0.05, 0.8))
    _box(table, "/table/Leg_L", (-0.55, 0.375, 0.0), (0.05, 0.75, 0.05))
    _box(table, "/table/Leg_R", (0.55, 0.375, 0.0), (0.05, 0.75, 0.05))
    table.Save()

    chair = _stage(root / "chair.usda")
    _root(chair, "chair")
    _box(chair, "/chair/Seat", (0.0, 0.45, 0.0), (0.45, 0.05, 0.45))
    _box(chair, "/chair/Back", (0.0, 0.7, -0.2), (0.45, 0.5, 0.05))
    chair.Save()

    chair_cm = _stage(root / "chair_cm.usda", mpu=0.01)
    _root(chair_cm, "chair_cm")
    _box(chair_cm, "/chair_cm/Seat", (0.0, 45.0, 0.0), (45.0, 5.0, 45.0))
    chair_cm.Save()

    post = _stage(root / "post_z.usda", up="Z")
    _root(post, "post_z")
    _box(post, "/post_z/Pole", (0.0, 0.0, 1.0), (0.1, 0.1, 2.0))
    post.Save()

    unfrozen = _stage(root / "unfrozen.usda")
    unfrozen_root = UsdGeom.Xform.Define(unfrozen, "/unfrozen")
    unfrozen.SetDefaultPrim(unfrozen_root.GetPrim())
    unfrozen_root.AddTranslateOp().Set(Gf.Vec3d(0.5, 0.0, 0.0))
    unfrozen_root.AddScaleOp().Set(Gf.Vec3f(2.0, 2.0, 2.0))
    _box(unfrozen, "/unfrozen/Box", (0.0, 0.25, 0.0), (0.5, 0.5, 0.5))
    unfrozen.Save()

    rooted_mesh = _stage(root / "rooted_mesh.usda")
    cube = UsdGeom.Cube.Define(rooted_mesh, "/rooted_mesh")
    cube.GetSizeAttr().Set(0.5)
    rooted_mesh.SetDefaultPrim(cube.GetPrim())
    rooted_mesh.Save()

    path_asset = _stage(root / "path_curve.usda")
    _root(path_asset, "path_curve")
    curve = UsdGeom.BasisCurves.Define(path_asset, "/path_curve/Curve")
    curve.CreateTypeAttr(UsdGeom.Tokens.linear)
    curve.CreateCurveVertexCountsAttr([3])
    curve.CreatePointsAttr([(-3, 0, 0), (0, 0, 3), (3, 0, 0)])
    curve.CreateWidthsAttr([0.05])
    path_asset.Save()

    crate = _stage(root / "crate.usda")
    _root(crate, "crate")
    _box(crate, "/crate/Box", (0.0, 0.25, 0.0), (0.5, 0.5, 0.5))
    crate.Save()

    ground = _stage(root / "ground.usda")
    _root(ground, "ground")
    mesh = UsdGeom.Mesh.Define(ground, "/ground/Plane")
    mesh.CreatePointsAttr([(-5, 0, -5), (5, 0, -5), (5, 0, 5), (-5, 0, 5)])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 3, 2, 1])
    mesh.CreateExtentAttr([(-5, 0, -5), (5, 0, 5)])
    ground.Save()

    lamp_dir = root / "lamp"
    (lamp_dir / "maps").mkdir(parents=True, exist_ok=True)
    (lamp_dir / "maps" / "lamp_diffuse.png").write_bytes(PNG_1PX)
    geo = _stage(lamp_dir / "geo.usda")
    _root(geo, "lamp")
    _box(geo, "/lamp/Base", (0.0, 0.05, 0.0), (0.3, 0.1, 0.3))
    _box(geo, "/lamp/Shade", (0.0, 0.5, 0.0), (0.4, 0.3, 0.4))
    geo.Save()
    low = _stage(lamp_dir / "geo_low.usda")
    _root(low, "lamp")
    _box(low, "/lamp/Base", (0.0, 0.05, 0.0), (0.3, 0.1, 0.3))
    _box(low, "/lamp/Shade", (0.0, 0.5, 0.0), (0.4, 0.3, 0.4))
    low.Save()
    mtl = _stage(lamp_dir / "mtl.usda")
    mtl.SetDefaultPrim(mtl.OverridePrim("/lamp"))
    UsdGeom.Scope.Define(mtl, "/lamp/mtl")
    brass = _material(mtl, "/lamp/mtl/brass", (0.8, 0.6, 0.2), "./maps/lamp_diffuse.png")
    UsdShade.MaterialBindingAPI.Apply(mtl.OverridePrim("/lamp/Shade")).Bind(brass)
    mtl.Save()
    lamp = _stage(lamp_dir / "lamp.usda")
    lamp_root = UsdGeom.Xform.Define(lamp, "/lamp").GetPrim()
    lamp.SetDefaultPrim(lamp_root)
    lamp_root.GetReferences().AddReference("./mtl.usda")
    lamp_root.GetPayloads().AddPayload("./geo.usda")
    lamp.Save()

    lod_dir = root / "lamp_lod"
    for file_name, shade_height in (("geo.usda", 0.3), ("geo_low.usda", 0.2)):
        lod = _stage(lod_dir / file_name)
        _root(lod, "lamp_lod")
        _box(lod, "/lamp_lod/Base", (0.0, 0.05, 0.0), (0.3, 0.1, 0.3))
        _box(lod, "/lamp_lod/Shade", (0.0, 0.5, 0.0), (0.4, shade_height, 0.4))
        lod.Save()
    lod_root = _stage(lod_dir / "lamp_lod.usda")
    lod_prim = UsdGeom.Xform.Define(lod_root, "/lamp_lod").GetPrim()
    lod_root.SetDefaultPrim(lod_prim)
    shipped = lod_prim.GetVariantSets().AddVariantSet("shipped_lod")
    for variant, file_name in (("high", "./geo.usda"), ("low", "./geo_low.usda")):
        shipped.AddVariant(variant)
        shipped.SetVariantSelection(variant)
        with shipped.GetVariantEditContext():
            lod_prim.GetPayloads().AddPayload(file_name)
    shipped.SetVariantSelection("high")
    lod_root.Save()

    for name, color in (("oak", (0.55, 0.35, 0.2)), ("steel", (0.6, 0.6, 0.65))):
        library_material = _stage(root / "materials" / f"{name}.usda")
        _material(library_material, f"/{name}", color)
        library_material.SetDefaultPrim(library_material.GetPrimAtPath(f"/{name}"))
        library_material.Save()

    (root / "hdri").mkdir(exist_ok=True)
    (root / "hdri" / "studio.hdr").write_bytes(HDR_BYTES)
    (root / "textures").mkdir(exist_ok=True)
    (root / "textures" / "wood_diffuse.png").write_bytes(PNG_1PX)

    gem_src = root / "_build" / "gem.usda"
    gem = _stage(gem_src)
    _root(gem, "gem")
    _box(gem, "/gem/Stone", (0.0, 0.1, 0.0), (0.2, 0.2, 0.2))
    gem.Save()
    UsdUtils.CreateNewUsdzPackage(Sdf.AssetPath(str(gem_src)), str(root / "gem.usdz"))
    for leftover in sorted(gem_src.parent.iterdir(), reverse=True):
        leftover.unlink()
    gem_src.parent.rmdir()

    bare = _bare_stage(root / "bare.usda")
    _root(bare, "bare")
    _box(bare, "/bare/Body", (0.0, 0.25, 0.0), (0.5, 0.5, 0.5))
    bare.Save()

    bare_kit_dir = root / "bare_kit"
    bare_geo = _bare_stage(bare_kit_dir / "geo.usda")
    _root(bare_geo, "bare_kit")
    _box(bare_geo, "/bare_kit/Body", (0.0, 0.25, 0.0), (0.5, 0.5, 0.5))
    bare_geo.Save()
    bare_kit = _bare_stage(bare_kit_dir / "bare_kit.usda")
    bare_kit_root = UsdGeom.Xform.Define(bare_kit, "/bare_kit").GetPrim()
    bare_kit.SetDefaultPrim(bare_kit_root)
    bare_kit_root.GetPayloads().AddPayload("./geo.usda")
    bare_kit.Save()

    return root
