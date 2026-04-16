# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Nested-asset service — place one asset reference inside another.

Writes reference arcs into a container asset's ``contents.usda``,
handling the ASWF layer scaffolding, meters→asset-units conversion
on the input transform, and cross-unit scale compensation when the
nested asset's ``metersPerUnit`` differs from the container's.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom

from bowerbot.schemas import ASWFLayerNames, TransformParams
from bowerbot.services.asset_service import (
    ensure_layer_scope,
    ensure_root_reference,
    read_asset_mpu_from_file,
    resolve_default_prim_name,
)
from bowerbot.services.geometry_service import get_mpu

logger = logging.getLogger(__name__)


def add_nested_asset_reference(
    container_dir: Path,
    group: str,
    prim_name: str,
    ref_asset_path: str,
    transform: TransformParams,
) -> str:
    """Add a nested asset reference to a container's ``contents.usda``.

    The nested asset's geometry lives wherever it normally lives; only
    a reference arc is written.

    Args:
        container_dir: ASWF folder that will hold the nested reference.
        group: Logical grouping under ``/{root}/contents/``
            (e.g. ``"Furniture"``).
        prim_name: Name of the new reference prim.
        ref_asset_path: Reference target — typically relative to the
            container folder (e.g. ``"../counter/counter.usda"``).
        transform: Translate/rotate/scale in the container's
            coordinate space (meters).

    Returns:
        The composed prim path in the container's root stage.
    """
    contents_path = container_dir / ASWFLayerNames.CONTENTS
    default_prim_name = resolve_default_prim_name(container_dir)

    if contents_path.exists():
        contents_layer = Sdf.Layer.FindOrOpen(str(contents_path))
    else:
        contents_layer = Sdf.Layer.CreateNew(str(contents_path))
        contents_layer.defaultPrim = default_prim_name

    ensure_layer_scope(contents_layer, default_prim_name, "contents", "Xform")
    _ensure_group_scope(contents_layer, default_prim_name, group)
    contents_layer.Save()

    stage = Usd.Stage.Open(str(contents_path))
    if stage is None:
        msg = f"Cannot open contents layer: {contents_path}"
        raise RuntimeError(msg)

    ref_prim_path = f"/{default_prim_name}/contents/{group}/{prim_name}"
    ref_prim = UsdGeom.Xform.Define(stage, ref_prim_path)
    ref_prim.GetPrim().GetReferences().AddReference(ref_asset_path)

    container_mpu = get_mpu(container_dir)
    factor = 1.0 / container_mpu if container_mpu > 0 else 1.0

    ref_full_path = (container_dir / ref_asset_path).resolve()
    nested_mpu = (
        read_asset_mpu_from_file(ref_full_path)
        if ref_full_path.exists() else container_mpu
    )
    compensation = (
        nested_mpu / container_mpu if container_mpu > 0 else 1.0
    )
    final_scale = (
        transform.scale[0] * compensation,
        transform.scale[1] * compensation,
        transform.scale[2] * compensation,
    )

    xformable = UsdGeom.Xformable(ref_prim)
    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(
        Gf.Vec3d(
            transform.translate[0] * factor,
            transform.translate[1] * factor,
            transform.translate[2] * factor,
        ),
    )
    if any(v != 0.0 for v in transform.rotate):
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(*transform.rotate))
    if final_scale != (1.0, 1.0, 1.0):
        xformable.AddScaleOp().Set(Gf.Vec3f(*final_scale))

    stage.Save()
    ensure_root_reference(container_dir, ASWFLayerNames.CONTENTS)

    logger.info(
        "Added nested asset %s -> %s in %s/%s",
        prim_name, ref_asset_path, container_dir.name, ASWFLayerNames.CONTENTS,
    )
    return ref_prim_path


def _ensure_group_scope(
    layer: Sdf.Layer, default_prim_name: str, group: str,
) -> None:
    """Ensure ``/{root}/contents/{group}`` exists as an Xform."""
    group_path = Sdf.Path(f"/{default_prim_name}/contents/{group}")
    if layer.GetPrimAtPath(group_path):
        return
    Sdf.CreatePrimInLayer(layer, group_path)
    group_prim = layer.GetPrimAtPath(group_path)
    group_prim.specifier = Sdf.SpecifierDef
    group_prim.typeName = "Xform"
