# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics joints — creating, removing and listing typed joints."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Sdf, Usd, UsdGeom

from bowerbot.schemas import (
    ASWFLayerNames,
    JointsSummary,
    JointSummary,
    PhysicsJointType,
    PhysicsNamespace,
    SceneNamespace,
)
from bowerbot.utils.core.asset_folder import (
    ensure_root_reference,
    ensure_side_layer,
    find_root_file,
    resolve_default_prim_name,
)
from bowerbot.utils.core.attributes import set_prim_attribute
from bowerbot.utils.core.naming import validate_prim_name
from bowerbot.utils.core.schema_registry import schema_class
from bowerbot.utils.core.values import usd_to_json
from bowerbot.utils.physics.predicates import is_joint
from bowerbot.utils.physics.scene import ensure_physics_scene
from bowerbot.utils.physics.schema_info import list_joint_properties, refuse_unknown

logger = logging.getLogger(__name__)


def create_joint_scene(
    stage: Usd.Stage,
    joint_type: PhysicsJointType,
    name: str,
    body0: str | None,
    body1: str | None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a typed joint at ``/Scene/Physics/<name>``; auto-ensures a ``UsdPhysics.Scene``."""
    validate_prim_name(name, "Joint")
    attributes = attributes or {}
    _validate_joint_bodies(stage, body0, body1)
    refuse_unknown(list_joint_properties(joint_type), attributes, "attribute")

    ensure_physics_scene(stage)
    prim_path = f"{SceneNamespace.PHYSICS}/{name}"
    joint = schema_class(joint_type).Define(stage, prim_path)

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


def create_joint_asset(
    asset_dir: Path,
    joint_type: PhysicsJointType,
    name: str,
    body0: str | None,
    body1: str | None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a typed joint in the asset's ``phy.usda`` at ``/<default>/joints/<name>``."""
    validate_prim_name(name, "Joint")
    attributes = attributes or {}
    refuse_unknown(list_joint_properties(joint_type), attributes, "attribute")

    root_file = find_root_file(asset_dir)
    if root_file is None:
        raise ValueError(f"No root file in asset {asset_dir.name}")
    composed = Usd.Stage.Open(str(root_file))
    _validate_joint_bodies(composed, body0, body1)
    del composed

    stage = Usd.Stage.Open(str(ensure_side_layer(asset_dir, ASWFLayerNames.PHY)))
    default_prim_name = resolve_default_prim_name(asset_dir)
    joints_scope_path = f"/{default_prim_name}/{PhysicsNamespace.JOINTS_SCOPE}"
    if not stage.GetPrimAtPath(joints_scope_path).IsValid():
        stage.DefinePrim(joints_scope_path, "Scope")

    prim_path = f"{joints_scope_path}/{name}"
    joint = schema_class(joint_type).Define(stage, prim_path)

    _set_body_rel(joint, "physics:body0", body0)
    _set_body_rel(joint, "physics:body1", body1)
    _author_joint_attributes(joint, attributes, joint_type)

    stage.Save()
    ensure_root_reference(asset_dir, ASWFLayerNames.PHY)

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


def remove_joint_scene(stage: Usd.Stage, prim_path: str) -> bool:
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


def remove_joint_asset(asset_dir: Path, name: str) -> bool:
    """Remove an asset-level joint prim from ``phy.usda``."""
    phy_path = asset_dir / ASWFLayerNames.PHY
    if not phy_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is None:
        return False
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_path = f"/{default_prim_name}/{PhysicsNamespace.JOINTS_SCOPE}/{name}"
    if layer.GetPrimAtPath(prim_path) is None:
        return False
    edit = Sdf.BatchNamespaceEdit()
    edit.Add(Sdf.Path(prim_path), Sdf.Path.emptyPath)
    if not layer.Apply(edit):
        return False
    layer.Save()
    return True


def list_joints_scene(
    stage: Usd.Stage, under_prim_path: str | None = None,
) -> JointsSummary:
    """Return every supported joint prim under *under_prim_path* (default scene root)."""
    root = (
        stage.GetPrimAtPath(under_prim_path)
        if under_prim_path else stage.GetPseudoRoot()
    )
    if not root or not root.IsValid():
        return JointsSummary()
    joints: list[JointSummary] = []
    for prim in Usd.PrimRange(root):
        if is_joint(prim):
            joints.append(_summarize_joint(prim))
    return JointsSummary(joints=joints)


def list_joints_asset(asset_dir: Path) -> JointsSummary:
    """Return every joint prim authored in the asset's ``phy.usda``."""
    phy_path = asset_dir / ASWFLayerNames.PHY
    if not phy_path.exists():
        return JointsSummary()
    stage = Usd.Stage.Open(str(phy_path))
    if stage is None:
        return JointsSummary()
    return list_joints_scene(stage)


def format_joint_prim(prim: Usd.Prim) -> dict:
    """Format a UsdPhysics joint for ``list_prims``."""
    body0_rel = prim.GetRelationship("physics:body0")
    body1_rel = prim.GetRelationship("physics:body1")
    body0 = [str(t) for t in body0_rel.GetTargets()] if body0_rel else []
    body1 = [str(t) for t in body1_rel.GetTargets()] if body1_rel else []
    return {
        "prim_path": str(prim.GetPath()),
        "kind": "joint",
        "type": str(prim.GetTypeName()),
        "body0": body0[0] if body0 else None,
        "body1": body1[0] if body1 else None,
    }


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
    joint, attributes: dict[str, Any], joint_type: PhysicsJointType,
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
        set_prim_attribute(
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
    return type_name in {jt.value for jt in PhysicsJointType}


def _summarize_joint(prim: Usd.Prim) -> JointSummary:
    """Read a joint prim into a summary."""
    type_name = prim.GetTypeName()
    body0_rel = prim.GetRelationship("physics:body0")
    body1_rel = prim.GetRelationship("physics:body1")
    body0_targets = list(body0_rel.GetTargets()) if body0_rel else []
    body1_targets = list(body1_rel.GetTargets()) if body1_rel else []

    attrs: dict[str, Any] = {}
    for a in prim.GetAttributes():
        name = a.GetName()
        if not name.startswith("physics:"):
            continue
        if name in ("physics:body0", "physics:body1"):
            continue
        if not a.HasAuthoredValue():
            continue
        attrs[name] = usd_to_json(a.Get())

    return JointSummary(
        prim_path=str(prim.GetPath()),
        joint_type=str(type_name),
        body0=str(body0_targets[0]) if body0_targets else None,
        body1=str(body1_targets[0]) if body1_targets else None,
        attributes=attrs,
        applied_apis=list(prim.GetAppliedSchemas()),
    )
