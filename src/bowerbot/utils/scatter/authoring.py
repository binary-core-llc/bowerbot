# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter authoring — writing a PointInstancer or placements, and reading them back."""

from __future__ import annotations

from typing import Any

import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, Vt

from bowerbot.schemas import (
    AssetMetadata,
    ScatterInstanceSet,
    ScatterNamespace,
    ScatterOutput,
    ScatterPrototype,
    ScatterRules,
    ScatterTuning,
    SceneObject,
)
from bowerbot.utils.core.bounds import world_bounds
from bowerbot.utils.core.references import add_references, get_prim_ref_paths
from bowerbot.utils.core.transforms import extract_position, gf_matrix_to_numpy
from bowerbot.utils.core.values import to_vec3
from bowerbot.utils.scatter.orientation import quat_mul, quat_to_rotate_xyz


def to_local(
    stage: Usd.Stage, parent_path: str, instances: ScatterInstanceSet,
) -> ScatterInstanceSet:
    """Re-express world-space instances in the frame of *parent_path*."""
    parent = stage.GetPrimAtPath(parent_path)
    if not parent.IsValid():
        return instances
    world = UsdGeom.Xformable(parent).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    if world == Gf.Matrix4d(1.0):
        return instances
    inverse = world.GetInverse()
    matrix = gf_matrix_to_numpy(inverse)
    positions = instances.positions @ matrix[:3, :3] + matrix[3, :3]
    rot = inverse.RemoveScaleShear().ExtractRotationQuat()
    parent_q = np.array([[rot.GetReal(), *rot.GetImaginary()]])
    orientations = quat_mul(np.repeat(parent_q, instances.count, axis=0),
                            instances.orientations)
    return ScatterInstanceSet(
        proto_indices=instances.proto_indices, positions=positions,
        orientations=orientations, scales=instances.scales,
    )


def write_scatter(
    stage: Usd.Stage,
    *,
    prim_path: str,
    output: ScatterOutput,
    prototypes: list[ScatterPrototype],
    instances: ScatterInstanceSet,
    first_index: int,
) -> dict[str, Any]:
    """Author a scatter in scene.usda as a PointInstancer or as placements."""
    if stage.GetPrimAtPath(prim_path).IsValid():
        stage.RemovePrim(prim_path)
    if output is ScatterOutput.PLACEMENTS:
        if instances.count > ScatterRules.MAX_PLACEMENTS:
            msg = (
                f"{instances.count:,} instances is too many for output='placements' "
                f"(max {ScatterRules.MAX_PLACEMENTS:,}); use output='instancer'."
            )
            raise ValueError(msg)
        stage.DefinePrim(prim_path, "Xform")
        local = to_local(stage, prim_path, instances)
        add_references(
            stage, placement_objects(prim_path, prototypes, local, first_index),
        )
        return {"placements": instances.count, "warnings": []}

    write_instancer(stage, prim_path, prototypes, instances)
    return {"placements": 0, "warnings": instancer_size_warning(instances.count)}


def write_instancer(
    stage: Usd.Stage,
    prim_path: str,
    prototypes: list[ScatterPrototype],
    instances: ScatterInstanceSet,
) -> None:
    """Author a PointInstancer whose prototypes are placement wrappers of the assets."""
    instancer = UsdGeom.PointInstancer.Define(stage, prim_path)
    xformable = UsdGeom.Xformable(instancer)
    xformable.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.0))
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(0.0, 0.0, 0.0))
    xformable.AddScaleOp().Set(Gf.Vec3f(1.0, 1.0, 1.0))

    prototypes_path = f"{prim_path}/{ScatterNamespace.PROTOTYPES}"
    stage.DefinePrim(prototypes_path, "Scope")
    add_references(stage, [
        SceneObject(
            prim_path=f"{prototypes_path}/{proto.name}",
            asset=AssetMetadata(
                name=proto.name, source_skill="local", source_id=proto.source,
                file_path=proto.scene_ref,
            ),
        )
        for proto in prototypes
    ])
    instancer.CreatePrototypesRel().SetTargets(
        [Sdf.Path(f"{prototypes_path}/{proto.name}") for proto in prototypes],
    )

    local = to_local(stage, prim_path, instances)
    q = local.orientations / np.linalg.norm(local.orientations, axis=1)[:, None]
    instancer.CreateProtoIndicesAttr(
        Vt.IntArray.FromNumpy(local.proto_indices.astype(np.int32)),
    )
    instancer.CreatePositionsAttr(
        Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(local.positions, dtype=np.float32)),
    )
    instancer.CreateOrientationsAttr(
        Vt.QuathArray.FromNumpy(np.ascontiguousarray(q[:, [1, 2, 3, 0]], dtype=np.float16)),
    )
    instancer.CreateScalesAttr(
        Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(local.scales, dtype=np.float32)),
    )
    time = Usd.TimeCode.Default()
    extent = instancer.ComputeExtentAtTime(time, time)
    if extent:
        instancer.CreateExtentAttr(extent)


def instancer_size_warning(count: int) -> list[str]:
    """Warn when an instancer makes scene.usda heavy to re-save."""
    if count <= ScatterTuning.LARGE_SCATTER:
        return []
    megabytes = count * ScatterTuning.ASCII_BYTES_PER_INSTANCE / 1e6
    return [
        f"{count:,} instances add about {megabytes:,.0f} MB to scene.usda, which "
        "BowerBot re-saves after every edit. Lower the density, or split the area "
        "into several scatters with regions.",
    ]


def placement_objects(
    group_path: str,
    prototypes: list[ScatterPrototype],
    instances: ScatterInstanceSet,
    first_index: int,
) -> list[SceneObject]:
    """One placement wrapper per instance under *group_path*, numbered from *first_index*."""
    rotations = quat_to_rotate_xyz(instances.orientations)
    objects: list[SceneObject] = []
    for i in range(instances.count):
        proto = prototypes[int(instances.proto_indices[i])]
        objects.append(SceneObject(
            prim_path=f"{group_path}/{proto.name}_{first_index + i:02d}",
            asset=AssetMetadata(
                name=proto.name, source_skill="local", source_id=proto.source,
                file_path=proto.scene_ref,
            ),
            translate=to_vec3(instances.positions[i].tolist()),
            rotate=rotations[i],
            scale=to_vec3(instances.scales[i].tolist()),
        ))
    return objects


def count_by_prototype(
    prototypes: list[ScatterPrototype], instances: ScatterInstanceSet,
) -> dict[str, int]:
    """Instances per prototype name."""
    counts = np.bincount(instances.proto_indices, minlength=len(prototypes))
    return {proto.name: int(c) for proto, c in zip(prototypes, counts, strict=True)}


def format_scatter_prim(prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache) -> dict[str, Any]:
    """``list_scene`` entry for a scatter PointInstancer."""
    instancer = UsdGeom.PointInstancer(prim)
    indices = instancer.GetProtoIndicesAttr().Get() or []
    stage = prim.GetStage()
    prototypes = []
    for target in instancer.GetPrototypesRel().GetTargets():
        proto = stage.GetPrimAtPath(target)
        child = proto.GetChild("asset") if proto.IsValid() else proto
        refs = get_prim_ref_paths(child) if child and child.IsValid() else []
        prototypes.append(refs[0] if refs else str(target))
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "scatter",
        "type": "PointInstancer",
        "instances": len(indices),
        "prototypes": prototypes,
        "position": extract_position(prim),
        "bounds": world_bounds(prim, bbox_cache),
    }
