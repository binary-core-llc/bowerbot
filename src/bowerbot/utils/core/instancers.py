# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Point instancers — which prims are prototypes, removing one with its instances, checks.

A prototype is a prim an instancer's ``prototypes`` relationship names; each
instance picks one through ``protoIndices``. The per-instance arrays
(positions, orientations, scales, ids, per-instance primvars ...) are
parallel to ``protoIndices``, so a prototype is removed together with its
instances and the rest are re-indexed, never by dropping the target alone.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from pxr import Sdf, Usd, UsdGeom

from bowerbot.schemas import ScatterInstancerArrays, Severity, ValidationIssue
from bowerbot.utils.core.integrity import remove_scene_prim


def prototype_owner(stage: Usd.Stage, prim_path: str) -> str | None:
    """The instancer whose prototype *prim_path* is, or lies inside; ``None`` otherwise."""
    path = Sdf.Path(prim_path)
    for ancestor in path.GetAncestorsRange():
        if ancestor == path:
            continue
        prim = stage.GetPrimAtPath(ancestor)
        if prim.IsValid() and prim.IsA(UsdGeom.PointInstancer):
            targets = UsdGeom.PointInstancer(prim).GetPrototypesRel().GetTargets()
            if any(path.HasPrefix(target) for target in targets):
                return str(ancestor)
    return None


def prototypes_below(stage: Usd.Stage, prim_path: str) -> str | None:
    """The instancer above *prim_path* whose prototypes *prim_path* holds (its prototype scope)."""
    path = Sdf.Path(prim_path)
    for ancestor in path.GetAncestorsRange():
        if ancestor == path:
            continue
        prim = stage.GetPrimAtPath(ancestor)
        if prim.IsValid() and prim.IsA(UsdGeom.PointInstancer):
            targets = UsdGeom.PointInstancer(prim).GetPrototypesRel().GetTargets()
            if any(target.HasPrefix(path) and target != path for target in targets):
                return str(ancestor)
    return None


def require_not_prototype(stage: Usd.Stage, prim_path: str) -> None:
    """Refuse moving a scatter's prototype: the scatter moves as one prim."""
    owner = prototype_owner(stage, prim_path)
    if owner is not None:
        msg = (
            f"{prim_path} is a prototype of the scatter {owner}: each of its pieces is "
            f"placed by the scatter, and moving the prototype would shift them all. "
            f"Move the scatter ({owner}) instead."
        )
        raise ValueError(msg)


def remove_prototype(stage: Usd.Stage, prim_path: str) -> dict[str, Any]:
    """Remove a prototype and every instance of it, re-indexing the others.

    The last prototype takes the whole scatter with it. Returns the scatter,
    how many instances went, whether the scatter itself went, and the
    dropped-targets report.
    """
    owner = prototype_owner(stage, prim_path)
    if owner is None:
        msg = f"{prim_path} is not a scatter prototype."
        raise ValueError(msg)
    instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(owner))
    targets = list(instancer.GetPrototypesRel().GetTargets())
    if Sdf.Path(prim_path) not in targets:
        msg = (
            f"{prim_path} is inside the prototype of a scatter, not the prototype "
            f"itself. Remove the prototype, or edit its asset."
        )
        raise ValueError(msg)
    index = targets.index(Sdf.Path(prim_path))
    indices = np.asarray(instancer.GetProtoIndicesAttr().Get() or [], dtype=np.int64)
    removed = int(np.count_nonzero(indices == index))
    if len(targets) == 1:
        report = remove_scene_prim(stage, owner)
        return {"scatter": owner, "removed_instances": removed, "removed_scatter": True,
                **report}

    keep = indices != index
    arrays = _per_instance_attributes(instancer, indices.size)
    for attr in (instancer.GetProtoIndicesAttr(), *arrays):
        if attr.GetNumTimeSamples():
            msg = f"{attr.GetPath()} is animated; BowerBot doesn't edit animated scatters."
            raise ValueError(msg)
    ids = instancer.GetIdsAttr().Get()
    _set_invisible(instancer, keep, None if ids is None else np.asarray(ids))
    for attr in arrays:
        attr.Set(_kept(attr.Get(), keep))
    new_indices = indices[keep]
    new_indices[new_indices > index] -= 1
    instancer.GetProtoIndicesAttr().Set(new_indices.astype(np.int32).tolist())
    report = remove_scene_prim(stage, prim_path)
    return {"scatter": owner, "removed_instances": removed, "removed_scatter": False, **report}


