# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Drop to surface — settling placements and reseating scatters on the ground."""

from __future__ import annotations

from typing import Any

import numpy as np
from pxr import Gf, Usd, UsdGeom, Vt

from bowerbot.schemas import (
    ScatterDropAlign,
    ScatterTuning,
    SurfaceIndex,
)
from bowerbot.utils import surface_utils
from bowerbot.utils.core.asset_folder import parse_nested_contents_path
from bowerbot.utils.core.bounds import prim_world_box
from bowerbot.utils.core.metrics import up_vector
from bowerbot.utils.core.references import get_prim_ref_paths
from bowerbot.utils.core.transforms import gf_matrix_to_numpy
from bowerbot.utils.scatter.orientation import (
    quat_between,
    quat_conj,
    quat_heading,
    quat_mul,
    quat_rotate,
    rotate_xyz_rotation,
)
from bowerbot.utils.scatter.prototypes import base_footprint, prototype_points
from bowerbot.utils.scatter.resting import base_samples, ground_normals, settle_shift


def drop_targets(stage: Usd.Stage, prim_paths: list[str]) -> tuple[list[str], list[str]]:
    """Expand paths to ``(placement wrappers, scatters)``; groups expand to their contents."""
    wrappers: list[str] = []
    scatters: list[str] = []
    for prim_path in prim_paths:
        if parse_nested_contents_path(prim_path) is not None:
            msg = (
                f"{prim_path} is a nested placement inside an asset; "
                "drop_to_surface moves scene-level placements only."
            )
            raise ValueError(msg)
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            msg = f"Prim not found: {prim_path}"
            raise ValueError(msg)
        iterator = iter(Usd.PrimRange(prim))
        for candidate in iterator:
            path = str(candidate.GetPath())
            if candidate.IsA(UsdGeom.PointInstancer):
                iterator.PruneChildren()
                if path not in scatters:
                    scatters.append(path)
                continue
            if _is_placement_wrapper(candidate):
                if path not in wrappers:
                    wrappers.append(path)
                iterator.PruneChildren()
    if not wrappers and not scatters:
        msg = (
            f"No placements or scatters found under {prim_paths}. Pass placement "
            "or scatter paths (/Scene/<Group>/<Name>) or a group that contains them."
        )
        raise ValueError(msg)
    return wrappers, scatters


