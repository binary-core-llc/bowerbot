# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""References — reading and authoring the references that place assets in a scene."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pxr import Ar, Gf, Kind, Sdf, Usd, UsdGeom

from bowerbot.schemas import (
    AssetFormat,
    ASWFLayerNames,
    SceneNamespace,
    SceneObject,
    TextureRules,
)
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


def is_placement(stage: Usd.Stage, prim_path: str | Sdf.Path) -> bool:
    """Whether *prim_path* is a placement: a wrapper whose ``asset`` child holds the asset."""
    path = Sdf.Path(prim_path)
    prim = stage.GetPrimAtPath(path)
    return bool(
        path.name != SceneNamespace.ASSET_CHILD
        and prim.IsValid()
        and prim.GetChild(SceneNamespace.ASSET_CHILD).IsValid(),
    )


def enclosing_placement(stage: Usd.Stage, prim_path: str) -> str | None:
    """The deepest placement whose ``asset`` child is *prim_path* or holds it, else ``None``."""
    path = Sdf.Path(prim_path)
    for prefix in reversed(path.GetPrefixes()[:-1]):
        inner = prefix.AppendChild(SceneNamespace.ASSET_CHILD)
        if path.HasPrefix(inner) and is_placement(stage, prefix):
            return str(prefix)
    return None


def placement_of(stage: Usd.Stage, prim_path: str) -> str:
    """The placement *prim_path* names: the placement itself or its ``asset`` child.

    A part inside a placement, and a prim outside every placement, are refused
    with the path to pass instead.
    """
    if not stage.GetPrimAtPath(prim_path).IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)
    if is_placement(stage, prim_path):
        return prim_path
    owner = enclosing_placement(stage, prim_path)
    if owner is not None and prim_path == f"{owner}/{SceneNamespace.ASSET_CHILD}":
        return owner
    if owner is not None:
        msg = (
            f"{prim_path} is inside the placement {owner}; pass the placement "
            f"itself ({owner})."
        )
        raise ValueError(msg)
    msg = (
        f"{prim_path} is not a placement; pass one as list_scene reports it "
        f"(/Scene/<Group>/<Name>)."
    )
    raise ValueError(msg)


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


def files_named_by(layer_files: Iterable[Path]) -> dict[Path, list[Path]]:
    """Each file the layers name (resolved) -> the layers naming it.

    A layer names a file through a sublayer, a reference or payload, or an
    asset-valued attribute (default or time sample), variant bodies included.
    A ``<UDIM>`` path names every tile on disk.
    """
    named: dict[Path, list[Path]] = {}
    for layer_file in layer_files:
        layer = Sdf.Layer.FindOrOpen(str(layer_file))
        if layer is None:
            continue
        paths = [
            *layer.subLayerPaths, *_layer_arc_paths(layer), *_layer_attribute_asset_paths(layer),
        ]
        for asset_path in paths:
            target = _resolve_arc(layer_file, asset_path)
            udim = TextureRules.UDIM_TOKEN
            tiles = (
                target.parent.glob(target.name.replace(udim, TextureRules.UDIM_TILE_GLOB))
                if udim in target.name else (target,)
            )
            for tile in tiles:
                named.setdefault(tile.resolve(), []).append(layer_file)
    return named


def unused_files(
    folder: Path, layer_files: Iterable[Path], *, keep: Iterable[Path] = (),
) -> set[Path]:
    """Files under *folder* (resolved) that none of *layer_files* names, *keep* aside."""
    if not folder.is_dir():
        return set()
    named = files_named_by(layer_files)
    kept = {path.resolve() for path in keep}
    return {
        path.resolve()
        for path in folder.rglob("*")
        if path.is_file() and not path.name.startswith(".")
        and path.resolve() not in named and path.resolve() not in kept
    }


def layer_files(folder: Path) -> list[Path]:
    """Every USD layer file under *folder*, sorted."""
    return sorted(
        path for path in folder.rglob("*")
        if path.is_file() and path.suffix in AssetFormat.layer_formats()
    )


def project_layers(project_dir: Path) -> list[Path]:
    """The project's own scene layers: ``scene.usda`` and its snapshots."""
    return sorted(
        path for path in project_dir.iterdir()
        if path.is_file() and path.suffix in AssetFormat.layer_formats()
    )


def unused_scene_textures(project_dir: Path) -> set[Path]:
    """Files in the project's ``textures/`` that neither the scene nor a snapshot names."""
    return unused_files(project_dir / ASWFLayerNames.TEXTURES, project_layers(project_dir))


def newly_unused(project_dir: Path, before: set[Path], after: set[Path]) -> list[str]:
    """What an edit left unused: *after* minus *before*, relative to the project, sorted."""
    root = project_dir.resolve()
    return sorted(path.relative_to(root).as_posix() for path in after - before)


def unused_files_note(unused: list[str]) -> str:
    """The sentence a result message adds for files an edit left unused (empty if none)."""
    if not unused:
        return ""
    return f" No longer used, kept in the project: {', '.join(unused)}."


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
        if isinstance(spec, Sdf.VariantSpec):
            spec = spec.primSpec  # arcs authored on the variant itself
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


def _layer_attribute_asset_paths(layer: Sdf.Layer) -> list[str]:
    """Every asset path an asset-valued attribute in *layer* authors, variant bodies included."""
    asset_types = {Sdf.ValueTypeNames.Asset, Sdf.ValueTypeNames.AssetArray}
    paths: list[str] = []

    def visit(path: Sdf.Path) -> None:
        if not path.IsPropertyPath():
            return
        spec = layer.GetAttributeAtPath(path)
        if spec is None or spec.typeName not in asset_types:
            return
        values = [spec.default] if spec.HasDefaultValue() else []
        values += [layer.QueryTimeSample(path, t) for t in layer.ListTimeSamplesForPath(path)]
        for value in values:
            items = value if isinstance(value, Sdf.AssetPathArray) else [value]
            paths.extend(
                item.path for item in items if isinstance(item, Sdf.AssetPath) and item.path
            )

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
