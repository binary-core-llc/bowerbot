# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics APIs — applying and removing UsdPhysics APIs, in an asset or in the scene."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Sdf, Usd

from bowerbot.schemas import (
    ASWFLayerNames,
    PhysicsApiName,
    PhysicsRules,
)
from bowerbot.utils.core.asset_folder import (
    ensure_root_reference,
    ensure_side_layer,
    find_root_file,
)
from bowerbot.utils.core.attributes import set_prim_attribute
from bowerbot.utils.core.overrides import prune_empty_overrides
from bowerbot.utils.core.schema_registry import schema_class
from bowerbot.utils.physics.scene import ensure_physics_scene
from bowerbot.utils.physics.schema_info import (
    list_api_properties,
    refuse_unknown,
    validate_instance_name,
)
from bowerbot.utils.physics.summary import read_api_schemas

logger = logging.getLogger(__name__)


def apply_api(
    asset_dir: Path,
    prim_path: str,
    api_name: PhysicsApiName,
    attributes: dict[str, Any] | None = None,
    relationships: dict[str, list[str]] | None = None,
    *,
    instance_name: str | None = None,
) -> dict[str, Any]:
    """Apply ``api_name`` to *prim_path* and author opinions in ``phy.usda``."""
    attributes = attributes or {}
    relationships = relationships or {}
    is_multi = api_name in PhysicsRules.MULTI_APPLY_APIS

    schema_info = list_api_properties(
        api_name, instance_name=instance_name,
    )
    refuse_unknown(schema_info, attributes, "attribute")
    refuse_unknown(schema_info, relationships, "relationship")

    root_file = find_root_file(asset_dir)
    if root_file is None:
        raise ValueError(f"No root file in asset {asset_dir.name}")

    composed = Usd.Stage.Open(str(root_file))
    requested = composed.GetPrimAtPath(prim_path)
    if not requested or not requested.IsValid():
        raise ValueError(
            f"Prim not found in asset {asset_dir.name}: {prim_path}",
        )

    instance: str | None = None
    if is_multi:
        instance = validate_instance_name(
            api_name, instance_name, requested.GetTypeName(),
        )
        target_path = str(requested.GetPath())
    else:
        target = resolve_typed_target(requested, api_name)
        target_path = str(target.GetPath())
        if api_name == PhysicsApiName.ARTICULATION_ROOT:
            check_articulation_root_nesting(composed, target_path)
    del composed

    stage = Usd.Stage.Open(str(ensure_side_layer(asset_dir, ASWFLayerNames.PHY)))
    prim = stage.OverridePrim(Sdf.Path(target_path))

    companion = PhysicsRules.COMPANIONS.get(api_name)
    if companion is not None:
        schema_class(companion).Apply(prim)
    if instance is not None:
        _apply_multi(prim, api_name, instance)
    else:
        schema_class(api_name).Apply(prim)

    for name, value in attributes.items():
        attr = prim.GetAttribute(name)
        set_prim_attribute(
            stage, target_path, name, value,
            expected_type=attr.GetTypeName(),
        )

    for name, targets in relationships.items():
        prim.GetRelationship(name).SetTargets(
            [Sdf.Path(t) for t in targets],
        )

    stage.Save()
    ensure_root_reference(asset_dir, ASWFLayerNames.PHY)

    logger.info(
        "Applied %s%s on %s in %s/phy.usda",
        api_name.value,
        f":{instance_name}" if instance_name else "",
        target_path, asset_dir.name,
    )
    return {
        "prim_path": target_path,
        "requested_prim_path": prim_path,
        "api_name": api_name.value,
        "instance_name": instance_name,
        "companion_api": companion.value if companion else None,
        "attributes_set": sorted(attributes),
        "relationships_set": sorted(relationships),
    }


def remove_api(
    asset_dir: Path,
    prim_path: str,
    api_name: PhysicsApiName,
    *,
    instance_name: str | None = None,
) -> bool:
    """Remove ``api_name`` (and any dependent APIs) from *prim_path*."""
    phy_path = asset_dir / ASWFLayerNames.PHY
    if not phy_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is None:
        return False
    return _remove_api_from_layer(
        layer, prim_path, api_name, instance_name=instance_name,
    )


def apply_api_scene(
    stage: Usd.Stage,
    prim_path: str,
    api_name: PhysicsApiName,
    attributes: dict[str, Any] | None = None,
    relationships: dict[str, list[str]] | None = None,
    *,
    instance_name: str | None = None,
) -> dict[str, Any]:
    """Apply ``api_name`` on scene.usda; auto-ensures a ``UsdPhysics.Scene``."""
    attributes = attributes or {}
    relationships = relationships or {}
    is_multi = api_name in PhysicsRules.MULTI_APPLY_APIS

    schema_info = list_api_properties(
        api_name, instance_name=instance_name,
    )
    refuse_unknown(schema_info, attributes, "attribute")
    refuse_unknown(schema_info, relationships, "relationship")
    ensure_physics_scene(stage)

    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found in scene: {prim_path}")

    instance: str | None = None
    if is_multi:
        instance = validate_instance_name(
            api_name, instance_name, prim.GetTypeName(),
        )
        target = prim
        target_path = prim_path
    else:
        target = resolve_typed_target(prim, api_name)
        target_path = str(target.GetPath())
        if api_name == PhysicsApiName.ARTICULATION_ROOT:
            check_articulation_root_nesting(stage, target_path)

    companion = PhysicsRules.COMPANIONS.get(api_name)
    if companion is not None:
        schema_class(companion).Apply(target)
    if instance is not None:
        _apply_multi(target, api_name, instance)
    else:
        schema_class(api_name).Apply(target)

    for name, value in attributes.items():
        attr = target.GetAttribute(name)
        set_prim_attribute(
            stage, target_path, name, value,
            expected_type=attr.GetTypeName(),
        )

    for name, targets in relationships.items():
        target.GetRelationship(name).SetTargets(
            [Sdf.Path(t) for t in targets],
        )

    stage.Save()
    logger.info(
        "Applied %s%s scene-level on %s",
        api_name.value,
        f":{instance_name}" if instance_name else "",
        prim_path,
    )
    return {
        "prim_path": target_path,
        "requested_prim_path": prim_path,
        "api_name": api_name.value,
        "instance_name": instance_name,
        "companion_api": companion.value if companion else None,
        "attributes_set": sorted(attributes),
        "relationships_set": sorted(relationships),
        "scope": "scene",
    }


