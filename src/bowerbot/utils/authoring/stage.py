# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The project's scene.usda: create it, open and save it, and keep named snapshots of it."""

from __future__ import annotations

import os
from pathlib import Path

from pxr import Kind
from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdUtils

from bowerbot.utils import authoring
from bowerbot.utils import usd

# ── Creating, opening and saving the scene ──


def create_empty_scene(
    path: str | Path,
    *,
    up_axis: str,
    meters_per_unit: float,
) -> None:
    """Create a single ``scene.usda`` at *path* if it does not exist."""
    path = Path(path)
    if path.exists():
        return

    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    UsdGeom.SetStageUpAxis(stage, usd.metrics.up_axis_token(up_axis))
    root = stage.DefinePrim("/Scene", "Xform")
    stage.SetDefaultPrim(root)
    Usd.ModelAPI(root).SetKind(Kind.Tokens.assembly)
    stage.Save()


def create_stage(
    path: str | Path, *, up_axis: str, meters_per_unit: float,
) -> Usd.Stage:
    """Create the scene at *path* (if missing) and return the open stage."""
    create_empty_scene(path, up_axis=up_axis, meters_per_unit=meters_per_unit)
    return open_stage(path)


def open_stage(path: str | Path) -> Usd.Stage:
    """Open a stage with the default (root-layer) edit target."""
    return Usd.Stage.Open(str(path))


def save_stage(stage: Usd.Stage) -> None:
    """Save the stage to its root layer."""
    stage.Save()


# ── Snapshots ──


def save_scene_snapshot(
    scene_path: Path, name: str, *, force: bool = False,
) -> Path:
    """Flatten the composed scene into a named, self-contained snapshot file."""
    scene_path = Path(scene_path)
    safe = authoring.naming.safe_file_name(name)
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

    flattened = UsdUtils.FlattenLayerStack(
        stage, lambda layer, path: _relative_to(scene_path.parent, layer, path),
    )
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
        if not entry.is_file() or entry.suffix != ".usda":
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
    safe = authoring.naming.safe_file_name(name)
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


# ── Helpers ──


def _relative_to(folder: Path, layer: Sdf.Layer, asset_path: str) -> str:
    """*asset_path* as written in *layer*, re-expressed relative to *folder*."""
    if not asset_path or os.path.isabs(asset_path):
        return asset_path
    layer_dir = Path(layer.realPath).parent
    if layer_dir == folder:
        return asset_path
    return os.path.relpath(layer_dir / asset_path, folder)


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
