# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset freeze — baking root transforms into the geometry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pxr import Gf, Usd, UsdGeom

from bowerbot.schemas import ASWFLayerNames


def freeze_one_asset(assets_dir: Path, name: str) -> dict[str, Any]:
    """Bake root transforms in a single asset folder; raise if folder/geo missing."""
    asset_dir = assets_dir / name
    if not asset_dir.exists() or not asset_dir.is_dir():
        msg = f"Asset folder not found: {name}"
        raise ValueError(msg)

    geo_path = asset_dir / ASWFLayerNames.GEO
    if not geo_path.exists():
        msg = f"No {ASWFLayerNames.GEO} in asset folder '{name}'"
        raise ValueError(msg)

    baked = bake_root_transforms(geo_path)
    return {"name": name, "baked": baked}


def bake_root_transforms(geometry_file: Path) -> bool:
    """Bake the root prim's local transform into descendant geometry."""
    stage = Usd.Stage.Open(str(geometry_file))
    if stage is None:
        return False

    root_prim = stage.GetDefaultPrim()
    if not root_prim or not root_prim.IsValid():
        return False

    xformable = UsdGeom.Xformable(root_prim)
    if not xformable:
        return False

    matrix = xformable.GetLocalTransformation()
    if _matrix_is_identity(matrix):
        return False

    normal_matrix = matrix.GetInverse().GetTranspose()

    for prim in Usd.PrimRange(root_prim):
        pb = UsdGeom.PointBased(prim)
        if not pb:
            continue
        _bake_into_point_based(pb, matrix, normal_matrix)

    xformable.ClearXformOpOrder()
    for prop_name in list(root_prim.GetPropertyNames()):
        if prop_name.startswith("xformOp:") or prop_name == "xformOpOrder":
            root_prim.RemoveProperty(prop_name)

    stage.Save()
    return True


def root_transform_is_identity(geometry_file: Path) -> bool:
    """Return True if the file's defaultPrim has identity local transform."""
    stage = Usd.Stage.Open(str(geometry_file))
    if stage is None:
        return True
    prim = stage.GetDefaultPrim()
    if not prim or not prim.IsValid():
        return True
    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        return True
    return _matrix_is_identity(xformable.GetLocalTransformation())


def _matrix_is_identity(matrix: Gf.Matrix4d, epsilon: float = 1e-5) -> bool:
    """Return True if *matrix* is the identity matrix within *epsilon*."""
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            if abs(matrix[i, j] - expected) > epsilon:
                return False
    return True


def _bake_into_point_based(
    pb: UsdGeom.PointBased,
    matrix: Gf.Matrix4d,
    normal_matrix: Gf.Matrix4d,
) -> None:
    """Apply *matrix* to a PointBased prim's points / normals / extent."""
    points_attr = pb.GetPointsAttr()
    points = points_attr.Get()
    if points is None or len(points) == 0:
        return

    new_points = [matrix.Transform(p) for p in points]
    points_attr.Set(new_points)

    normals_attr = pb.GetNormalsAttr()
    normals = normals_attr.Get()
    if normals is not None and len(normals) > 0:
        new_normals = [
            normal_matrix.TransformDir(n).GetNormalized() for n in normals
        ]
        normals_attr.Set(new_normals)

    extent_attr = pb.GetExtentAttr()
    if extent_attr.HasAuthoredValue():
        xs = [p[0] for p in new_points]
        ys = [p[1] for p in new_points]
        zs = [p[2] for p in new_points]
        extent_attr.Set([
            Gf.Vec3f(min(xs), min(ys), min(zs)),
            Gf.Vec3f(max(xs), max(ys), max(zs)),
        ])
