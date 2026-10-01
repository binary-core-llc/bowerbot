# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""How the scene refers to asset folders: /Scene placements, nested assets, container frames.

A placement is a wrapper Xform under ``/Scene`` whose ``asset`` child references
an asset folder's root file. A nested asset is a wrapper inside a container
asset's ``contents.usda``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Gf
from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import usd

logger = logging.getLogger(__name__)

# ── Placing assets in the scene ──


def add_references(
    stage: Usd.Stage,
    scene_objects: list[schemas.SceneObject],
    *,
    project_mpu: float,
    project_up_axis: str,
) -> None:
    """Reference each asset under a wrapper Xform, conformed to the project's units and up axis.

    The conform is computed once per unique asset.
    """
    conform: dict[str, tuple[float, float | None]] = {}
    for scene_object in scene_objects:
        asset_path = (
            scene_object.asset.file_path or scene_object.asset.source_id
        )
        if asset_path not in conform:
            conform[asset_path] = usd.metrics.asset_conform(
                stage, asset_path,
                project_mpu=project_mpu, project_up_axis=project_up_axis,
            )
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


def scene_group_path(group: str) -> str:
    """Build the /Scene scope path for a group, sanitizing each nested segment."""
    segments = [name for seg in group.split("/") if (name := usd.naming.safe_prim_name(seg))]
    if not segments:
        msg = "a layout entry 'group' must name a non-empty scene scope."
        raise ValueError(msg)
    for segment in segments:
        if not usd.naming.is_valid_prim_name(segment):
            msg = (
                f"group segment '{segment}' is not a valid USD prim name "
                f"(it must start with a letter or underscore)."
            )
            raise ValueError(msg)
    return "/Scene/" + "/".join(segments)


def is_placement_wrapper(prim: Usd.Prim) -> bool:
    """A scene placement wrapper: an Xformable whose ``asset`` child carries a reference."""
    child = prim.GetChild("asset")
    return (
        prim.IsA(UsdGeom.Xformable)
        and child.IsValid()
        and bool(usd.references.get_prim_ref_paths(child))
    )


# ── Which placements use an asset folder ──


def find_asset_placements(stage: Usd.Stage, asset_dir: Path) -> list[str]:
    """Return scene prim paths of every wrapper-asset child referencing *asset_dir*."""
    root_path = stage.GetRootLayer().realPath
    if not root_path:
        return []
    stage_dir = Path(root_path).parent
    target_dir = asset_dir.resolve()
    placements: list[str] = []
    for prim in stage.Traverse():
        for ref_path in usd.references.get_prim_ref_paths(prim):
            resolved = (stage_dir / ref_path).resolve()
            if resolved.exists() and resolved.parent == target_dir:
                placements.append(str(prim.GetPath()))
                break
    return placements


def count_scene_refs_to_asset_dir(stage: Usd.Stage, asset_dir: Path) -> int:
    """Count how many prims in the scene reference *asset_dir*."""
    return len(find_asset_placements(stage, asset_dir))


def clear_scene_variant_selections(
    stage: Usd.Stage,
    asset_dir: Path,
    set_name: str,
    variant_name: str | None = None,
) -> int:
    """Drop ``variantSelections[set_name]`` from every placement of the asset.

    When *variant_name* is given, only drop selections whose current value
    matches it. Prunes empty over ancestors left behind on each touched
    placement. Returns the number of placements scrubbed.
    """
    placements = find_asset_placements(stage, asset_dir)
    if not placements:
        return 0
    layer = stage.GetRootLayer()
    scrubbed = 0
    for placement in placements:
        spec = layer.GetPrimAtPath(placement)
        if spec is None:
            continue
        sels = spec.variantSelections
        if set_name not in sels:
            continue
        if variant_name is not None and sels[set_name] != variant_name:
            continue
        del sels[set_name]
        scrubbed += 1
        usd.namespace.prune_empty_overrides(layer, placement)
    if scrubbed:
        layer.Save()
    return scrubbed


# ── The asset folder behind a scene prim ──


