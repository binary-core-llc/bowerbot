# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""References — reading and authoring the references that place assets in a scene."""

from __future__ import annotations

from pathlib import Path

from pxr import Ar, Gf, Kind, Sdf, Usd, UsdGeom

from bowerbot.schemas import AssetFormat, SceneNamespace, SceneObject
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


def project_asset_references(project_dir: Path, assets_dir: Path) -> dict[str, set[str]]:
    """Map each project USD file to the ``assets/`` entries it references from outside itself.

    Every layer is scanned once, variant bodies and payloads included. A
    reference matches the entry its resolved path lies in (a whole
    ``assets/<entry>`` component), never by name substring. Keys are paths
    relative to *project_dir*.
    """
    assets_root = assets_dir.resolve()
    references: dict[str, set[str]] = {}
    for usd_file in sorted(project_dir.rglob("*")):
        if usd_file.suffix not in AssetFormat.layer_formats():
            continue
        layer = Sdf.Layer.FindOrOpen(str(usd_file))
        if layer is None:
            continue
        own_entry = _assets_entry(usd_file.resolve(), assets_root)
        entries = {
            entry
            for asset_path in _layer_arc_paths(layer)
            if (entry := _assets_entry(_resolve_arc(usd_file, asset_path), assets_root))
            and entry != own_entry
        }
        if entries:
            references[str(usd_file.relative_to(project_dir))] = entries
    return references


def files_referencing(references: dict[str, set[str]], entry: str) -> list[str]:
    """The project files (relative paths, sorted) that reference the ``assets/`` *entry*."""
    return sorted(file for file, entries in references.items() if entry in entries)


def assets_used_from(
    references: dict[str, set[str]], root_file: str, assets_prefix: str,
) -> set[str]:
    """Entries *root_file* uses, directly or through the assets it uses (nested contents)."""
    used: set[str] = set()
    frontier = set(references.get(root_file, set()))
    while frontier:
        entry = frontier.pop()
        used.add(entry)
        folder = f"{assets_prefix}/{entry}/"
        for file, entries in references.items():
            if file.startswith(folder):
                frontier |= entries - used
    return used


def _layer_arc_paths(layer: Sdf.Layer) -> list[str]:
    """Every reference and payload asset path authored in *layer*, variant bodies included."""
    paths: list[str] = []

    def visit(path: Sdf.Path) -> None:
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
                paths.extend(arc.assetPath for arc in items if arc.assetPath)

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return paths


def _resolve_arc(layer_file: Path, asset_path: str) -> Path:
    """The file an arc's asset path points at, resolved against its layer's folder."""
    outer, _ = Ar.SplitPackageRelativePathOuter(asset_path)
    target = Path(outer)
    return target if target.is_absolute() else (layer_file.parent / target).resolve()


def _assets_entry(path: Path, assets_root: Path) -> str | None:
    """The ``assets/`` entry (folder or .usdz) *path* lies in, or ``None``."""
    if not path.is_relative_to(assets_root) or path == assets_root:
        return None
    return path.relative_to(assets_root).parts[0]


def add_reference(stage: Usd.Stage, scene_object: SceneObject) -> None:
    """Reference an asset under a wrapper Xform, conformed to the scene's units and up-axis."""
    add_references(stage, [scene_object])


def add_references(stage: Usd.Stage, scene_objects: list[SceneObject]) -> None:
    """Author a batch of asset references, computing conform once per unique asset.

    The wrapper places the asset (translate, rotate, scale as asked); its
    ``asset`` child conforms it (unit scale and up-axis correction) and carries
    the reference, so each reference keeps its own conform.
    """
    conform: dict[str, tuple[float, float | None]] = {}
    for scene_object in scene_objects:
        asset_path = (
            scene_object.asset.file_path or scene_object.asset.source_id
        )
        if asset_path not in conform:
            conform[asset_path] = asset_conform(stage, asset_path)
        unit_scale, up_axis_correction = conform[asset_path]

        wrapper = stage.DefinePrim(scene_object.prim_path, "Xform")
        join_model_hierarchy(stage, scene_object.prim_path)
        xformable = UsdGeom.Xformable(wrapper)
        xformable.AddTranslateOp().Set(Gf.Vec3d(*scene_object.translate))
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(*scene_object.rotate))
        xformable.AddScaleOp().Set(Gf.Vec3f(*scene_object.scale))

        asset_prim = stage.DefinePrim(
            f"{scene_object.prim_path}/{SceneNamespace.ASSET_CHILD}", "Xform",
        )
        author_conform(asset_prim, unit_scale, up_axis_correction)
        asset_prim.GetReferences().AddReference(asset_path)


def join_model_hierarchy(stage: Usd.Stage, prim_path: str) -> None:
    """Make *prim_path* and every ancestor under the scene root a ``group`` model.

    A placed asset (a component) is a model only when every prim above it is a
    group or assembly; groups, wrappers and scatter prims carry no geometry of
    their own, so they are groups. An ancestor that already has a kind keeps it.
    """
    path = Sdf.Path(prim_path)
    while path.pathElementCount > 1:
        model = Usd.ModelAPI(stage.GetPrimAtPath(path))
        if not model.GetKind():
            model.SetKind(Kind.Tokens.group)
        path = path.GetParentPath()


def author_conform(prim: Usd.Prim, unit_scale: float, correction: float | None) -> None:
    """Author the ops conforming a referenced asset to its parent: up-axis turn, then units.

    Replaces any ops already authored at the edit target (a re-authored variant).
    """
    xformable = UsdGeom.Xformable(prim)
    if xformable.GetOrderedXformOps():
        xformable.ClearXformOpOrder()
    if correction is not None:
        xformable.AddRotateXOp().Set(correction)
    if unit_scale != 1.0:
        xformable.AddScaleOp().Set(Gf.Vec3f(unit_scale, unit_scale, unit_scale))
