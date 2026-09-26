# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD stage primitives — open, edit, query an open ``Usd.Stage``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pxr import Kind, Sdf, Usd, UsdGeom, UsdShade, UsdUtils

from bowerbot.schemas import AssetFormat
from bowerbot.utils.core.bounds import bbox_cache, world_bounds
from bowerbot.utils.core.naming import safe_file_name

# ── Open / save ──


def create_empty_scene(
    path: str | Path,
    *,
    up_axis: str = "Y",
    meters_per_unit: float = 1.0,
) -> None:
    """Create a single ``scene.usda`` at *path* if it does not exist."""
    path = Path(path)
    if path.exists():
        return

    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    UsdGeom.SetStageUpAxis(
        stage,
        UsdGeom.Tokens.z if str(up_axis).upper() == "Z" else UsdGeom.Tokens.y,
    )
    root = stage.DefinePrim("/Scene", "Xform")
    stage.SetDefaultPrim(root)
    Usd.ModelAPI(root).SetKind(Kind.Tokens.assembly)
    stage.Save()


def create_stage(path: str | Path) -> Usd.Stage:
    """Create the scene at *path* (if missing) and return the open stage."""
    create_empty_scene(path)
    return open_stage(path)


def open_stage(path: str | Path) -> Usd.Stage:
    """Open a stage with the default (root-layer) edit target."""
    return Usd.Stage.Open(str(path))


def save_scene_snapshot(
    scene_path: Path, name: str, *, force: bool = False,
) -> Path:
    """Flatten the composed scene into a named, self-contained snapshot file."""
    scene_path = Path(scene_path)
    safe = safe_file_name(name)
    if not safe:
        raise ValueError(
            f"Snapshot name {name!r} is empty after sanitization. "
            "Use alphanumeric characters, underscore, or hyphen.",
        )
    snapshot_path = scene_path.parent / f"{safe}.usda"
    if snapshot_path.resolve() == scene_path.resolve():
        raise ValueError(
            f"Snapshot name {name!r} collides with scene.usda. "
            "Pick a different name.",
        )
    if snapshot_path.exists() and not force:
        raise ValueError(
            f"{snapshot_path.name} already exists. Re-run with force=true "
            "to overwrite.",
        )

    stage = Usd.Stage.Open(str(scene_path))
    if stage is None:
        raise ValueError(f"Cannot open scene at {scene_path}")

    composed_default = stage.GetDefaultPrim()
    if not composed_default or not composed_default.IsValid():
        raise RuntimeError(
            f"Composed stage at {scene_path} has no defaultPrim; "
            "refusing to snapshot to avoid losing scene content.",
        )
    default_name = composed_default.GetName()

    flattened = UsdUtils.FlattenLayerStack(stage)
    if flattened is None:
        raise RuntimeError(f"Failed to flatten layer stack for {scene_path}")
    if not flattened.defaultPrim:
        flattened.defaultPrim = default_name
    if flattened.GetPrimAtPath(f"/{default_name}") is None:
        raise RuntimeError(
            f"Flattened layer has no /{default_name} prim; refusing to "
            "write an empty snapshot.",
        )

    if snapshot_path.exists():
        snapshot_layer = Sdf.Layer.FindOrOpen(str(snapshot_path))
        if snapshot_layer is None:
            raise RuntimeError(f"Cannot open {snapshot_path}")
        snapshot_layer.Clear()
    else:
        snapshot_layer = Sdf.Layer.CreateNew(str(snapshot_path))

    snapshot_layer.TransferContent(flattened)
    snapshot_layer.subLayerPaths.clear()
    _strip_dcc_artifacts(snapshot_layer)
    snapshot_layer.Save()
    return snapshot_path


def list_scene_snapshots(scene_path: Path) -> list[dict[str, object]]:
    """List every snapshot .usda file alongside scene.usda."""
    scene_path = Path(scene_path)
    scene_dir = scene_path.parent
    if not scene_dir.is_dir():
        return []
    entries: list[dict[str, object]] = []
    for entry in sorted(scene_dir.iterdir()):
        if not entry.is_file() or entry.suffix != AssetFormat.USDA:
            continue
        if entry.resolve() == scene_path.resolve():
            continue
        entries.append({
            "name": entry.stem,
            "path": str(entry),
            "size_bytes": entry.stat().st_size,
        })
    return entries


def delete_scene_snapshot(scene_path: Path, name: str) -> Path:
    """Delete a named snapshot file alongside scene.usda."""
    scene_path = Path(scene_path)
    safe = safe_file_name(name)
    if not safe:
        raise ValueError(f"Invalid snapshot name: {name!r}")
    snapshot_path = scene_path.parent / f"{safe}.usda"
    if snapshot_path.resolve() == scene_path.resolve():
        raise ValueError("Refusing to delete scene.usda.")
    if not snapshot_path.exists():
        raise ValueError(f"Snapshot not found: {snapshot_path.name}")
    cached = Sdf.Layer.FindOrOpen(str(snapshot_path))
    if cached is not None:
        cached.Clear()
    snapshot_path.unlink()
    return snapshot_path