def resolve_asset_dir_for_prim(
    stage: Usd.Stage,
    prim_path: str,
) -> tuple[Path | None, str | None]:
    """Find the outer ASWF asset folder backing *prim_path* in *stage*."""
    # Resolution is rooted at stage_dir (project root) on purpose: nested
    # refs in contents.usda are authored relative to that layer
    # (../sibling_asset/...) and resolve to a nonexistent path here, so
    # they are skipped and the walk continues to the outer container's
    # scene-level reference. That is the routing target move/remove/freeze
    # need.
    stage_dir = Path(stage.GetRootLayer().realPath).parent

    def _check(prim: Usd.Prim) -> tuple[Path | None, str | None]:
        for ref_path in usd.references.get_prim_ref_paths(prim):
            resolved = (stage_dir / ref_path).resolve()
            if not resolved.exists() or not resolved.parent.is_dir():
                continue
            folder = resolved.parent
            for ext in constants.AssetFolderRules.USD_LAYER_EXTENSIONS:
                if resolved.name == f"{folder.name}{ext}":
                    return folder, str(prim.GetPath())
        return None, None

    target = stage.GetPrimAtPath(prim_path)
    if target and target.IsValid():
        result = _check(target)
        if result[0] is not None:
            return result
        for child in target.GetChildren():
            result = _check(child)
            if result[0] is not None:
                return result

    parts = prim_path.strip("/").split("/")
    for i in range(len(parts) - 1, 0, -1):
        ancestor_path = "/" + "/".join(parts[:i])
        prim = stage.GetPrimAtPath(ancestor_path)
        if not prim or not prim.IsValid():
            continue
        result = _check(prim)
        if result[0] is not None:
            return result
        for child in prim.GetChildren():
            result = _check(child)
            if result[0] is not None:
                return result

    return None, None


def require_asset_context(
    stage: Usd.Stage, prim_path: str,
) -> tuple[Path, str]:
    """Resolve the asset folder + reference prim path; raise if neither is found."""
    asset_dir, ref_prim_path = resolve_asset_dir_for_prim(stage, prim_path)
    if asset_dir is None or ref_prim_path is None:
        raise ValueError(
            f"Cannot find ASWF asset folder for {prim_path}. "
            "Operation only works on assets placed as ASWF folders (not USDZ).",
        )
    return asset_dir, ref_prim_path


def to_asset_local(prim_path: str, ref_prim_path: str) -> str:
    """Strip the scene-side reference prefix to get an asset-local path."""
    if prim_path.startswith(ref_prim_path):
        remainder = prim_path[len(ref_prim_path):]
        return remainder if remainder else "/"
    return prim_path


def normalize_asset_prim_path(
    prim_path: str, ref_prim_path: str, default_prim_name: str,
) -> str:
    """Strip the scene namespace then anchor under the asset's default prim."""
    if prim_path == ref_prim_path:
        return f"/{default_prim_name}"
    if prim_path.startswith(f"{ref_prim_path}/"):
        return authoring.asset_folder.to_layer_local_path(
            prim_path[len(ref_prim_path):], default_prim_name,
        )
    return authoring.asset_folder.to_layer_local_path(prim_path, default_prim_name)


# ── Nested assets in contents.usda ──


def compute_ref_asset_path(
    relative_asset_path: str,
    assets_dir: Path,
    container_dir: Path,
) -> str:
    """Compute the reference path from the container to the nested asset."""
    asset_full_path = (assets_dir.parent / relative_asset_path).resolve()
    try:
        ref_path = asset_full_path.relative_to(container_dir.resolve())
        return f"./{ref_path.as_posix()}"
    except ValueError:
        return (
            "../" + asset_full_path.relative_to(
                container_dir.parent.resolve(),
            ).as_posix()
        )


