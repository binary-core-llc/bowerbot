# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics summary — what physics an asset or scene carries, and dropping an empty phy.usda."""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Sdf, Usd

from bowerbot.schemas import (
    AssetPhysicsSummary,
    ASWFLayerNames,
    PhysicsPrimSummary,
    ScenePhysicsSummary,
)
from bowerbot.utils.core.asset_folder import (
    delete_side_layer,
)
from bowerbot.utils.core.values import usd_to_json

logger = logging.getLogger(__name__)


def get_physics_summary(asset_dir: Path) -> AssetPhysicsSummary:
    """Every authored physics opinion in the asset's ``phy.usda``."""
    phy_path = asset_dir / ASWFLayerNames.PHY
    if not phy_path.exists():
        return AssetPhysicsSummary(asset_path=str(asset_dir))
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is None:
        return AssetPhysicsSummary(
            asset_path=str(asset_dir), has_physics_layer=True,
        )

    prims: list[PhysicsPrimSummary] = []

    def visit(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if not isinstance(spec, Sdf.PrimSpec):
            return
        apis = read_api_schemas(spec)
        attrs = {a.name: usd_to_json(a.default) for a in spec.attributes}
        rels = {
            r.name: [str(t) for t in r.targetPathList.explicitItems]
            for r in spec.relationships
        }
        if apis or attrs or rels:
            prims.append(PhysicsPrimSummary(
                prim_path=str(path),
                applied_apis=apis,
                attributes=attrs,
                relationships=rels,
            ))

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return AssetPhysicsSummary(
        asset_path=str(asset_dir), has_physics_layer=True, prims=prims,
    )


def get_scene_physics_summary(
    stage: Usd.Stage, prim_path: str,
) -> ScenePhysicsSummary:
    """Scene-side physics opinions on *prim_path* and its descendants."""
    layer = stage.GetRootLayer()
    if layer.GetPrimAtPath(prim_path) is None:
        return ScenePhysicsSummary(prim_path=prim_path)

    prims: list[PhysicsPrimSummary] = []

    def visit(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if not isinstance(spec, Sdf.PrimSpec):
            return
        apis = read_api_schemas(spec)
        attrs = {
            a.name: usd_to_json(a.default)
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
            prims.append(PhysicsPrimSummary(
                prim_path=str(path),
                applied_apis=apis,
                attributes=attrs,
                relationships=rels,
            ))

    layer.Traverse(Sdf.Path(prim_path), visit)
    return ScenePhysicsSummary(prim_path=prim_path, prims=prims)


def remove_physics_layer_if_empty(asset_dir: Path) -> bool:
    """Delete ``phy.usda`` and drop its reference when no opinions remain."""
    if not (asset_dir / ASWFLayerNames.PHY).exists():
        return False
    if get_physics_summary(asset_dir).prims:
        return False
    delete_side_layer(asset_dir, ASWFLayerNames.PHY)
    return True


def read_api_schemas(prim_spec: Sdf.PrimSpec) -> list[str]:
    """Union of every apiSchemas list-op slot on *prim_spec*."""
    list_op = prim_spec.GetInfo("apiSchemas")
    if list_op is None:
        return []
    apis: list[str] = []
    for slot in ("prependedItems", "appendedItems", "explicitItems"):
        apis.extend(getattr(list_op, slot, ()))
    return apis
