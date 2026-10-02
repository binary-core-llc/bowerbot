# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""References and payloads: read and clear them, and find the files a layer points to."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf
from pxr import Usd

# ── Reading references ──


def reference_paths(prim_spec: Sdf.PrimSpec) -> list[str]:
    """Asset paths of the references a prim spec adds, in the order they apply."""
    return [
        arc.assetPath for arc in prim_spec.referenceList.GetAppliedItems() if arc.assetPath
    ]


def payload_paths(prim_spec: Sdf.PrimSpec) -> list[str]:
    """Asset paths of the payloads a prim spec adds, in the order they apply."""
    return [
        arc.assetPath for arc in prim_spec.payloadList.GetAppliedItems() if arc.assetPath
    ]


def get_prim_ref_paths(prim: Usd.Prim) -> list[str]:
    """Return all reference asset paths authored on *prim*."""
    refs = prim.GetMetadata("references")
    if not refs:
        return []
    return [arc.assetPath for arc in refs.GetAppliedItems() if arc.assetPath]


def has_direct_references(stage: Usd.Stage, prim_path: str) -> bool:
    """Whether *prim_path* has any directly-authored reference arc in the stage's root layer."""
    layer = stage.GetRootLayer()
    spec = layer.GetPrimAtPath(prim_path)
    if spec is None:
        return False
    return spec.HasInfo("references")


def layer_file_targets(layer: Sdf.Layer) -> set[Path]:
    """The files *layer* points to: references, payloads and asset-valued attributes."""
    base = Path(layer.realPath).parent
    targets: set[Path] = set()

    def add(asset_path: str) -> None:
        if asset_path:
            targets.add((base / asset_path).resolve())

    def visit(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if isinstance(spec, Sdf.PrimSpec):
            for asset_path in (*reference_paths(spec), *payload_paths(spec)):
                add(asset_path)
        elif isinstance(spec, Sdf.AttributeSpec):
            value = spec.default
            if isinstance(value, Sdf.AssetPath):
                add(value.path)
            elif isinstance(value, Sdf.AssetPathArray):
                for item in value:
                    add(item.path)

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return targets

# ── Editing references ──


def clear_direct_references(stage: Usd.Stage, prim_path: str) -> None:
    """Remove all directly-authored reference arcs at *prim_path* in the stage's root layer."""
    layer = stage.GetRootLayer()
    spec = layer.GetPrimAtPath(prim_path)
    if spec is None:
        return
    if spec.HasInfo("references"):
        spec.ClearInfo("references")
        layer.Save()
