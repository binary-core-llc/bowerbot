# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Joints, in the scene or in an asset's ``phy.usda``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import physics
from bowerbot.utils import usd

logger = logging.getLogger(__name__)


def list_properties(joint_type: schemas.PhysicsJointType) -> schemas.PhysicsApiSchemaInfo:
    """Schema-registry view of every property a typed joint declares."""
    prim_def = Usd.SchemaRegistry().FindConcretePrimDefinition(joint_type.value)
    if prim_def is None:
        raise ValueError(
            f"USD schema registry does not know {joint_type.value}. "
            "USD build is missing UsdPhysics.",
        )

    properties: list[schemas.PhysicsPropertySpec] = []
    for prop_name in prim_def.GetPropertyNames():
        attr_spec = prim_def.GetSchemaAttributeSpec(prop_name)
        if attr_spec is not None:
            properties.append(schemas.PhysicsPropertySpec(
                name=prop_name,
                kind="attribute",
                type_name=str(attr_spec.typeName),
                default=usd.values.to_jsonable(attr_spec.default),
                allowed_tokens=[
                    str(t) for t in (attr_spec.allowedTokens or [])
                ],
                documentation=usd.attributes.property_doc(prim_def, prop_name, attr_spec),
            ))
            continue
        rel_spec = prim_def.GetSchemaRelationshipSpec(prop_name)
        if rel_spec is not None:
            properties.append(schemas.PhysicsPropertySpec(
                name=prop_name,
                kind="relationship",
                documentation=usd.attributes.property_doc(prim_def, prop_name, rel_spec),
            ))

    return schemas.PhysicsApiSchemaInfo(
        api_name=joint_type.value,
        target_requirement="(typed prim)",
        properties=properties,
    )


def create_in_scene(
    stage: Usd.Stage,
    joint_type: schemas.PhysicsJointType,
    name: str,
    body0: str | None,
    body1: str | None,
    attributes: dict[str, Any] | None = None,
    *,
    project_mpu: float,
    project_up_axis: str,
) -> dict[str, Any]:
    """Create a typed joint at ``/Scene/Physics/<name>``; auto-ensures a ``UsdPhysics.Scene``."""
    usd.naming.validate_joint_name(name)
    attributes = attributes or {}
    _validate_joint_bodies(stage, body0, body1)
    _refuse_unknown_joint_properties(joint_type, attributes)

    physics.scenes.ensure(stage, project_mpu=project_mpu, project_up_axis=project_up_axis)
    prim_path = f"{constants.SceneNamespace.PHYSICS}/{name}"
    joint = constants.PhysicsUsd.JOINTS[joint_type].Define(stage, prim_path)

    _set_body_rel(joint, "physics:body0", body0)
    _set_body_rel(joint, "physics:body1", body1)
    _author_joint_attributes(joint, attributes, joint_type)

    stage.Save()
    logger.info(
        "Created %s scene-level at %s (body0=%s, body1=%s)",
        joint_type.value, prim_path, body0, body1,
    )
    return {
        "prim_path": prim_path,
        "joint_type": joint_type.value,
        "scope": "scene",
        "body0": body0,
        "body1": body1,
        "attributes_set": sorted(attributes),
    }


