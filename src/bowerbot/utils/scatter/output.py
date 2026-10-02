# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Writing a scatter into scene.usda, as a PointInstancer or as placements."""

from __future__ import annotations

from typing import Any

import numpy as np
from pxr import Gf
from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import Vt

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import usd


def write(
    stage: Usd.Stage,
    *,
    prim_path: str,
    output: schemas.ScatterOutput,
    prototypes: list[schemas.ScatterPrototype],
    instances: schemas.ScatterInstanceSet,
    first_index: int,
    project_mpu: float,
    project_up_axis: str,
) -> dict[str, Any]:
    """Author a scatter in scene.usda as a PointInstancer or as placements."""
    if stage.GetPrimAtPath(prim_path).IsValid():
        stage.RemovePrim(prim_path)
    if output is schemas.ScatterOutput.PLACEMENTS:
        if instances.count > constants.ScatterRules.MAX_PLACEMENTS:
            msg = (
                f"{instances.count:,} instances is too many for output='placements' "
                f"(max {constants.ScatterRules.MAX_PLACEMENTS:,}); use output='instancer'."
            )
            raise ValueError(msg)
        stage.DefinePrim(prim_path, "Xform")
        local = to_local(stage, prim_path, instances)
        authoring.placement.add_references(
            stage, placement_objects(prim_path, prototypes, local, first_index),
            project_mpu=project_mpu, project_up_axis=project_up_axis,
        )
        return {"placements": instances.count, "warnings": []}

    write_instancer(
        stage, prim_path, prototypes, instances,
        project_mpu=project_mpu, project_up_axis=project_up_axis,
    )
    return {"placements": 0, "warnings": instancer_size_warning(instances.count)}


def write_instancer(
    stage: Usd.Stage,
    prim_path: str,
    prototypes: list[schemas.ScatterPrototype],
    instances: schemas.ScatterInstanceSet,
    *,
    project_mpu: float,
    project_up_axis: str,
) -> None:
    """Author a PointInstancer whose prototypes are placement wrappers of the assets."""
    instancer = UsdGeom.PointInstancer.Define(stage, prim_path)
    xformable = UsdGeom.Xformable(instancer)
    xformable.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.0))
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(0.0, 0.0, 0.0))
    xformable.AddScaleOp().Set(Gf.Vec3f(1.0, 1.0, 1.0))

    prototypes_path = f"{prim_path}/{constants.ScatterNamespace.PROTOTYPES}"
    stage.DefinePrim(prototypes_path, "Scope")
    authoring.placement.add_references(stage, [
        schemas.SceneObject(
            prim_path=f"{prototypes_path}/{proto.name}",
            asset=schemas.AssetMetadata(
                name=proto.name, source_skill="local", source_id=proto.source,
                file_path=proto.scene_ref,
            ),
        )
        for proto in prototypes
    ], project_mpu=project_mpu, project_up_axis=project_up_axis)
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
    update_extent(instancer)


def placement_objects(
    group_path: str,
    prototypes: list[schemas.ScatterPrototype],
    instances: schemas.ScatterInstanceSet,
    first_index: int,
) -> list[schemas.SceneObject]:
    """One placement wrapper per instance under *group_path*, numbered from *first_index*."""
    rotations = usd.transforms.quat_to_rotate_xyz(instances.orientations)
    objects: list[schemas.SceneObject] = []
    for i in range(instances.count):
        proto = prototypes[int(instances.proto_indices[i])]
        objects.append(schemas.SceneObject(
            prim_path=f"{group_path}/{proto.name}_{first_index + i:02d}",
            asset=schemas.AssetMetadata(
                name=proto.name, source_skill="local", source_id=proto.source,
                file_path=proto.scene_ref,
            ),
            translate=usd.values.vec3(instances.positions[i]),
            rotate=rotations[i],
            scale=usd.values.vec3(instances.scales[i]),
        ))
    return objects


def instancer_size_warning(count: int) -> list[str]:
    """Warn when an instancer makes scene.usda heavy to re-save."""
    if count <= constants.ScatterTuning.LARGE_SCATTER:
        return []
    megabytes = count * constants.ScatterTuning.ASCII_BYTES_PER_INSTANCE / 1e6
    return [
        f"{count:,} instances add about {megabytes:,.0f} MB to scene.usda, which "
        "BowerBot re-saves after every edit. Lower the density, or split the area "
        "into several scatters with regions.",
    ]


def to_local(
    stage: Usd.Stage, parent_path: str, instances: schemas.ScatterInstanceSet,
) -> schemas.ScatterInstanceSet:
    """Re-express world-space instances in the frame of *parent_path*."""
    parent = stage.GetPrimAtPath(parent_path)
    if not parent.IsValid():
        return instances
    world = usd.transforms.world_matrix(parent)
    if usd.transforms.is_identity(world):
        return instances
    inverse = world.GetInverse()
    matrix = usd.transforms.gf_matrix_to_numpy(inverse)
    positions = usd.transforms.transform_points(instances.positions, matrix)
    parent_q = usd.transforms.matrix_rotation_quat(inverse)[None, :]
    orientations = usd.transforms.quat_mul(np.repeat(parent_q, instances.count, axis=0),
                            instances.orientations)
    return schemas.ScatterInstanceSet(
        proto_indices=instances.proto_indices, positions=positions,
        orientations=orientations, scales=instances.scales,
    )


def refresh_extents(stage: Usd.Stage) -> list[str]:
    """Refresh every scatter's stored box; return the ones that changed. Not saved."""
    root_layer = stage.GetRootLayer()
    time = Usd.TimeCode.Default()
    tolerance = constants.ScatterTuning.EXTENT_TOLERANCE
    refreshed: list[str] = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.PointInstancer) or root_layer.GetPrimAtPath(prim.GetPath()) is None:
            continue
        instancer = UsdGeom.PointInstancer(prim)
        real = instancer.ComputeExtentAtTime(time, time)
        if real is None:
            continue
        stored = instancer.GetExtentAttr().Get()
        same = stored is not None and all(
            abs(have - want) <= tolerance * max(1.0, abs(want))
            for corner in range(2) for have, want in zip(stored[corner], real[corner], strict=True)
        )
        if not same:
            instancer.CreateExtentAttr(real)
            refreshed.append(str(prim.GetPath()))
    return refreshed


def update_extent(instancer: UsdGeom.PointInstancer) -> None:
    """Author the instancer's extent from the instances it holds now."""
    time = Usd.TimeCode.Default()
    extent = instancer.ComputeExtentAtTime(time, time)
    if extent:
        instancer.CreateExtentAttr(extent)


def count_by_prototype(
    prototypes: list[schemas.ScatterPrototype], instances: schemas.ScatterInstanceSet,
) -> dict[str, int]:
    """Instances per prototype name."""
    counts = np.bincount(instances.proto_indices, minlength=len(prototypes))
    return {proto.name: int(c) for proto, c in zip(prototypes, counts, strict=True)}
