# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Summaries of the physics authored on an asset or on a scene prim."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf
from pxr import Usd

from bowerbot import schemas
from bowerbot.utils import physics
from bowerbot.utils import usd


def summarize_asset(asset_dir: Path) -> schemas.AssetPhysicsSummary:
    """Every authored physics opinion in the asset's ``phy.usda``."""
    phy_path = physics.layer.file_path(asset_dir)
    if not phy_path.exists():
        return schemas.AssetPhysicsSummary(asset_path=str(asset_dir))
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is None:
        return schemas.AssetPhysicsSummary(
            asset_path=str(asset_dir), has_physics_layer=True,
        )

    prims: list[schemas.PhysicsPrimSummary] = []

    def visit(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if not isinstance(spec, Sdf.PrimSpec):
            return
        apis = physics.apis.read_api_schemas(spec)
        attrs = {a.name: usd.values.to_jsonable(a.default) for a in spec.attributes}
        rels = {
            r.name: [str(t) for t in r.targetPathList.explicitItems]
            for r in spec.relationships
        }
        if apis or attrs or rels:
            prims.append(schemas.PhysicsPrimSummary(
                prim_path=str(path),
                applied_apis=apis,
                attributes=attrs,
                relationships=rels,
            ))

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return schemas.AssetPhysicsSummary(
        asset_path=str(asset_dir), has_physics_layer=True, prims=prims,
    )


def summarize_scene_prim(
    stage: Usd.Stage, prim_path: str,
) -> schemas.ScenePhysicsSummary:
    """Scene-side physics opinions on *prim_path* and its descendants."""
    layer = stage.GetRootLayer()
    if layer.GetPrimAtPath(prim_path) is None:
        return schemas.ScenePhysicsSummary(prim_path=prim_path)

    prims: list[schemas.PhysicsPrimSummary] = []

    def visit(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if not isinstance(spec, Sdf.PrimSpec):
            return
        apis = physics.apis.read_api_schemas(spec)
        attrs = {
            a.name: usd.values.to_jsonable(a.default)
            for a in spec.attributes
            if a.name.startswith("physics:")
        }
        rels = {
            r.name: [str(t) for t in r.targetPathList.explicitItems]
            for r in spec.relationships
            if r.name.startswith("physics:")
            or r.name == "material:binding:physics"
        }
        if apis or attrs or rels:
            prims.append(schemas.PhysicsPrimSummary(
                prim_path=str(path),
                applied_apis=apis,
                attributes=attrs,
                relationships=rels,
            ))

    layer.Traverse(Sdf.Path(prim_path), visit)
    return schemas.ScenePhysicsSummary(prim_path=prim_path, prims=prims)