def create_in_asset(
    asset_dir: Path,
    joint_type: schemas.PhysicsJointType,
    name: str,
    body0: str | None,
    body1: str | None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a typed joint in the asset's ``phy.usda`` at ``/<default>/joints/<name>``."""
    usd.naming.validate_joint_name(name)
    attributes = attributes or {}
    _refuse_unknown_joint_properties(joint_type, attributes)

    root_file = authoring.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        raise ValueError(f"No root file in asset {asset_dir.name}")
    composed = Usd.Stage.Open(str(root_file))
    _validate_joint_bodies(composed, body0, body1)
    del composed

    physics.layer.ensure(asset_dir)
    stage = Usd.Stage.Open(str(physics.layer.file_path(asset_dir)))
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    joints_scope_path = f"/{default_prim_name}/{constants.PhysicsNamespace.JOINTS_SCOPE}"
    if not stage.GetPrimAtPath(joints_scope_path).IsValid():
        stage.DefinePrim(joints_scope_path, "Scope")

    prim_path = f"{joints_scope_path}/{name}"
    joint = constants.PhysicsUsd.JOINTS[joint_type].Define(stage, prim_path)

    _set_body_rel(joint, "physics:body0", body0)
    _set_body_rel(joint, "physics:body1", body1)
    _author_joint_attributes(joint, attributes, joint_type)

    stage.Save()
    authoring.asset_folder.ensure_root_reference(asset_dir, constants.ASWFLayerNames.PHY)

    logger.info(
        "Created %s asset-level at %s in %s/phy.usda",
        joint_type.value, prim_path, asset_dir.name,
    )
    return {
        "prim_path": prim_path,
        "joint_type": joint_type.value,
        "scope": "asset",
        "asset_folder": asset_dir.name,
        "body0": body0,
        "body1": body1,
        "attributes_set": sorted(attributes),
    }


def remove_from_scene(stage: Usd.Stage, prim_path: str) -> bool:
    """Remove a scene-level joint prim from ``scene.usda``."""
    layer = stage.GetRootLayer()
    spec = layer.GetPrimAtPath(prim_path)
    if spec is None:
        return False
    if not _is_supported_joint_spec(spec):
        return False
    edit = Sdf.BatchNamespaceEdit()
    edit.Add(Sdf.Path(prim_path), Sdf.Path.emptyPath)
    if not layer.Apply(edit):
        return False
    layer.Save()
    return True


def remove_from_asset(asset_dir: Path, name: str) -> bool:
    """Remove an asset-level joint prim from ``phy.usda``."""
    phy_path = physics.layer.file_path(asset_dir)
    if not phy_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is None:
        return False
    default_prim_name = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    prim_path = f"/{default_prim_name}/{constants.PhysicsNamespace.JOINTS_SCOPE}/{name}"
    if layer.GetPrimAtPath(prim_path) is None:
        return False
    edit = Sdf.BatchNamespaceEdit()
    edit.Add(Sdf.Path(prim_path), Sdf.Path.emptyPath)
    if not layer.Apply(edit):
        return False
    layer.Save()
    return True


def list_on_stage(
    stage: Usd.Stage, under_prim_path: str | None = None,
) -> schemas.JointsSummary:
    """Return every supported joint prim under *under_prim_path* (default scene root)."""
    root = (
        stage.GetPrimAtPath(under_prim_path)
        if under_prim_path else stage.GetPseudoRoot()
    )
    if not root or not root.IsValid():
        return schemas.JointsSummary()
    joints: list[schemas.JointSummary] = []
    for prim in Usd.PrimRange(root):
        if usd.prim_types.is_joint(prim):
            joints.append(_summarize_joint(prim))
    return schemas.JointsSummary(joints=joints)


def list_in_asset(asset_dir: Path) -> schemas.JointsSummary:
    """Return every joint prim authored in the asset's ``phy.usda``."""
    phy_path = physics.layer.file_path(asset_dir)
    if not phy_path.exists():
        return schemas.JointsSummary()
    stage = Usd.Stage.Open(str(phy_path))
    if stage is None:
        return schemas.JointsSummary()
    return list_on_stage(stage)


# ── Helpers ──


def _validate_joint_bodies(
    stage: Usd.Stage, body0: str | None, body1: str | None,
) -> None:
    """Refuse if neither body reaches a RigidBodyAPI, or targets are not Xformable."""
    if not body0 and not body1:
        raise ValueError(
            "Joint must reference at least one body. Both body0 and "
            "body1 are empty; the joint would have nothing to connect.",
        )

    reaches_rigid_body = False
    for label, path in (("body0", body0), ("body1", body1)):
        if not path:
            continue
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.IsValid():
            raise ValueError(f"Joint {label} prim not found: {path}")
        if not prim.IsA(UsdGeom.Xformable):
            raise ValueError(
                f"Joint {label} must be a UsdGeom.Xformable; "
                f"{path} is a {prim.GetTypeName()!r}",
            )
        if _ancestor_has_api(prim, "PhysicsRigidBodyAPI"):
            reaches_rigid_body = True

    if not reaches_rigid_body:
        raise ValueError(
            "Joint must connect to at least one prim that reaches "
            "PhysicsRigidBodyAPI (self or ancestor). Neither "
            f"{body0!r} nor {body1!r} does. Apply RigidBodyAPI to one "
            "of them first.",
        )


def _refuse_unknown_joint_properties(
    joint_type: schemas.PhysicsJointType, attributes: dict[str, Any],
) -> None:
    """Refuse attribute names the joint schema does not declare."""
    info = list_properties(joint_type)
    valid = {
        p.name for p in info.properties
        if p.kind == "attribute" and not p.name.startswith(
            ("physics:body0", "physics:body1"),
        )
    }
    unknown = sorted(n for n in attributes if n not in valid)
    if unknown:
        raise ValueError(
            f"{joint_type.value} does not declare attribute(s) {unknown}. "
            f"Allowed: {sorted(valid)}",
        )


def _set_body_rel(joint, rel_name: str, target_path: str | None) -> None:
    """Author the body0 / body1 rel. Empty/None target = world (no targets set)."""
    rel = joint.GetPrim().GetRelationship(rel_name)
    if not rel or not rel.IsValid():
        rel = joint.GetPrim().CreateRelationship(rel_name, custom=False)
    if target_path:
        rel.SetTargets([Sdf.Path(target_path)])
    else:
        rel.SetTargets([])


def _author_joint_attributes(
    joint, attributes: dict[str, Any], joint_type: schemas.PhysicsJointType,
) -> None:
    """Set caller-provided joint attributes after typed-prim definition."""
    prim = joint.GetPrim()
    for name, value in attributes.items():
        attr = prim.GetAttribute(name)
        if not attr or not attr.IsValid():
            raise ValueError(
                f"Attribute {name!r} not resolvable on {joint_type.value} "
                f"at {prim.GetPath()}",
            )
        usd.attributes.set_prim_attribute(
            prim.GetStage(), str(prim.GetPath()), name, value,
            expected_type=attr.GetTypeName(),
        )


def _ancestor_has_api(prim: Usd.Prim, api_name: str) -> bool:
    """Whether *prim* or any of its ancestors has *api_name* in apiSchemas."""
    cursor = prim
    while cursor and cursor.IsValid() and cursor.GetPath() != Sdf.Path.absoluteRootPath:
        applied = cursor.GetAppliedSchemas()
        if any(s.split(":")[0] == api_name for s in applied):
            return True
        cursor = cursor.GetParent()
    return False


def _is_supported_joint_spec(spec: Sdf.PrimSpec) -> bool:
    """Spec-side check (no stage) for joint typeName in our whitelist."""
    type_name = str(spec.typeName) if spec.typeName else ""
    return type_name in {jt.value for jt in schemas.PhysicsJointType}


def _summarize_joint(prim: Usd.Prim) -> schemas.JointSummary:
    """Read a joint prim into a summary."""
    type_name = prim.GetTypeName()
    body0, body1 = usd.prim_types.joint_bodies(prim)

    attrs: dict[str, Any] = {}
    for a in prim.GetAttributes():
        name = a.GetName()
        if not name.startswith("physics:"):
            continue
        if name in ("physics:body0", "physics:body1"):
            continue
        if not a.HasAuthoredValue():
            continue
        attrs[name] = usd.values.to_jsonable(a.Get())

    return schemas.JointSummary(
        prim_path=str(prim.GetPath()),
        joint_type=str(type_name),
        body0=body0,
        body1=body1,
        attributes=attrs,
        applied_apis=list(prim.GetAppliedSchemas()),
    )
