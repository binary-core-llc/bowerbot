# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Collision groups under ``/Scene/Physics``."""

from __future__ import annotations

import logging
from typing import Any

from pxr import Sdf
from pxr import Usd
from pxr import UsdPhysics

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import physics
from bowerbot.utils import usd

logger = logging.getLogger(__name__)


def create_or_update(
    stage: Usd.Stage,
    name: str,
    *,
    includes: list[str] | None = None,
    excludes: list[str] | None = None,
    filtered_groups: list[str] | None = None,
    invert_filter: bool | None = None,
    merge_group: str | None = None,
    project_mpu: float,
    project_up_axis: str,
) -> dict[str, Any]:
    """Create or update a ``UsdPhysicsCollisionGroup``; auto-ensures a ``UsdPhysics.Scene``."""
    usd.naming.require_prim_name(name, "Collision group name")
    physics.scenes.ensure_default(
        stage, project_mpu=project_mpu, project_up_axis=project_up_axis,
    )

    prim_path = _group_prim_path(name)
    group = UsdPhysics.CollisionGroup.Define(stage, prim_path)

    if includes is not None or excludes is not None:
        collection = group.GetCollidersCollectionAPI()
        if includes is not None:
            collection.CreateIncludesRel().SetTargets(
                [Sdf.Path(p) for p in includes],
            )
        if excludes is not None:
            collection.CreateExcludesRel().SetTargets(
                [Sdf.Path(p) for p in excludes],
            )

    if filtered_groups is not None:
        resolved = [_resolve_group_path(g) for g in filtered_groups]
        for path in resolved:
            if not stage.GetPrimAtPath(path).IsValid():
                raise ValueError(
                    f"filtered_groups references missing group at {path}. "
                    "Create that group first.",
                )
        group.CreateFilteredGroupsRel().SetTargets(
            [Sdf.Path(p) for p in resolved],
        )

    if invert_filter is not None:
        group.CreateInvertFilteredGroupsAttr().Set(bool(invert_filter))

    if merge_group is not None:
        group.CreateMergeGroupNameAttr().Set(str(merge_group))

    stage.Save()
    logger.info("Authored collision group %s at %s", name, prim_path)
    return {
        "name": name,
        "prim_path": prim_path,
        "includes_set": includes is not None,
        "excludes_set": excludes is not None,
        "filtered_groups_set": filtered_groups is not None,
        "invert_filter_set": invert_filter is not None,
        "merge_group_set": merge_group is not None,
    }


def remove(
    stage: Usd.Stage, name: str, *, force: bool = False,
) -> bool:
    """Remove a collision group; refuses if other groups depend on it unless ``force``."""
    prim_path = _group_prim_path(name)
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return False

    if not force:
        dependents = _find_dependent_groups(stage, prim_path)
        if dependents:
            raise ValueError(
                f"Cannot remove collision group {name!r}: {len(dependents)} "
                f"other group(s) reference it via filteredGroups: "
                f"{sorted(dependents)}. Retry with force=True to remove "
                "(BowerBot scrubs the dangling references afterwards).",
            )

    removed = stage.RemovePrim(prim_path)
    if removed:
        stage.Save()
    return removed


def list_all(stage: Usd.Stage) -> schemas.CollisionGroupsSummary:
    """Return every ``UsdPhysicsCollisionGroup`` under ``/Scene/Physics``."""
    scope = stage.GetPrimAtPath(constants.SceneNamespace.PHYSICS)
    if not scope or not scope.IsValid():
        return schemas.CollisionGroupsSummary()

    summaries = [
        _summarize_group(child)
        for child in scope.GetChildren()
        if usd.prim_types.is_collision_group(child)
    ]
    return schemas.CollisionGroupsSummary(groups=summaries)


# ── Helpers ──


def _group_prim_path(name: str) -> str:
    """Path to a group prim, flat-sibling of PhysicsScene under /Scene/Physics."""
    return f"{constants.SceneNamespace.PHYSICS}/{name}"


def _resolve_group_path(name_or_path: str) -> str:
    """Accept either a bare group name or a full prim path; return prim path."""
    if name_or_path.startswith("/"):
        return name_or_path
    return _group_prim_path(name_or_path)


def _summarize_group(prim: Usd.Prim) -> schemas.CollisionGroupSummary:
    """Read a ``UsdPhysicsCollisionGroup`` prim into a summary model."""
    group = UsdPhysics.CollisionGroup(prim)
    collection = group.GetCollidersCollectionAPI()

    includes_rel = collection.GetIncludesRel()
    excludes_rel = collection.GetExcludesRel()
    filtered_rel = group.GetFilteredGroupsRel()
    invert_attr = group.GetInvertFilteredGroupsAttr()
    merge_attr = group.GetMergeGroupNameAttr()

    return schemas.CollisionGroupSummary(
        name=prim.GetName(),
        prim_path=str(prim.GetPath()),
        includes=[str(t) for t in includes_rel.GetTargets()]
        if includes_rel else [],
        excludes=[str(t) for t in excludes_rel.GetTargets()]
        if excludes_rel else [],
        filtered_groups=[str(t) for t in filtered_rel.GetTargets()]
        if filtered_rel else [],
        invert_filter=bool(invert_attr.Get()) if invert_attr else False,
        merge_group=str(merge_attr.Get()) if (
            merge_attr and merge_attr.Get()
        ) else None,
    )


def _find_dependent_groups(stage: Usd.Stage, group_prim_path: str) -> list[str]:
    """Names of other groups whose ``filteredGroups`` targets *group_prim_path*."""
    scope = stage.GetPrimAtPath(constants.SceneNamespace.PHYSICS)
    if not scope or not scope.IsValid():
        return []
    target = Sdf.Path(group_prim_path)
    dependents: list[str] = []
    for child in scope.GetChildren():
        if not usd.prim_types.is_collision_group(child):
            continue
        if str(child.GetPath()) == group_prim_path:
            continue
        rel = UsdPhysics.CollisionGroup(child).GetFilteredGroupsRel()
        if rel and target in rel.GetTargets():
            dependents.append(child.GetName())
    return dependents
