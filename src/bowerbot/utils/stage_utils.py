# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""USD stage primitives — open, edit, query an open ``Usd.Stage``."""

from __future__ import annotations

from pathlib import Path

from pxr import Kind, Sdf, Sdr, Usd, UsdGeom, UsdShade, UsdUtils

from bowerbot.schemas import AssetFormat
from bowerbot.utils.core.bounds import bbox_cache, world_bounds
from bowerbot.utils.core.naming import safe_file_name
from bowerbot.utils.core.values import infer_sdf_type, json_to_usd, usd_to_json

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
            "value": usd_to_json(attr.Get()),
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
    converted = json_to_usd(value, type_name)
    try:
        attr.Set(converted)
    except (TypeError, RuntimeError):
        msg = (
            f"value {value!r} does not match {attribute_name}'s "
            f"declared type {type_name}."
        )
        raise ValueError(msg) from None


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

    inferred = infer_sdf_type(value)
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

    cache = bbox_cache()

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
            "bounds": world_bounds(prim, cache),
        })
    return results