def _strip_dcc_artifacts(layer: Sdf.Layer) -> None:
    """Drop layer scratch metadata and root prims outside the default namespace."""
    layer.customLayerData = {}
    default = layer.defaultPrim
    if not default:
        return
    edit = Sdf.BatchNamespaceEdit()
    removed_any = False
    for spec in list(layer.rootPrims):
        if spec.name != default:
            edit.Add(spec.path, Sdf.Path.emptyPath)
            removed_any = True
    if removed_any:
        layer.Apply(edit)


def save_stage(stage: Usd.Stage) -> None:
    """Save the stage to its root layer."""
    stage.Save()


# ── Transforms / namespace edits ──


def rename_prim(stage: Usd.Stage, old_path: str, new_path: str) -> bool:
    """Rename/move a prim. Caller should reopen the stage afterwards."""
    old_prim = stage.GetPrimAtPath(old_path)
    if not old_prim.IsValid():
        msg = f"Prim not found: {old_path}"
        raise ValueError(msg)

    parent_path = str(Sdf.Path(new_path).GetParentPath())
    if parent_path and parent_path != "/":
        parent_prim = stage.GetPrimAtPath(parent_path)
        if not parent_prim.IsValid():
            stage.DefinePrim(parent_path, "Xform")

    edit = Sdf.BatchNamespaceEdit()
    edit.Add(old_path, new_path)
    success: bool = stage.GetRootLayer().Apply(edit)
    if success:
        rename_variant_overs(stage.GetRootLayer(), old_path, new_path)
        stage.Save()
    return success


def rename_variant_overs(
    layer: Sdf.Layer, old_prim_path: str, new_prim_path: str,
) -> bool:
    """Relabel variant-body specs from *old_prim_path* to *new_prim_path*."""
    old = Sdf.Path(old_prim_path)
    new = Sdf.Path(new_prim_path)
    if not old.IsAbsolutePath() or not new.IsAbsolutePath():
        return False
    if old.GetParentPath() != new.GetParentPath():
        return False

    touched = False
    ancestor = old.GetParentPath()
    while ancestor != Sdf.Path.absoluteRootPath and ancestor != Sdf.Path.emptyPath:
        ancestor_spec = layer.GetPrimAtPath(ancestor)
        if ancestor_spec is None:
            ancestor = ancestor.GetParentPath()
            continue
        names = str(old.MakeRelativePath(ancestor)).split("/")
        for vset_name in list(ancestor_spec.variantSets.keys()):
            vset_spec = ancestor_spec.variantSets[vset_name]
            for variant_name in list(vset_spec.variants.keys()):
                inner_prim = vset_spec.variants[variant_name].primSpec
                if inner_prim is None:
                    continue
                if _rename_descendant_spec(inner_prim, names, new.name):
                    touched = True
        ancestor = ancestor.GetParentPath()

    if touched:
        layer.Save()
    return touched


def _rename_descendant_spec(
    root_spec: Sdf.PrimSpec, name_chain: list[str], new_leaf_name: str,
) -> bool:
    """Rename the descendant prim spec at *name_chain* under *root_spec* to *new_leaf_name*."""
    cursor = root_spec
    for i, name in enumerate(name_chain):
        if cursor is None or name not in cursor.nameChildren:
            return False
        if i == len(name_chain) - 1:
            child_spec = cursor.nameChildren[name]
            child_spec.name = new_leaf_name
            return True
        cursor = cursor.nameChildren[name]
    return False


# ── Inspection ──


def list_prim_children(stage: Usd.Stage, prim_path: str) -> list[dict[str, Any]]:
    """Return every bindable Gprim at or under *prim_path*."""
    root_prim = stage.GetPrimAtPath(prim_path)
    if not root_prim.IsValid():
        return []

    cache = bbox_cache()

    results: list[dict[str, Any]] = []
    for prim in Usd.PrimRange(root_prim):
        if not prim.IsA(UsdGeom.Gprim):
            continue
        bound_mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        type_name = prim.GetTypeName()
        results.append({
            "prim_path": str(prim.GetPath()),
            "name": prim.GetName(),
            "type": type_name or "Xform",
            "is_mesh": type_name == "Mesh",
            "is_bindable": True,
            "current_material": str(bound_mat.GetPath()) if bound_mat else None,
            "bounds": world_bounds(prim, cache),
        })
    return results
