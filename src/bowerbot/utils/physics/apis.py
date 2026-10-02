# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Applying and removing UsdPhysics APIs, in an asset's ``phy.usda`` or in the scene."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Sdf
from pxr import Usd

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import physics
from bowerbot.utils import usd

logger = logging.getLogger(__name__)


def list_properties(
    api_name: schemas.PhysicsApiName,
    *,
    instance_name: str | None = None,
) -> schemas.PhysicsApiSchemaInfo:
    """Live schema-registry view of every property the API declares.

    For multi-apply APIs (DriveAPI, LimitAPI) *instance_name* is
    required; property names are returned with the instance substituted
    (e.g. ``drive:angular:physics:stiffness``).
    """
    if api_name in constants.PhysicsRules.MULTI_APPLY_APIS and not instance_name:
        raise ValueError(
            f"{api_name.value} is a multi-apply API. "
            "Provide instance_name (e.g. 'angular', 'linear').",
        )

    prim_def = Usd.SchemaRegistry().FindAppliedAPIPrimDefinition(
        api_name.value,
    )
    if prim_def is None:
        raise ValueError(
            f"USD schema registry does not know {api_name.value}. "
            "USD build is missing UsdPhysics.",
        )

    properties: list[schemas.SchemaPropertySpec] = []
    for prop_name in prim_def.GetPropertyNames():
        real_name = (
            prop_name.replace(constants.PhysicsRules.INSTANCE_NAME_PLACEHOLDER, instance_name)
            if instance_name else prop_name
        )
        row = usd.attributes.schema_property_row(prim_def, prop_name, name=real_name)
        if row is not None:
            properties.append(row)

    target_req = (
        "UsdPhysics joint prim" if api_name in constants.PhysicsRules.MULTI_APPLY_APIS
        else f"UsdGeom.{constants.PhysicsUsd.API_TARGETS[api_name].__name__}"
    )
    companion = constants.PhysicsRules.COMPANION_APIS.get(api_name)
    return schemas.PhysicsApiSchemaInfo(
        api_name=api_name.value,
        target_requirement=target_req,
        requires_companion_api=companion.value if companion else None,
        properties=properties,
    )


def validate_instance_name(
    api_name: schemas.PhysicsApiName,
    instance_name: str,
    joint_type_name: str,
) -> None:
    """Refuse if *instance_name* is invalid for *api_name* on *joint_type*."""
    try:
        jt = schemas.PhysicsJointType(joint_type_name)
    except ValueError:
        raise ValueError(
            f"{api_name.value} can only be applied to a UsdPhysics "
            f"joint prim; got type {joint_type_name!r}.",
        ) from None

    valid = constants.PhysicsRules.INSTANCES_BY_API[api_name].get(jt, frozenset())
    if not valid:
        raise ValueError(
            f"{api_name.value} is not supported on {jt.value}.",
        )
    if instance_name not in valid:
        raise ValueError(
            f"instance_name {instance_name!r} is not valid for "
            f"{api_name.value} on {jt.value}. "
            f"Allowed: {sorted(valid)}",
        )