def instancer_problems(instancer: UsdGeom.PointInstancer) -> list[ValidationIssue]:
    """What makes an instancer draw wrong: missing prototypes, bad indices, short arrays."""
    where = str(instancer.GetPath())
    stage = instancer.GetPrim().GetStage()
    targets = instancer.GetPrototypesRel().GetTargets()
    issues = [
        ValidationIssue(severity=Severity.ERROR, prim_path=where,
                        message=f"Instancer prototype {target} does not exist")
        for target in targets if not stage.GetPrimAtPath(target).IsValid()
    ]
    issues += [
        ValidationIssue(severity=Severity.WARNING, prim_path=where,
                        message=(f"Instancer prototype {target} is outside the instancer, "
                                 f"so it also draws on its own"))
        for target in targets if not target.HasPrefix(instancer.GetPath())
    ]
    indices = instancer.GetProtoIndicesAttr().Get() or []
    bad = sorted({int(i) for i in indices if not 0 <= int(i) < len(targets)})
    if bad:
        issues.append(ValidationIssue(
            severity=Severity.ERROR, prim_path=where,
            message=(f"protoIndices name prototype(s) {bad[:5]}, but the instancer has "
                     f"{len(targets)} prototype(s)"),
        ))
    for name in ScatterInstancerArrays.ATTRIBUTES:
        attr = instancer.GetPrim().GetAttribute(name)
        value = attr.Get() if attr and attr.HasAuthoredValue() else None
        if value is not None and len(value) != len(indices):
            issues.append(ValidationIssue(
                severity=Severity.ERROR, prim_path=where,
                message=f"{name} has {len(value)} entries for {len(indices)} instances",
            ))
    return issues


def _per_instance_attributes(
    instancer: UsdGeom.PointInstancer, count: int,
) -> list[Usd.Attribute]:
    """Authored attributes holding one value per instance (primvar indices when indexed)."""
    attrs = [
        attr for name in ScatterInstancerArrays.ATTRIBUTES
        if (attr := instancer.GetPrim().GetAttribute(name)) and attr.HasAuthoredValue()
    ]
    for primvar in UsdGeom.PrimvarsAPI(instancer).GetPrimvarsWithAuthoredValues():
        if primvar.GetInterpolation() not in ScatterInstancerArrays.PRIMVAR_INTERPOLATIONS:
            continue
        attrs.append(primvar.GetIndicesAttr() if primvar.IsIndexed() else primvar.GetAttr())
    for attr in attrs:
        value = attr.Get()
        if value is not None and len(value) != count:
            msg = (
                f"{attr.GetPath()} has {len(value)} entries for {count} instances; the "
                f"scatter is inconsistent, so BowerBot won't edit it. Re-scatter with "
                f"replace=true."
            )
            raise ValueError(msg)
    return attrs


def _kept(value: Any, keep: np.ndarray) -> Any:
    """The entries of a Vt array where *keep* is true, as the same array type."""
    kind = type(value)
    try:
        return kind.FromNumpy(np.asarray(value)[keep])
    except (AttributeError, TypeError, ValueError):
        return kind([value[i] for i in np.flatnonzero(keep)])


def _set_invisible(
    instancer: UsdGeom.PointInstancer, keep: np.ndarray, ids: np.ndarray | None,
) -> None:
    """Keep ``invisibleIds`` naming the same instances once *keep* drops the others."""
    attr = instancer.GetInvisibleIdsAttr()
    hidden = attr.Get() if attr.HasAuthoredValue() else None
    if not hidden:
        return
    if ids is not None:
        remaining = set(ids[keep].tolist())
        attr.Set([int(i) for i in hidden if int(i) in remaining])
        return
    new_index = np.cumsum(keep) - 1
    attr.Set([int(new_index[i]) for i in hidden if 0 <= int(i) < keep.size and keep[int(i)]])
