# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD stage primitives — open, edit, query an open ``Usd.Stage``."""

from __future__ import annotations

from pathlib import Path

from pxr import Gf
from pxr import Kind
from pxr import Sdf
from pxr import Sdr
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade
from pxr import UsdUtils

from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import usd

# ── Reference inspection ──


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


def find_asset_references(
    project_dir: Path,
    folder_name: str,
    skip_dir: Path | None = None,
) -> list[str]:
    """Scan *project_dir* for USD files referencing *folder_name* in any variant body or payload."""
    referencing: list[str] = []
    for usd_file in sorted(project_dir.rglob("*")):
        if usd_file.suffix not in (".usd", ".usda", ".usdc"):
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


def list_prim_attributes(
    stage: Usd.Stage, prim_path: str,
) -> list[dict[str, object]]:
    """Return every attribute on the prim with type, current value, authored flag."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")

    out: list[dict[str, object]] = []
    for attr in prim.GetAttributes():
        out.append({
            "name": attr.GetName(),
            "type": str(attr.GetTypeName()),
            "value": usd.values.usd_value_to_json(attr.Get()),
            "authored": attr.HasAuthoredValue(),
        })
    return out


def set_prim_attribute(
    stage: Usd.Stage,
    prim_path: str,
    attribute_name: str,
    value: object,
    *,
    expected_type: Sdf.ValueTypeName | None = None,
) -> None:
    """Author or clear an attribute opinion at the stage's current edit target.

    When *expected_type* is provided it overrides value-shape inference and
    the schema-registry lookup; callers that know the declared type from a
    separate composition (e.g. variant body authoring against an asset's
    composed stage) should pass it to avoid the wrong type being authored.
    """
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")

    if value is None:
        layer = stage.GetEditTarget().GetLayer()
        prim_spec = layer.GetPrimAtPath(prim_path)
        if prim_spec is None:
            return
        attr_spec = prim_spec.attributes.get(attribute_name)
        if attr_spec is not None:
            prim_spec.RemoveProperty(attr_spec)
            usd.namespace.prune_empty_overrides(layer, prim_path)
        return

    attr = prim.GetAttribute(attribute_name)
    if not attr.IsValid():
        attr = _create_attribute_on_demand(
            prim, attribute_name, value, expected_type,
        )

    type_name = expected_type if expected_type is not None else attr.GetTypeName()
    converted = usd.values.json_to_usd_value(value, type_name)
    try:
        attr.Set(converted)
    except (TypeError, RuntimeError):
        msg = (
            f"value {value!r} does not match {attribute_name}'s "
            f"declared type {type_name}."
        )
        raise ValueError(msg) from None


def _create_attribute_on_demand(
    prim: Usd.Prim,
    attribute_name: str,
    value: object,
    expected_type: Sdf.ValueTypeName | None = None,
) -> Usd.Attribute:
    """Create an attribute; xformOp:* routes through Xformable so xformOpOrder updates."""
    if attribute_name.startswith("xformOp:") and prim.IsA(UsdGeom.Xformable):
        op = usd.transforms.add_xform_op(UsdGeom.Xformable(prim), attribute_name)
        if op is not None:
            return op.GetAttr()

    if expected_type is not None:
        return prim.CreateAttribute(attribute_name, expected_type, custom=False)

    if attribute_name.startswith("inputs:") and prim.IsA(UsdShade.Shader):
        shader = UsdShade.Shader(prim)
        base_name = attribute_name[len("inputs:"):]
        sdr_type = _resolve_shader_input_type(shader, base_name)
        if sdr_type is not None:
            return shader.CreateInput(base_name, sdr_type).GetAttr()

    inferred = usd.values.infer_sdf_type(value)
    return prim.CreateAttribute(attribute_name, inferred, custom=False)


def _resolve_shader_input_type(
    shader: UsdShade.Shader, base_name: str,
) -> Sdf.ValueTypeName | None:
    """Look up a shader input's declared type via the Sdr registry."""
    id_attr = shader.GetIdAttr()
    info_id = id_attr.Get() if id_attr else None
    if not info_id:
        return None
    node = Sdr.Registry().GetShaderNodeByIdentifier(info_id)
    if node is None:
        return None
    sdr_input = node.GetShaderInput(base_name)
    if sdr_input is None:
        return None
    return sdr_input.GetTypeAsSdfType().GetSdfType()


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


