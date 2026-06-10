# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD stage primitives — open, edit, query an open ``Usd.Stage``."""

from __future__ import annotations

import os
from pathlib import Path

from pxr import Gf, Kind, Sdf, Sdr, Usd, UsdGeom, UsdShade, UsdUtils

from bowerbot.schemas import SceneObject
from bowerbot.utils.naming_utils import safe_file_name

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
    for usd_file in project_dir.rglob("*"):
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
            "value": _usd_value_to_json(attr.Get()),
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
            prune_empty_overrides(layer, prim_path)
        return

    attr = prim.GetAttribute(attribute_name)
    if not attr.IsValid():
        attr = _create_attribute_on_demand(
            prim, attribute_name, value, expected_type,
        )

    type_name = expected_type if expected_type is not None else attr.GetTypeName()
    converted = _json_to_usd_value(value, type_name)
    attr.Set(converted)


def prune_empty_overrides(layer: Sdf.Layer, prim_path: str) -> None:
    """Walk up from *prim_path*, removing any fully-empty SpecifierOver spec."""
    path = Sdf.Path(prim_path)
    while path != Sdf.Path.absoluteRootPath:
        spec = layer.GetPrimAtPath(path)
        if spec is None:
            return
        if not _is_empty_override(spec):
            return
        parent_path = path.GetParentPath()
        edit = Sdf.BatchNamespaceEdit()
        edit.Add(path, Sdf.Path.emptyPath)
        if not layer.Apply(edit):
            return
        path = parent_path


_INTRINSIC_PRIM_INFO_KEYS = frozenset({"specifier", "typeName"})


def _is_empty_override(spec: Sdf.PrimSpec) -> bool:
    """An ``over`` with no authored content; safe to delete."""
    if spec.specifier != Sdf.SpecifierOver:
        return False
    if spec.typeName:
        return False
    if len(spec.attributes) or len(spec.relationships) or len(spec.nameChildren):
        return False
    if len(spec.variantSets) or len(spec.variantSelections):
        return False
    for arc in (
        spec.referenceList, spec.payloadList,
        spec.inheritPathList, spec.specializesList,
    ):
        if (
            arc.prependedItems or arc.appendedItems
            or arc.addedItems or arc.explicitItems
            or arc.deletedItems
        ):
            return False
    authored = set(spec.ListInfoKeys()) - _INTRINSIC_PRIM_INFO_KEYS
    return not authored


def _create_attribute_on_demand(
    prim: Usd.Prim,
    attribute_name: str,
    value: object,
    expected_type: Sdf.ValueTypeName | None = None,
) -> Usd.Attribute:
    """Create an attribute; xformOp:* routes through Xformable so xformOpOrder updates."""
    if attribute_name.startswith("xformOp:") and prim.IsA(UsdGeom.Xformable):
        op = _add_xform_op(UsdGeom.Xformable(prim), attribute_name)
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

    inferred = _infer_sdf_type(value)
    return prim.CreateAttribute(attribute_name, inferred, custom=False)


def _add_xform_op(
    xformable: UsdGeom.Xformable, attribute_name: str,
) -> UsdGeom.XformOp | None:
    """Return the xform op for *attribute_name*, adding to xformOpOrder if missing."""
    suffix = attribute_name[len("xformOp:"):]
    base, _, namespace = suffix.partition(":")
    spec = _XFORM_OP_SPECS.get(base)
    if spec is None:
        return None
    op_type, value_type = spec
    current_order = xformable.GetXformOpOrderAttr().Get() or ()
    if attribute_name in current_order:
        attr = xformable.GetPrim().CreateAttribute(
            attribute_name, value_type, custom=False,
        )
        return UsdGeom.XformOp(attr)
    return xformable.AddXformOp(op_type, opSuffix=namespace or "")