def remove_api_scene(
    stage: Usd.Stage,
    prim_path: str,
    api_name: PhysicsApiName,
    *,
    instance_name: str | None = None,
) -> bool:
    """Remove ``api_name`` opinions from scene.usda at *prim_path*."""
    return _remove_api_from_layer(
        stage.GetRootLayer(), prim_path, api_name,
        instance_name=instance_name,
    )


def resolve_typed_target(
    prim: Usd.Prim, api_name: PhysicsApiName,
) -> Usd.Prim:
    """Return *prim* or its unique descendant matching the API's target type."""
    cls = schema_class(PhysicsRules.TARGET_TYPES[api_name])
    if prim.IsA(cls):
        return prim
    candidates = [
        d for d in Usd.PrimRange(prim) if d != prim and d.IsA(cls)
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(
            f"{api_name.value} requires UsdGeom.{cls.__name__}; "
            f"{prim.GetPath()} is a {prim.GetTypeName()!r} with no "
            f"{cls.__name__} descendants.",
        )
    raise ValueError(
        f"{api_name.value} requires UsdGeom.{cls.__name__}; "
        f"{prim.GetPath()} is a {prim.GetTypeName()!r} with "
        f"{len(candidates)} {cls.__name__} descendants. Pick one and "
        f"retry: {[str(c.GetPath()) for c in candidates]}",
    )


def check_articulation_root_nesting(stage: Usd.Stage, prim_path: str) -> None:
    """Refuse if any ancestor or descendant already has ``ArticulationRootAPI``.

    The UsdPhysics spec forbids nesting two ArticulationRootAPIs in the
    same subtree; call this before applying it on a new prim.
    """
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return

    api = "PhysicsArticulationRootAPI"
    cursor = prim.GetParent()
    while (
        cursor and cursor.IsValid()
        and cursor.GetPath() != Sdf.Path.absoluteRootPath
    ):
        if api in cursor.GetAppliedSchemas():
            raise ValueError(
                f"Cannot apply ArticulationRootAPI on {prim_path}: "
                f"ancestor {cursor.GetPath()} already has it. The "
                "UsdPhysics spec forbids nesting two ArticulationRootAPIs "
                "in the same subtree.",
            )
        cursor = cursor.GetParent()

    for descendant in Usd.PrimRange(prim):
        if descendant.GetPath() == prim.GetPath():
            continue
        if api in descendant.GetAppliedSchemas():
            raise ValueError(
                f"Cannot apply ArticulationRootAPI on {prim_path}: "
                f"descendant {descendant.GetPath()} already has it. The "
                "UsdPhysics spec forbids nesting two ArticulationRootAPIs "
                "in the same subtree.",
            )


def _apply_multi(prim: Usd.Prim, api_name: PhysicsApiName, instance_name: str) -> None:
    """Apply a multi-apply API with the given instance name."""
    schema_class(api_name).Apply(prim, instance_name)


def _remove_api_from_layer(
    layer: Sdf.Layer,
    prim_path: str,
    api_name: PhysicsApiName,
    *,
    instance_name: str | None = None,
) -> bool:
    """Drop ``api_name`` + dependents + their opinions from *layer*."""
    prim_spec = layer.GetPrimAtPath(prim_path)
    if prim_spec is None:
        return False

    authored = set(read_api_schemas(prim_spec))
    targets: list[PhysicsApiName] = [api_name]
    for dependent in PhysicsRules.DEPENDENTS.get(api_name, ()):
        if dependent.value in authored:
            targets.append(dependent)

    touched = False
    for name in targets:
        token = (
            f"{name.value}:{instance_name}"
            if name in PhysicsRules.MULTI_APPLY_APIS and instance_name
            else name.value
        )
        if _drop_from_api_listop(prim_spec, token):
            touched = True
        props = list_api_properties(
            name,
            instance_name=instance_name if name in PhysicsRules.MULTI_APPLY_APIS else None,
        )
        for prop in props.properties:
            container = (
                prim_spec.attributes if prop.kind == "attribute"
                else prim_spec.relationships
            )
            spec = container.get(prop.name)
            if spec is not None:
                prim_spec.RemoveProperty(spec)
                touched = True

    if touched:
        layer.Save()
        prune_empty_overrides(layer, prim_path)
    return touched


def _drop_from_api_listop(prim_spec: Sdf.PrimSpec, api_name: str) -> bool:
    """Drop *api_name* from prim's apiSchemas list-op; True if changed."""
    list_op = prim_spec.GetInfo("apiSchemas")
    if list_op is None:
        return False
    new_op = Sdf.TokenListOp()
    touched = False
    for slot in ("prependedItems", "appendedItems", "explicitItems"):
        items = list(getattr(list_op, slot, ()))
        if api_name in items:
            items.remove(api_name)
            touched = True
        setattr(new_op, slot, items)
    if touched:
        prim_spec.SetInfo("apiSchemas", new_op)
    return touched