def drop_scatter(
    stage: Usd.Stage, prim_path: str, index: SurfaceIndex, *, align: ScatterDropAlign,
) -> dict[str, Any]:
    """Reseat a scatter's instances on the surface in place, optionally re-tilting them."""
    up = index.up
    instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(prim_path))
    time = Usd.TimeCode.Default()
    positions = np.asarray(instancer.GetPositionsAttr().Get() or [], dtype=np.float64)
    n = positions.shape[0]
    if n == 0:
        return {"prim_path": prim_path, "supported": False}
    proto_idx = np.asarray(instancer.GetProtoIndicesAttr().Get(), dtype=np.int64)
    raw_q = instancer.GetOrientationsAttr().Get()
    orientations = (
        np.asarray(raw_q, dtype=np.float64)[:, [3, 0, 1, 2]] if raw_q
        else np.tile([1.0, 0.0, 0.0, 0.0], (n, 1))
    )
    raw_s = instancer.GetScalesAttr().Get()
    scales = np.asarray(raw_s, dtype=np.float64) if raw_s else np.ones((n, 3))

    world_gf = UsdGeom.XformCache(time).GetLocalToWorldTransform(instancer.GetPrim())
    world = gf_matrix_to_numpy(world_gf)
    to_local = np.linalg.inv(world)
    targets = instancer.GetPrototypesRel().GetTargets()
    proto_min = np.zeros((len(targets), 3))
    proto_max = np.zeros((len(targets), 3))
    for i, target in enumerate(targets):
        points = prototype_points(stage, str(target), up)
        local = points @ to_local[:3, :3] + to_local[3, :3]
        proto_min[i], proto_max[i] = base_footprint(local, up)
    base_min, base_max = proto_min[proto_idx], proto_max[proto_idx]

    retilted = 0
    if align is ScatterDropAlign.SURFACE:
        rotation = world_gf.RemoveScaleShear().ExtractRotationQuat()
        to_world_q = np.tile([rotation.GetReal(), *rotation.GetImaginary()], (n, 1))
        world_scale = float(np.cbrt(abs(np.linalg.det(world[:3, :3]))))
        up_vec = up_vector(up)
        base = (base_min + base_max) / 2.0
        centers_local = positions + quat_rotate(orientations, base * scales)
        centers = centers_local @ world[:3, :3] + world[3, :3]
        headings = quat_heading(quat_mul(to_world_q, orientations), up)
        hit, _, tris = surface_utils.surface_under(
            index, centers, mode="nearest", reference=centers[:, up].copy(),
        )
        fallback = np.where(
            hit[:, None], index.triangles.normals[np.maximum(tris, 0)], up_vec,
        )
        normals, fitted = ground_normals(
            index, centers, headings, scales * world_scale, base_min, base_max,
            fallback, up,
        )
        tilted = quat_mul(
            quat_conj(to_world_q), quat_mul(quat_between(up_vec, normals), headings),
        )
        orientations = np.where(fitted[:, None], tilted, orientations)
        positions = centers_local - quat_rotate(orientations, base * scales)
        retilted = int(fitted.sum())

    samples = base_samples(positions, orientations, scales, base_min, base_max, up)
    world_samples = samples.reshape(-1, 3) @ world[:3, :3] + world[3, :3]
    shift, supported = settle_shift(index, world_samples.reshape(samples.shape), up)
    if not supported.any():
        return {"prim_path": prim_path, "supported": False}
    delta = np.outer(shift, up_vector(up)) @ to_local[:3, :3]
    if retilted:
        instancer.GetOrientationsAttr().Set(Vt.QuathArray.FromNumpy(
            np.ascontiguousarray(orientations[:, [1, 2, 3, 0]], dtype=np.float16),
        ))
    instancer.GetPositionsAttr().Set(
        Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(positions + delta, dtype=np.float32)),
    )
    extent = instancer.ComputeExtentAtTime(time, time)
    if extent:
        instancer.CreateExtentAttr(extent)
    stranded = np.flatnonzero(~supported)[:ScatterTuning.STRANDED_REPORT]
    stranded_at = world_samples.reshape(samples.shape)[stranded].mean(axis=1)
    return {
        "prim_path": prim_path,
        "supported": True,
        "instances": n,
        "reseated": int(supported.sum()),
        "retilted": retilted,
        "moved_by": {
            "min": round(float(shift[supported].min()), 4),
            "max": round(float(shift[supported].max()), 4),
        },
        "no_surface_under": {
            "count": int((~supported).sum()),
            "instances": stranded.tolist(),
            "positions": np.round(stranded_at, 3).tolist(),
        },
    }