def add_nested_asset_reference(
    container_dir: Path,
    group: str,
    prim_name: str,
    ref_asset_path: str,
    transform: schemas.TransformParams,
    *,
    project_mpu: float,
    project_up_axis: str,
) -> str:
    """Author a nested asset reference inside a container's ``contents.usda``.

    Like a scene placement, the nested asset is scaled and turned into its
    container's units and up axis. *transform*'s translate is in the
    container's own units and axes (see :func:`resolve_asset_position`).
    """
    contents_path = container_dir / constants.ASWFLayerNames.CONTENTS
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(container_dir)

    if contents_path.exists():
        contents_layer = Sdf.Layer.FindOrOpen(str(contents_path))
    else:
        contents_layer = Sdf.Layer.CreateNew(str(contents_path))
        contents_layer.defaultPrim = default_prim_name

    authoring.asset_folder.ensure_layer_scope(
        contents_layer, default_prim_name, "contents", "Xform",
    )
    _ensure_group_scope(contents_layer, default_prim_name, group)
    contents_layer.Save()

    stage = Usd.Stage.Open(str(contents_path))
    if stage is None:
        msg = f"Cannot open contents layer: {contents_path}"
        raise RuntimeError(msg)

    wrapper_path = f"/{default_prim_name}/contents/{group}/{prim_name}"
    wrapper = UsdGeom.Xform.Define(stage, wrapper_path)

    container_mpu, container_up = authoring.asset_folder.asset_metrics(
        container_dir, project_mpu=project_mpu, project_up_axis=project_up_axis,
    )

    ref_full_path = (container_dir / ref_asset_path).resolve()
    nested_mpu, nested_up = container_mpu, container_up
    if ref_full_path.exists():
        nested_mpu, nested_up = usd.metrics.file_metrics(
            ref_full_path, default_mpu=project_mpu, default_up_axis=project_up_axis,
        )
        nested_mpu = usd.metrics.usable_mpu(nested_mpu)
    unit_scale, up_axis_correction = usd.metrics.conform(
        nested_mpu, nested_up, parent_mpu=container_mpu, parent_up_axis=container_up,
    )

    sx, sy, sz = transform.scale
    final_scale = (sx * unit_scale, sy * unit_scale, sz * unit_scale)

    xformable = UsdGeom.Xformable(wrapper)
    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(Gf.Vec3d(*transform.translate))
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(*transform.rotate))
    xformable.AddScaleOp().Set(Gf.Vec3f(*final_scale))

    asset_inner = stage.DefinePrim(f"{wrapper_path}/asset", "Xform")
    if up_axis_correction is not None:
        UsdGeom.Xformable(asset_inner).AddRotateXOp().Set(up_axis_correction)
    asset_inner.GetReferences().AddReference(ref_asset_path)

    stage.Save()
    authoring.asset_folder.ensure_root_reference(container_dir, constants.ASWFLayerNames.CONTENTS)

    logger.info(
        "Added nested asset %s -> %s in %s/%s",
        prim_name, ref_asset_path, container_dir.name, constants.ASWFLayerNames.CONTENTS,
    )
    return wrapper_path