def apply_in_asset(
    asset_dir: Path,
    prim_path: str,
    api_name: schemas.PhysicsApiName,
    attributes: dict[str, Any] | None = None,
    relationships: dict[str, list[str]] | None = None,
    *,
    instance_name: str | None = None,
    scene_stage: Usd.Stage,
) -> dict[str, Any]:
    """Apply ``api_name`` to *prim_path* and author opinions in ``phy.usda``.

    Refused when *scene_stage* (the scene the asset is placed in) would then
    have a physics error it does not have now.
    """
    attributes = attributes or {}
    relationships = relationships or {}
    is_multi = api_name in constants.PhysicsRules.MULTI_APPLY_APIS

    schema_info = list_properties(
        api_name, instance_name=instance_name,
    )
    _refuse_unknown(api_name, attributes, schema_info, "attribute")
    _refuse_unknown(api_name, relationships, schema_info, "relationship")

    root_file = authoring.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        raise ValueError(f"No root file in asset {asset_dir.name}")

    composed = Usd.Stage.Open(str(root_file))
    requested = composed.GetPrimAtPath(prim_path)
    if not requested or not requested.IsValid():
        raise ValueError(
            f"Prim not found in asset {asset_dir.name}: {prim_path}",
        )

    if is_multi:
        validate_instance_name(
            api_name, instance_name, requested.GetTypeName(),
        )
        target_path = str(requested.GetPath())
    else:
        target = resolve_typed_target(requested, api_name)
        target_path = str(target.GetPath())
        if api_name == schemas.PhysicsApiName.ARTICULATION_ROOT:
            refuse_nested_articulation_root(composed, target_path)
    del composed

    known = physics.rules.errors(scene_stage)
    stage = physics.layer.open_for_edit(asset_dir)
    prim = stage.OverridePrim(Sdf.Path(target_path))

    companion = constants.PhysicsRules.COMPANION_APIS.get(api_name)
    if companion is not None:
        constants.PhysicsUsd.APIS[companion].Apply(prim)
    if is_multi:
        _apply_multi(prim, api_name, instance_name)
    else:
        constants.PhysicsUsd.APIS[api_name].Apply(prim)

    for name, value in attributes.items():
        attr = prim.GetAttribute(name)
        usd.attributes.set_prim_attribute(
            stage, target_path, name, value,
            expected_type=attr.GetTypeName(),
        )

    for name, targets in relationships.items():
        prim.GetRelationship(name).SetTargets(
            [Sdf.Path(t) for t in targets],
        )

    physics.layer.save_edit(
        asset_dir, stage, scene_stage, known,
        f"Applying {api_name.value} to {target_path} in asset {asset_dir.name}",
    )

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


def remove_from_asset(
    asset_dir: Path,
    prim_path: str,
    api_name: schemas.PhysicsApiName,
    *,
    instance_name: str | None = None,
    scene_stage: Usd.Stage,
) -> bool:
    """Remove ``api_name`` (and any dependent APIs) from *prim_path*.

    Refused when *scene_stage* would then have a physics error it does not have now.
    """
    phy_path = physics.layer.file_path(asset_dir)
    if not phy_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is None:
        return False
    return _remove_api_from_layer(
        layer, prim_path, api_name, instance_name=instance_name, scene_stage=scene_stage,
        doing=f"Removing {api_name.value} from {prim_path} in asset {asset_dir.name}",
    )