_XFORM_OP_SPECS: dict[str, tuple[object, Sdf.ValueTypeName]] = {
    "translate": (UsdGeom.XformOp.TypeTranslate, Sdf.ValueTypeNames.Double3),
    "rotateX": (UsdGeom.XformOp.TypeRotateX, Sdf.ValueTypeNames.Float),
    "rotateY": (UsdGeom.XformOp.TypeRotateY, Sdf.ValueTypeNames.Float),
    "rotateZ": (UsdGeom.XformOp.TypeRotateZ, Sdf.ValueTypeNames.Float),
    "rotateXYZ": (UsdGeom.XformOp.TypeRotateXYZ, Sdf.ValueTypeNames.Float3),
    "rotateXZY": (UsdGeom.XformOp.TypeRotateXZY, Sdf.ValueTypeNames.Float3),
    "rotateYXZ": (UsdGeom.XformOp.TypeRotateYXZ, Sdf.ValueTypeNames.Float3),
    "rotateYZX": (UsdGeom.XformOp.TypeRotateYZX, Sdf.ValueTypeNames.Float3),
    "rotateZXY": (UsdGeom.XformOp.TypeRotateZXY, Sdf.ValueTypeNames.Float3),
    "rotateZYX": (UsdGeom.XformOp.TypeRotateZYX, Sdf.ValueTypeNames.Float3),
    "scale": (UsdGeom.XformOp.TypeScale, Sdf.ValueTypeNames.Float3),
    "orient": (UsdGeom.XformOp.TypeOrient, Sdf.ValueTypeNames.Quatf),
    "transform": (UsdGeom.XformOp.TypeTransform, Sdf.ValueTypeNames.Matrix4d),
}


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


def _infer_sdf_type(value: object) -> Sdf.ValueTypeName:
    """Guess an Sdf type from a JSON-shaped value."""
    if isinstance(value, bool):
        return Sdf.ValueTypeNames.Bool
    if isinstance(value, int):
        return Sdf.ValueTypeNames.Int
    if isinstance(value, float):
        return Sdf.ValueTypeNames.Float
    if isinstance(value, str):
        return Sdf.ValueTypeNames.Token
    if isinstance(value, list | tuple):
        n = len(value)
        if n == 2:
            return Sdf.ValueTypeNames.Float2
        if n == 3:
            return Sdf.ValueTypeNames.Color3f
        if n == 4:
            return Sdf.ValueTypeNames.Color4f
    return Sdf.ValueTypeNames.Float


def _usd_value_to_json(value: object) -> object:
    """Render a USD-typed value back as a JSON-friendly Python value."""
    if value is None:
        return None
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Sdf.AssetPath):
        return value.path or str(value)
    # Gf.Vec3f / Vec3d have no __iter__ but list() works via __getitem__.
    if hasattr(value, "__len__") and not isinstance(value, bytes):
        items = list(value)
        if items and hasattr(items[0], "__len__") and not isinstance(
            items[0], str | bytes,
        ):
            return [_usd_value_to_json(v) for v in items]
        try:
            return [float(c) for c in items]
        except (TypeError, ValueError):
            return [str(c) for c in items]
    return str(value)


def _json_to_usd_value(value: object, type_name: Sdf.ValueTypeName) -> object:
    """Cast a JSON-shaped value to match a USD attribute's declared type."""
    raw = str(type_name).lower()

    if raw in ("float", "half", "double"):
        return float(value)
    if raw in ("int", "uchar", "uint", "int64", "uint64"):
        return int(value)
    if raw == "bool":
        return bool(value)
    if raw in ("token", "string"):
        return str(value)
    if raw == "asset":
        return Sdf.AssetPath(str(value))
    if raw.startswith(("color3", "float3", "vector3f", "normal3f", "point3f")):
        return Gf.Vec3f(*value)
    if raw.startswith(("double3", "vector3d", "normal3d", "point3d")):
        return Gf.Vec3d(*value)
    if raw.startswith(("color4", "float4")):
        return Gf.Vec4f(*value)
    if raw.startswith("float2"):
        return Gf.Vec2f(*value)
    return value


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


# ── References ──


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
            conform[asset_path] = _asset_conform(stage, asset_path)
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


def unique_prim_path(stage: Usd.Stage, parent: str, base_name: str) -> str:
    """Return ``<parent>/<base_name>`` or the next free ``<parent>/<base_name>_NN``."""
    direct = f"{parent}/{base_name}"
    if not stage.GetPrimAtPath(direct).IsValid():
        return direct
    n = 2
    while True:
        candidate = f"{parent}/{base_name}_{n:02d}"
        if not stage.GetPrimAtPath(candidate).IsValid():
            return candidate
        n += 1