def drop_prim(
    stage: Usd.Stage,
    prim_path: str,
    index: SurfaceIndex,
    *,
    align: ScatterDropAlign,
) -> dict[str, Any]:
    """Move one placement so it rests on the highest surface under its footprint."""
    up = index.up
    axes = list(index.axes)
    prim = stage.GetPrimAtPath(prim_path)
    bmin, bmax = prim_world_box(stage, prim_path)
    grid = np.linspace(0.1, 0.9, ScatterTuning.DROP_FOOTPRINT)
    ga, gb = np.meshgrid(grid, grid, indexing="ij")
    footprint = np.zeros((ga.size, 3))
    footprint[:, axes[0]] = bmin[axes[0]] + ga.ravel() * (bmax[axes[0]] - bmin[axes[0]])
    footprint[:, axes[1]] = bmin[axes[1]] + gb.ravel() * (bmax[axes[1]] - bmin[axes[1]])
    ceiling = np.full(footprint.shape[0], bmax[up])
    hit, heights, _ = surface_utils.surface_under(
        index, footprint, mode="below", reference=ceiling,
    )
    if not hit.any():
        # Fully buried: use the nearest ground above instead.
        hit, heights, _ = surface_utils.surface_under(
            index, footprint, mode="nearest", reference=ceiling,
        )
    if not hit.any():
        return {"prim_path": prim_path, "supported": False}

    xformable = UsdGeom.Xformable(prim)
    ops = {op.GetOpType(): op for op in xformable.GetOrderedXformOps()}
    translate_op = ops.get(UsdGeom.XformOp.TypeTranslate)
    if translate_op is None:
        msg = f"{prim_path} has no translate op; only BowerBot placements can be dropped."
        raise ValueError(msg)
    parent_world = UsdGeom.Xformable(prim.GetParent()).ComputeLocalToWorldTransform(
        Usd.TimeCode.Default(),
    ) if prim.GetParent().IsA(UsdGeom.Xformable) else Gf.Matrix4d(1.0)
    to_parent = parent_world.GetInverse()
    old_local = np.array(translate_op.Get() or Gf.Vec3d(0.0, 0.0, 0.0), dtype=np.float64)
    up_vec = up_vector(up)

    rotate_value = None
    world_shift = np.zeros(3)
    if align is ScatterDropAlign.SURFACE and int(hit.sum()) >= 3:
        pts = footprint[hit].copy()
        pts[:, up] = heights[hit]
        design = np.column_stack([pts[:, axes[0]], pts[:, axes[1]], np.ones(pts.shape[0])])
        coef, *_ = np.linalg.lstsq(design, pts[:, up], rcond=None)
        normal = np.zeros(3)
        normal[axes[0]], normal[axes[1]], normal[up] = -coef[0], -coef[1], 1.0
        normal /= np.linalg.norm(normal)
        tilt = quat_between(up_vec, normal[None, :])[0]
        rotate_op = ops.get(UsdGeom.XformOp.TypeRotateXYZ)
        if rotate_op is None:
            msg = f"{prim_path} has no rotateXYZ op; use align='keep' to drop it upright."
            raise ValueError(msg)
        old_rot = rotate_xyz_rotation(rotate_op.Get())
        tilt_rot = Gf.Rotation(Gf.Quatd(tilt[0], Gf.Vec3d(*tilt[1:].tolist())))
        new_rot = old_rot * tilt_rot
        rz, ry, rx = new_rot.Decompose(Gf.Vec3d.ZAxis(), Gf.Vec3d.YAxis(), Gf.Vec3d.XAxis())
        rotate_value = Gf.Vec3f(rx, ry, rz)

        pivot = np.asarray(
            UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            .ExtractTranslation(), dtype=np.float64,
        )
        base = (bmin + bmax) / 2.0
        base[up] = bmin[up]
        swung = base + quat_rotate(tilt[None, :], (pivot - base)[None, :])[0]
        world_shift += swung - pivot
        fitted = coef[0] * pts[:, axes[0]] + coef[1] * pts[:, axes[1]] + coef[2]
        residual = float(np.max(pts[:, up] - fitted))
        target = float(coef[0] * base[axes[0]] + coef[1] * base[axes[1]] + coef[2])
        target += max(residual, 0.0)
        world_shift += up_vec * (target - base[up])
    else:
        world_shift += up_vec * (float(np.nanmax(heights[hit])) - bmin[up])

    shift_local = np.asarray(to_parent.TransformDir(Gf.Vec3d(*world_shift.tolist())))
    new_local = old_local + shift_local
    translate_op.Set(Gf.Vec3d(*new_local.tolist()))
    if rotate_value is not None:
        ops[UsdGeom.XformOp.TypeRotateXYZ].Set(rotate_value)
    return {
        "prim_path": prim_path,
        "supported": True,
        "from": [round(v, 4) for v in old_local.tolist()],
        "to": [round(v, 4) for v in new_local.tolist()],
        "moved_by": round(float(np.dot(world_shift, up_vec)), 4),
    }


def _is_placement_wrapper(prim: Usd.Prim) -> bool:
    """A scene placement wrapper: an Xformable whose ``asset`` child carries a reference."""
    child = prim.GetChild("asset")
    return (
        prim.IsA(UsdGeom.Xformable)
        and child.IsValid()
        and bool(get_prim_ref_paths(child))
    )