def update_nested_asset_transform(
    container_dir: Path,
    group: str,
    prim_name: str,
    translate: tuple[float, float, float],
    rotate: tuple[float, float, float],
) -> bool:
    """Update translate/rotate on a nested-asset wrapper in ``contents.usda``.

    *translate* is in the container's own units and axes.
    """
    contents_path = container_dir / constants.ASWFLayerNames.CONTENTS
    if not contents_path.exists():
        return False

    default_prim_name = authoring.asset_folder.resolve_default_prim_name(container_dir)
    wrapper_path = f"/{default_prim_name}/contents/{group}/{prim_name}"

    stage = Usd.Stage.Open(str(contents_path))
    if stage is None:
        return False
    wrapper = stage.GetPrimAtPath(wrapper_path)
    if not wrapper or not wrapper.IsValid():
        return False

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
    xformable.AddTranslateOp().Set(Gf.Vec3d(*translate))
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(*rotate))
    xformable.AddScaleOp().Set(existing_scale)

    stage.Save()
    logger.info(
        "Updated nested transform %s in %s/%s",
        prim_name, container_dir.name, constants.ASWFLayerNames.CONTENTS,
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
    contents_path = container_dir / constants.ASWFLayerNames.CONTENTS
    if not contents_path.exists():
        return True

    layer = Sdf.Layer.FindOrOpen(str(contents_path))
    if layer is None:
        return False

    default_prim_name = authoring.asset_folder.resolve_default_prim_name(container_dir)
    parent_path = Sdf.Path(f"/{default_prim_name}/contents/{group}")
    parent_spec = layer.GetPrimAtPath(parent_path)
    if parent_spec is not None and prim_name in parent_spec.nameChildren:
        del parent_spec.nameChildren[prim_name]
        layer.Save()
        logger.info(
            "Removed nested asset %s from %s/%s",
            prim_name, container_dir.name, constants.ASWFLayerNames.CONTENTS,
        )

    cleanup_unused_contents_in_folder(container_dir)
    return True


def cleanup_unused_contents_in_folder(container_dir: Path) -> list[str]:
    """Drop empty group scopes in *container_dir*'s ``contents.usda``.

    Mirrors :func:`bowerbot.utils.materials.layer.remove_unused`:
    removes per-prim entries that no longer carry meaningful data, then
    deletes the layer file when it has nothing left and rebuilds the
    root references without it. For contents, "meaningful" means a
    reference arc; empty group scopes (``Props``, ``Furniture``, etc.)
    are the unused entries.
    """
    contents_path = container_dir / constants.ASWFLayerNames.CONTENTS
    if not contents_path.exists():
        return []

    layer = Sdf.Layer.FindOrOpen(str(contents_path))
    if layer is None:
        return []

    default_prim_name = authoring.asset_folder.resolve_default_prim_name(container_dir)
    contents_scope_path = Sdf.Path(f"/{default_prim_name}/contents")
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

    authoring.asset_folder.remove_empty_layer(
        contents_path, container_dir, lambda p: p.HasAuthoredReferences(),
    )

    if removed:
        logger.info(
            "Cleaned %d empty group(s) from %s/%s",
            len(removed), container_dir.name, constants.ASWFLayerNames.CONTENTS,
        )
    return removed


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


# ── Positions in a container's frame ──


def get_container_world_inverse(
    stage: Usd.Stage, frame_prim_path: str,
) -> Gf.Matrix4d | None:
    """Return the inverse world transform of *frame_prim_path*.

    For positions inside an asset folder, pass the prim that references the
    folder (see :func:`resolve_asset_dir_for_prim`): its frame includes the
    folder's unit scale and up-axis turn.
    """
    prim = stage.GetPrimAtPath(frame_prim_path)
    if not prim or not prim.IsValid():
        return None

    xform_cache = UsdGeom.XformCache()
    return xform_cache.GetLocalToWorldTransform(prim).GetInverse()


def resolve_asset_position(
    mode: schemas.PositionMode,
    translate: tuple[float, float, float],
    *,
    asset_dir: Path,
    world_to_local_mat: Gf.Matrix4d | None,
    up_given: bool,
    project_mpu: float,
    project_up_axis: str,
) -> tuple[float, float, float]:
    """Resolve a tool's translate into a position in the asset's own units and axes.

    ``ABSOLUTE``: *translate* is a world point, taken into the asset's frame
    by *world_to_local_mat*. ``BOUNDS_OFFSET``: *translate* holds offsets in
    the project's units and axes from the asset's bounding box: from its
    center on the floor plane, and from its top along the up axis (from its
    bottom when negative; a default distance above the top when *up_given*
    is false).
    """
    if mode is schemas.PositionMode.ABSOLUTE:
        if world_to_local_mat is None:
            return translate
        internal = world_to_local_mat.Transform(Gf.Vec3d(*translate))
        return internal[0], internal[1], internal[2]

    to_asset = authoring.asset_folder.conform_matrix(
        asset_dir, project_mpu=project_mpu, project_up_axis=project_up_axis,
    ).GetInverse()
    offset = to_asset.TransformDir(Gf.Vec3d(*translate))
    bounds = authoring.asset_folder.get_geometry_bounds(asset_dir)
    if bounds is None:
        return offset[0], offset[1], offset[2]

    asset_mpu, asset_up_axis = authoring.asset_folder.asset_metrics(
        asset_dir, project_mpu=project_mpu, project_up_axis=project_up_axis,
    )
    return _apply_bounds_offsets(
        bounds, (offset[0], offset[1], offset[2]),
        up=usd.metrics.axis_index(asset_up_axis),
        up_given=up_given,
        default_above=constants.PlacementDefaults.ABOVE_OFFSET_METERS / asset_mpu,
    )


# ── Helpers ──


def _apply_bounds_offsets(
    bounds: dict[str, dict[str, float]],
    offset: tuple[float, float, float],
    *,
    up: int,
    up_given: bool,
    default_above: float,
) -> tuple[float, float, float]:
    """Turn offsets from an asset's bounds into a position, all in the asset's units and axes."""
    axes = "xyz"
    position = [bounds["center"][axes[i]] + offset[i] for i in range(3)]
    if not up_given:
        position[up] = bounds["max"][axes[up]] + default_above
    elif offset[up] >= 0:
        position[up] = bounds["max"][axes[up]] + offset[up]
    else:
        position[up] = bounds["min"][axes[up]] + offset[up]
    return position[0], position[1], position[2]


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
