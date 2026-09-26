# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""References — reading and authoring the references that place assets in a scene."""

from __future__ import annotations

from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom

from bowerbot.schemas import AssetFormat, SceneObject
from bowerbot.utils.core.metrics import asset_conform


def get_prim_ref_paths(prim: Usd.Prim) -> list[str]:
    """Return all reference asset paths authored on *prim*."""
    refs = prim.GetMetadata("references")
    if not refs:
        return []
    paths: list[str] = []
    for ref_list in (
        refs.prependedItems,
        refs.appendedItems,
        refs.explicitItems,
    ):
        if not ref_list:
            continue
        for ref in ref_list:
            if ref.assetPath:
                paths.append(ref.assetPath)
    return paths


def get_all_ref_paths(stage: Usd.Stage) -> set[str]:
    """Collect every reference asset path authored on the stage."""
    refs: set[str] = set()
    for prim in stage.Traverse():
        refs.update(get_prim_ref_paths(prim))
    return refs


def find_asset_placements(stage: Usd.Stage, asset_dir: Path) -> list[str]:
    """Return scene prim paths of every wrapper-asset child referencing *asset_dir*."""
    root_path = stage.GetRootLayer().realPath
    if not root_path:
        return []
    stage_dir = Path(root_path).parent
    target_dir = asset_dir.resolve()
    placements: list[str] = []
    for prim in stage.Traverse():
        for ref_path in get_prim_ref_paths(prim):
            resolved = (stage_dir / ref_path).resolve()
            if resolved.exists() and resolved.parent == target_dir:
                placements.append(str(prim.GetPath()))
                break
    return placements


def count_scene_refs_to_asset_dir(stage: Usd.Stage, asset_dir: Path) -> int:
    """Count how many prims in the scene reference *asset_dir*."""
    return len(find_asset_placements(stage, asset_dir))


def find_asset_references(
    project_dir: Path,
    folder_name: str,
    skip_dir: Path | None = None,
) -> list[str]:
    """Scan *project_dir* for USD files referencing *folder_name* in any variant body or payload."""
    referencing: list[str] = []
    for usd_file in project_dir.rglob("*"):
        if usd_file.suffix not in AssetFormat.layer_formats():
            continue
        if skip_dir is not None:
            try:
                usd_file.relative_to(skip_dir)
                continue
            except ValueError:
                pass
        layer = Sdf.Layer.FindOrOpen(str(usd_file))
        if layer is None:
            continue
        if _layer_references_folder(layer, folder_name):
            referencing.append(str(usd_file.relative_to(project_dir)))
    return referencing


def _layer_references_folder(layer: Sdf.Layer, folder_name: str) -> bool:
    """Whether any prim spec in *layer* (including variant bodies) references *folder_name*."""
    found = [False]

    def visit(path: Sdf.Path) -> None:
        if found[0]:
            return
        spec = layer.GetObjectAtPath(path)
        if not isinstance(spec, Sdf.PrimSpec):
            return
        for proxy in (spec.referenceList, spec.payloadList):
            for items in (
                proxy.prependedItems,
                proxy.appendedItems,
                proxy.addedItems,
                proxy.explicitItems,
                proxy.orderedItems,
            ):
                for arc in items:
                    if folder_name in arc.assetPath:
                        found[0] = True
                        return

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return found[0]


def add_reference(stage: Usd.Stage, scene_object: SceneObject) -> None:
    """Reference an asset under a wrapper Xform, conformed to the scene's units and up-axis."""
    add_references(stage, [scene_object])


def add_references(stage: Usd.Stage, scene_objects: list[SceneObject]) -> None:
    """Author a batch of asset references, computing conform once per unique asset."""
    conform: dict[str, tuple[float, float | None]] = {}
    for scene_object in scene_objects:
        asset_path = (
            scene_object.asset.file_path or scene_object.asset.source_id
        )
        if asset_path not in conform:
            conform[asset_path] = asset_conform(stage, asset_path)
        unit_scale, up_axis_correction = conform[asset_path]

        wrapper = stage.DefinePrim(scene_object.prim_path, "Xform")
        xformable = UsdGeom.Xformable(wrapper)

        tx, ty, tz = scene_object.translate
        rx, ry, rz = scene_object.rotate
        sx, sy, sz = scene_object.scale
        final_scale = (sx * unit_scale, sy * unit_scale, sz * unit_scale)

        xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))
        xformable.AddScaleOp().Set(Gf.Vec3f(*final_scale))

        asset_prim = stage.DefinePrim(
            f"{scene_object.prim_path}/asset", "Xform",
        )
        if up_axis_correction is not None:
            UsdGeom.Xformable(asset_prim).AddRotateXOp().Set(up_axis_correction)
        asset_prim.GetReferences().AddReference(asset_path)