def apply_in_scene(
    stage: Usd.Stage,
    prim_path: str,
    api_name: schemas.PhysicsApiName,
    attributes: dict[str, Any] | None = None,
    relationships: dict[str, list[str]] | None = None,
    *,
    instance_name: str | None = None,
    project_mpu: float,
    project_up_axis: str,
) -> dict[str, Any]:
    """Apply ``api_name`` on scene.usda; auto-ensures a ``UsdPhysics.Scene``."""
    attributes = attributes or {}
    relationships = relationships or {}
    is_multi = api_name in constants.PhysicsRules.MULTI_APPLY_APIS

    schema_info = list_properties(
        api_name, instance_name=instance_name,
    )
    _refuse_unknown(api_name, attributes, schema_info, "attribute")
    _refuse_unknown(api_name, relationships, schema_info, "relationship")
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found in scene: {prim_path}")
    known = physics.rules.errors(stage)
    physics.scenes.ensure_default(
        stage, project_mpu=project_mpu, project_up_axis=project_up_axis,
    )

    if is_multi:
        validate_instance_name(
            api_name, instance_name, prim.GetTypeName(),
        )
        target = prim
        target_path = prim_path
    else:
        target = resolve_typed_target(prim, api_name)
        target_path = str(target.GetPath())
        if api_name == schemas.PhysicsApiName.ARTICULATION_ROOT:
            refuse_nested_articulation_root(stage, target_path)

    companion = constants.PhysicsRules.COMPANION_APIS.get(api_name)
    if companion is not None:
        constants.PhysicsUsd.APIS[companion].Apply(target)
    if is_multi:
        _apply_multi(target, api_name, instance_name)
    else:
        constants.PhysicsUsd.APIS[api_name].Apply(target)

    for name, value in attributes.items():
        attr = target.GetAttribute(name)
        usd.attributes.set_prim_attribute(
            stage, target_path, name, value,
            expected_type=attr.GetTypeName(),
        )

    for name, targets in relationships.items():
        target.GetRelationship(name).SetTargets(
            [Sdf.Path(t) for t in targets],
        )

    physics.rules.refuse_new_errors(
        stage, known, f"Applying {api_name.value} to {target_path}",
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


def remove_from_scene(
    stage: Usd.Stage,
    prim_path: str,
    api_name: schemas.PhysicsApiName,
    *,
    instance_name: str | None = None,
) -> bool:
    """Remove ``api_name`` opinions from scene.usda at *prim_path*.

    Refused when the scene would then have a physics error it does not have now.
    """
    return _remove_api_from_layer(
        stage.GetRootLayer(), prim_path, api_name,
        instance_name=instance_name, scene_stage=stage,
        doing=f"Removing {api_name.value} from {prim_path}",
    )


def resolve_typed_target(
    prim: Usd.Prim, api_name: schemas.PhysicsApiName,
) -> Usd.Prim:
    """Return *prim* or its unique descendant matching the API's target type."""
    cls = constants.PhysicsUsd.API_TARGETS[api_name]
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


def refuse_nested_articulation_root(stage: Usd.Stage, prim_path: str) -> None:
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


def read_api_schemas(prim_spec: Sdf.PrimSpec) -> list[str]:
    """Union of every apiSchemas list-op slot on *prim_spec*."""
    list_op = prim_spec.GetInfo("apiSchemas")
    if list_op is None:
        return []
    apis: list[str] = []
    for slot in ("prependedItems", "appendedItems", "explicitItems"):
        apis.extend(getattr(list_op, slot, ()))
    return apis


# ── Helpers ──


def _apply_multi(prim: Usd.Prim, api_name: schemas.PhysicsApiName, instance_name: str) -> None:
    """Apply a multi-apply API with the given instance name."""
    constants.PhysicsUsd.APIS[api_name].Apply(prim, instance_name)


def _refuse_unknown(
    api_name: schemas.PhysicsApiName,
    provided: dict[str, Any],
    schema_info: schemas.PhysicsApiSchemaInfo,
    kind: str,
) -> None:
    """Refuse property names the schema does not declare."""
    usd.attributes.refuse_undeclared(
        api_name.value, provided,
        {p.name for p in schema_info.properties if p.kind == kind}, kind,
    )


def _remove_api_from_layer(
    layer: Sdf.Layer,
    prim_path: str,
    api_name: schemas.PhysicsApiName,
    *,
    instance_name: str | None = None,
    scene_stage: Usd.Stage,
    doing: str,
) -> bool:
    """Drop ``api_name`` + dependents + their opinions from *layer*."""
    prim_spec = layer.GetPrimAtPath(prim_path)
    if prim_spec is None:
        return False
    known = physics.rules.errors(scene_stage)

    authored = set(read_api_schemas(prim_spec))
    targets: list[schemas.PhysicsApiName] = [api_name]
    for dependent in constants.PhysicsRules.DEPENDENT_APIS.get(api_name, ()):
        if dependent.value in authored:
            targets.append(dependent)

    touched = False
    for name in targets:
        token = (
            f"{name.value}:{instance_name}"
            if name in constants.PhysicsRules.MULTI_APPLY_APIS and instance_name
            else name.value
        )
        if usd.attributes.drop_api_schema(prim_spec, token):
            touched = True
        props = list_properties(
            name,
            instance_name=(
                instance_name if name in constants.PhysicsRules.MULTI_APPLY_APIS else None
            ),
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
        physics.rules.refuse_new_errors(scene_stage, known, doing)
        layer.Save()
        usd.namespace.prune_empty_overrides(layer, prim_path)
    return touched