# ── Transforms / namespace edits ──


def read_translate_and_rotate_y(prim: Usd.Prim) -> tuple[float, float, float, float]:
    """Return ``(tx, ty, tz, ry)`` resolved on ``prim``; missing ops read as 0."""
    xformable = UsdGeom.Xformable(prim)
    tx = ty = tz = ry = 0.0
    for op in xformable.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            value = op.Get()
            if value is not None:
                tx, ty, tz = float(value[0]), float(value[1]), float(value[2])
        elif op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            value = op.Get()
            if value is not None:
                ry = float(value[1])
    return tx, ty, tz, ry


def set_transform(
    stage: Usd.Stage,
    prim_path: str,
    translate: tuple[float, float, float],
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> None:
    """Update translate/rotate on an existing prim in place."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)

    xformable = UsdGeom.Xformable(prim)
    tx, ty, tz = translate
    rx, ry, rz = rotate

    found_translate = False
    found_rotate = False
    for op in xformable.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            if op.GetOpName() == "xformOp:translate":
                op.Set(Gf.Vec3d(tx, ty, tz))
                found_translate = True
        elif op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            op.Set(Gf.Vec3f(rx, ry, rz))
            found_rotate = True

    if not found_translate:
        xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))
    if not found_rotate and any(v != 0.0 for v in (rx, ry, rz)):
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))


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
    success = stage.GetRootLayer().Apply(edit)
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


def remove_prim(stage: Usd.Stage, prim_path: str) -> bool:
    """Remove a prim, clean any orphan variant body specs, and save on success."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        msg = f"Prim not found: {prim_path}"
        raise ValueError(msg)

    removed = stage.RemovePrim(prim_path)
    if removed:
        clear_orphan_variant_overs(stage.GetRootLayer(), prim_path)
        stage.Save()
    return removed


def clear_orphan_variant_overs(
    layer: Sdf.Layer, removed_prim_path: str,
) -> bool:
    """Clear orphan variant-body specs at *removed_prim_path*, cascading empties."""
    target = Sdf.Path(removed_prim_path)
    if not target.IsAbsolutePath() or target == Sdf.Path.absoluteRootPath:
        return False

    touched = False
    ancestor = target.GetParentPath()
    while ancestor != Sdf.Path.absoluteRootPath and ancestor != Sdf.Path.emptyPath:
        ancestor_spec = layer.GetPrimAtPath(ancestor)
        if ancestor_spec is None:
            ancestor = ancestor.GetParentPath()
            continue
        names = str(target.MakeRelativePath(ancestor)).split("/")
        for vset_name in list(ancestor_spec.variantSets.keys()):
            vset_spec = ancestor_spec.variantSets[vset_name]
            for variant_name in list(vset_spec.variants.keys()):
                variant_spec = vset_spec.variants[variant_name]
                inner_prim = variant_spec.primSpec
                if inner_prim is None:
                    continue
                if _delete_descendant_spec(inner_prim, names):
                    touched = True
                if _is_variant_body_empty(variant_spec):
                    vset_spec.RemoveVariant(variant_spec)
                    touched = True
            if len(vset_spec.variants) == 0:
                del ancestor_spec.variantSets[vset_name]
                name_list = ancestor_spec.variantSetNameList
                for items in (
                    name_list.prependedItems,
                    name_list.appendedItems,
                    name_list.addedItems,
                    name_list.explicitItems,
                    name_list.orderedItems,
                ):
                    if vset_name in items:
                        items.remove(vset_name)
                if vset_name in name_list.deletedItems:
                    name_list.deletedItems.remove(vset_name)
                if vset_name in ancestor_spec.variantSelections:
                    del ancestor_spec.variantSelections[vset_name]
                touched = True
        ancestor = ancestor.GetParentPath()

    if touched:
        layer.Save()
    return touched


def _delete_descendant_spec(
    root_spec: Sdf.PrimSpec, name_chain: list[str],
) -> bool:
    """Delete the descendant at *name_chain*; prune empty intermediates back up to *root_spec*."""
    cursor = root_spec
    chain: list[tuple[Sdf.PrimSpec, str]] = []
    for name in name_chain[:-1]:
        if cursor is None or name not in cursor.nameChildren:
            return False
        chain.append((cursor, name))
        cursor = cursor.nameChildren[name]
    leaf_name = name_chain[-1]
    if cursor is None or leaf_name not in cursor.nameChildren:
        return False
    del cursor.nameChildren[leaf_name]
    for parent_spec, child_name in reversed(chain):
        child_spec = parent_spec.nameChildren.get(child_name)
        if child_spec is None or not _is_empty_intermediate(child_spec):
            break
        del parent_spec.nameChildren[child_name]
    return True


def _is_empty_intermediate(spec: Sdf.PrimSpec) -> bool:
    """Whether a prim spec carries no opinions and no children (safe to prune)."""
    if len(spec.nameChildren) or len(spec.attributes) or len(spec.relationships):
        return False
    info = set(spec.ListInfoKeys()) - {"specifier", "typeName"}
    return not info


def _is_variant_body_empty(variant_spec: Sdf.VariantSpec) -> bool:
    """Whether a variant body has no authored opinions left."""
    inner = variant_spec.primSpec
    if inner is None:
        return True
    if len(inner.nameChildren) or len(inner.attributes) or len(inner.relationships):
        return False
    info = set(inner.ListInfoKeys()) - {"specifier", "typeName"}
    return not info


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
            "bounds": world_bounds(prim, bbox_cache),
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


def update_translate_op(prim: Usd.Prim, value: Gf.Vec3d) -> None:
    """Update the first translate xform op on *prim*."""
    xformable = UsdGeom.Xformable(prim)
    for op in xformable.GetOrderedXformOps():
        if op.GetOpName() == "xformOp:translate":
            op.Set(value)
            return


def update_rotate_op(prim: Usd.Prim, value: Gf.Vec3f) -> None:
    """Update the first rotateXYZ xform op on *prim*."""
    xformable = UsdGeom.Xformable(prim)
    for op in xformable.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            op.Set(value)
            return


def _asset_conform(stage: Usd.Stage, asset_path: str) -> tuple[float, float | None]:
    """Return (unit scale, up-axis X-rotation or None) conforming an asset to the stage."""
    if not os.path.isabs(asset_path):
        stage_dir = os.path.dirname(stage.GetRootLayer().realPath)
        asset_path = os.path.join(stage_dir, asset_path)

    asset_stage = Usd.Stage.Open(asset_path, Usd.Stage.LoadNone)
    if asset_stage is None:
        return 1.0, None

    asset_mpu = UsdGeom.GetStageMetersPerUnit(asset_stage)
    scene_mpu = UsdGeom.GetStageMetersPerUnit(stage)
    unit_scale = 1.0 if scene_mpu == 0 else asset_mpu / scene_mpu

    asset_up = UsdGeom.GetStageUpAxis(asset_stage)
    scene_up = UsdGeom.GetStageUpAxis(stage)
    correction = None
    if asset_up == UsdGeom.Tokens.y and scene_up == UsdGeom.Tokens.z:
        correction = 90.0
    elif asset_up == UsdGeom.Tokens.z and scene_up == UsdGeom.Tokens.y:
        correction = -90.0
    return unit_scale, correction


def extract_position(prim: Usd.Prim) -> dict[str, float] | None:
    """Return the translate component of a prim's local transform."""
    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        return None
    t = xformable.GetLocalTransformation().ExtractTranslation()
    return {"x": round(t[0], 2), "y": round(t[1], 2), "z": round(t[2], 2)}


def world_bounds(
    prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache,
) -> dict | None:
    """Compute world-aligned AABB for a prim, rounded to 4 decimals."""
    rng = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
    if rng.IsEmpty():
        return None
    mn, mx = rng.GetMin(), rng.GetMax()
    return {
        "min": {"x": round(mn[0], 4), "y": round(mn[1], 4), "z": round(mn[2], 4)},
        "max": {"x": round(mx[0], 4), "y": round(mx[1], 4), "z": round(mx[2], 4)},
    }