# ── References ──


def add_reference(stage: Usd.Stage, scene_object: schemas.SceneObject) -> None:
    """Reference an asset under a wrapper Xform, conformed to the scene's units and up-axis."""
    add_references(stage, [scene_object])


def add_references(stage: Usd.Stage, scene_objects: list[schemas.SceneObject]) -> None:
    """Author a batch of asset references, computing conform once per unique asset."""
    conform: dict[str, tuple[float, float | None]] = {}
    for scene_object in scene_objects:
        asset_path = (
            scene_object.asset.file_path or scene_object.asset.source_id
        )
        if asset_path not in conform:
            conform[asset_path] = usd.metrics.asset_conform(stage, asset_path)
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


# ── Lights (scene level) ──


# ── Transforms / namespace edits ──


# ── Inspection ──


def list_prim_children(stage: Usd.Stage, prim_path: str) -> list[dict]:
    """Return every bindable Gprim at or under *prim_path*."""
    root_prim = stage.GetPrimAtPath(prim_path)
    if not root_prim.IsValid():
        return []

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_],
    )

    results: list[dict] = []
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
            "bounds": usd.bounds.world_bounds(prim, bbox_cache),
        })
    return results


def get_all_ref_paths(stage: Usd.Stage) -> set[str]:
    """Collect every reference asset path authored on the stage."""
    refs: set[str] = set()
    for prim in stage.Traverse():
        refs.update(get_prim_ref_paths(prim))
    return refs


def count_scene_refs_to_asset_dir(stage: Usd.Stage, asset_dir: Path) -> int:
    """Count how many prims in the scene reference *asset_dir*."""
    return len(find_asset_placements(stage, asset_dir))


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


def get_container_world_inverse(
    stage: Usd.Stage, container_prim_path: str,
) -> Gf.Matrix4d | None:
    """Return the inverse world transform of a container's wrapper Xform."""
    prim = stage.GetPrimAtPath(container_prim_path)
    if not prim or not prim.IsValid():
        return None

    wrapper = prim
    if prim.GetName() == "asset":
        parent = prim.GetParent()
        if parent and parent.IsValid():
            wrapper = parent

    xform_cache = UsdGeom.XformCache()
    return xform_cache.GetLocalToWorldTransform(wrapper).GetInverse()


def parse_nested_contents_path(prim_path: str) -> tuple[str, str] | None:
    """If *prim_path* is a nested-asset wrapper, return (group, prim_name)."""
    marker = "/asset/contents/"
    idx = prim_path.find(marker)
    if idx >= 0:
        suffix = prim_path[idx + len(marker):]
        parts = [p for p in suffix.split("/") if p]
        if len(parts) == 2:
            return parts[0], parts[1]
        msg = (
            f"Path {prim_path} is inside a nested asset's contents but "
            f"not at the wrapper level. Only the wrapper "
            f"(.../asset/contents/<group>/<name>) can be edited; deeper "
            f"prims live inside the referenced nested asset and editing "
            f"them at scene level would create per-instance overrides."
        )
        raise ValueError(msg)

    if "/asset/" in prim_path or prim_path.endswith("/asset"):
        msg = (
            f"Path {prim_path} is inside a referenced top-level asset. "
            f"Only the scene-level wrapper (/Scene/<Group>/<Name>) and "
            f"nested wrappers (.../asset/contents/<group>/<name>) can be "
            f"edited; everything else lives inside the referenced asset "
            f"and editing it at scene level would create per-instance "
            f"overrides."
        )
        raise ValueError(msg)

    return None


def world_to_local_point(
    stage: Usd.Stage,
    container_prim_path: str,
    x: float, y: float, z: float,
) -> tuple[float, float, float] | None:
    """Convert a world-space point into a container's local frame."""
    inv = get_container_world_inverse(stage, container_prim_path)
    if inv is None:
        return None
    local = inv.Transform(Gf.Vec3d(x, y, z))
    return float(local[0]), float(local[1]), float(local[2])


# ── Internal helpers ──


