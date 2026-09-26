# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Nested assets — assets placed inside another asset's contents.usda."""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom

from bowerbot.schemas import (
    AssetScopeNames,
    ASWFLayerNames,
    SceneNamespace,
    TransformParams,
)
from bowerbot.utils.core.asset_folder import (
    ensure_layer_scope,
    ensure_root_reference,
    ensure_side_layer,
    get_mpu,
    remove_empty_layer,
    resolve_default_prim_name,
)
from bowerbot.utils.core.metrics import read_mpu

logger = logging.getLogger(__name__)


def add_nested_asset_reference(
    container_dir: Path,
    group: str,
    prim_name: str,
    ref_asset_path: str,
    transform: TransformParams,
) -> str:
    """Author a nested asset reference inside a container's ``contents.usda``."""
    contents_path = ensure_side_layer(container_dir, ASWFLayerNames.CONTENTS)
    default_prim_name = resolve_default_prim_name(container_dir)
    contents_layer = Sdf.Layer.FindOrOpen(str(contents_path))

    ensure_layer_scope(contents_layer, default_prim_name, AssetScopeNames.CONTENTS, "Xform")
    _ensure_group_scope(contents_layer, default_prim_name, group)
    contents_layer.Save()

    stage = Usd.Stage.Open(str(contents_path))
    if stage is None:
        msg = f"Cannot open contents layer: {contents_path}"
        raise RuntimeError(msg)

    wrapper_path = f"/{default_prim_name}/contents/{group}/{prim_name}"
    wrapper = UsdGeom.Xform.Define(stage, wrapper_path)

    container_mpu = get_mpu(container_dir)
    factor = 1.0 / container_mpu if container_mpu > 0 else 1.0

    ref_full_path = (container_dir / ref_asset_path).resolve()
    nested_mpu = (
        read_mpu(ref_full_path)
        if ref_full_path.exists() else container_mpu
    )
    unit_scale = (
        nested_mpu / container_mpu if container_mpu > 0 else 1.0
    )

    sx, sy, sz = transform.scale
    final_scale = (sx * unit_scale, sy * unit_scale, sz * unit_scale)

    xformable = UsdGeom.Xformable(wrapper)
    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(
        Gf.Vec3d(
            transform.translate[0] * factor,
            transform.translate[1] * factor,
            transform.translate[2] * factor,
        ),
    )
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(*transform.rotate))
    xformable.AddScaleOp().Set(Gf.Vec3f(*final_scale))

    asset_inner = stage.DefinePrim(f"{wrapper_path}/{SceneNamespace.ASSET_CHILD}", "Xform")
    asset_inner.GetReferences().AddReference(ref_asset_path)

    stage.Save()
    ensure_root_reference(container_dir, ASWFLayerNames.CONTENTS)

    logger.info(
        "Added nested asset %s -> %s in %s/%s",
        prim_name, ref_asset_path, container_dir.name, ASWFLayerNames.CONTENTS,
    )
    return wrapper_path


def update_nested_asset_transform(
    container_dir: Path,
    group: str,
    prim_name: str,
    translate: tuple[float, float, float],
    rotate: tuple[float, float, float],
) -> bool:
    """Update translate/rotate on a nested-asset wrapper in ``contents.usda``."""
    contents_path = container_dir / ASWFLayerNames.CONTENTS
    if not contents_path.exists():
        return False

    default_prim_name = resolve_default_prim_name(container_dir)
    wrapper_path = f"/{default_prim_name}/contents/{group}/{prim_name}"

    stage = Usd.Stage.Open(str(contents_path))
    if stage is None:
        return False
    wrapper = stage.GetPrimAtPath(wrapper_path)
    if not wrapper or not wrapper.IsValid():
        return False

    container_mpu = get_mpu(container_dir)
    factor = 1.0 / container_mpu if container_mpu > 0 else 1.0

    xformable = UsdGeom.Xformable(wrapper)
    existing_scale_op = next(
        (op for op in xformable.GetOrderedXformOps()
         if op.GetOpType() == UsdGeom.XformOp.TypeScale),
        None,
    )
    existing_scale = (
        existing_scale_op.Get() if existing_scale_op is not None
        else Gf.Vec3f(1.0, 1.0, 1.0)
    )

    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(
        Gf.Vec3d(translate[0] * factor, translate[1] * factor, translate[2] * factor),
    )
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(*rotate))
    xformable.AddScaleOp().Set(existing_scale)

    stage.Save()
    logger.info(
        "Updated nested transform %s in %s/%s",
        prim_name, container_dir.name, ASWFLayerNames.CONTENTS,
    )
    return True


def remove_nested_asset_reference(
    container_dir: Path,
    group: str,
    prim_name: str,
) -> bool:
    """Remove a nested asset reference from a container's ``contents.usda``.

    Idempotent: returns True whether the spec was deleted or was already
    absent. Returns False only on a real error (cannot open the layer).
    Empty group scopes and an empty contents layer are cleaned up
    automatically via :func:`cleanup_unused_contents_in_folder`.
    """
    contents_path = container_dir / ASWFLayerNames.CONTENTS
    if not contents_path.exists():
        return True

    layer = Sdf.Layer.FindOrOpen(str(contents_path))
    if layer is None:
        return False

    default_prim_name = resolve_default_prim_name(container_dir)
    parent_path = Sdf.Path(f"/{default_prim_name}/contents/{group}")
    parent_spec = layer.GetPrimAtPath(parent_path)
    if parent_spec is not None and prim_name in parent_spec.nameChildren:
        del parent_spec.nameChildren[prim_name]
        layer.Save()
        logger.info(
            "Removed nested asset %s from %s/%s",
            prim_name, container_dir.name, ASWFLayerNames.CONTENTS,
        )

    cleanup_unused_contents_in_folder(container_dir)
    return True


def cleanup_unused_contents_in_folder(container_dir: Path) -> list[str]:
    """Drop empty group scopes in *container_dir*'s ``contents.usda``.

    Mirrors :func:`bowerbot.utils.material_utils.cleanup_unused_in_folder`:
    removes per-prim entries that no longer carry meaningful data, then
    deletes the layer file when it has nothing left and rebuilds the
    root references without it. For contents, "meaningful" means a
    reference arc; empty group scopes (``Props``, ``Furniture``, etc.)
    are the unused entries.
    """
    contents_path = container_dir / ASWFLayerNames.CONTENTS
    if not contents_path.exists():
        return []

    layer = Sdf.Layer.FindOrOpen(str(contents_path))
    if layer is None:
        return []

    default_prim_name = resolve_default_prim_name(container_dir)
    contents_scope_path = Sdf.Path(f"/{default_prim_name}/{AssetScopeNames.CONTENTS}")
    contents_spec = layer.GetPrimAtPath(contents_scope_path)

    removed: list[str] = []
    if contents_spec is not None:
        empty_groups = [
            child_name for child_name in list(contents_spec.nameChildren.keys())
            if len(contents_spec.nameChildren[child_name].nameChildren) == 0
        ]
        for child_name in empty_groups:
            del contents_spec.nameChildren[child_name]
            removed.append(child_name)
        if removed:
            layer.Save()

    remove_empty_layer(
        contents_path, container_dir, lambda p: p.HasAuthoredReferences(),
    )

    if removed:
        logger.info(
            "Cleaned %d empty group(s) from %s/%s",
            len(removed), container_dir.name, ASWFLayerNames.CONTENTS,
        )
    return removed


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
