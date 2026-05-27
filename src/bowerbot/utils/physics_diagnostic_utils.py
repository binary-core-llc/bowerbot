# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics diagnostic checks; registered with the global registry at import."""

from __future__ import annotations

from pxr import Sdf, Usd, UsdGeom, UsdPhysics

from bowerbot.schemas import Finding, FindingStatus, SceneNamespace, Severity
from bowerbot.utils.diagnostic_registry_utils import register
from bowerbot.utils.physics_typing_utils import (
    is_articulation_root,
    is_joint,
    is_rigid_body,
)

_VALID_AXIS_TOKENS: frozenset[str] = frozenset({"X", "Y", "Z"})


def _iter_joints(stage: Usd.Stage) -> list[Usd.Prim]:
    return [p for p in stage.Traverse() if is_joint(p)]


def _iter_rigid_bodies(stage: Usd.Stage) -> list[Usd.Prim]:
    return [p for p in stage.Traverse() if is_rigid_body(p)]


def _joints_referencing(stage: Usd.Stage, body: Usd.Prim) -> list[Usd.Prim]:
    body_path = body.GetPath()
    out: list[Usd.Prim] = []
    for joint in _iter_joints(stage):
        for rel_name in ("physics:body0", "physics:body1"):
            rel = joint.GetRelationship(rel_name)
            if rel and body_path in list(rel.GetTargets()):
                out.append(joint)
                break
    return out


def _joint_focus_matches(stage: Usd.Stage, focus: Usd.Prim | None) -> bool:
    if focus is None or is_joint(focus):
        return True
    return bool(_joints_referencing(stage, focus))


def _joints_for_focus(
    stage: Usd.Stage, focus: Usd.Prim | None,
) -> list[Usd.Prim]:
    if focus is None:
        return _iter_joints(stage)
    if is_joint(focus):
        return [focus]
    return _joints_referencing(stage, focus)


def _ancestor_has_rigid_body(prim: Usd.Prim) -> bool:
    cursor = prim
    while cursor and cursor.IsValid() and cursor.GetPath() != Sdf.Path.absoluteRootPath:
        if "PhysicsRigidBodyAPI" in cursor.GetAppliedSchemas():
            return True
        cursor = cursor.GetParent()
    return False


def _target_prim(stage: Usd.Stage, joint: Usd.Prim, rel_name: str) -> Usd.Prim | None:
    rel = joint.GetRelationship(rel_name)
    if not rel:
        return None
    targets = list(rel.GetTargets())
    if not targets:
        return None
    return stage.GetPrimAtPath(targets[0])


def _max_half_extent(prim: Usd.Prim) -> float | None:
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    bbox = cache.ComputeWorldBound(prim).ComputeAlignedBox()
    if bbox.IsEmpty():
        return None
    half = (bbox.GetMax() - bbox.GetMin()) * 0.5
    return float(max(half[0], half[1], half[2]))


@register(
    check_id="physics:has_physics_scene",
    subsystem="physics",
    applies_to=lambda _stage, _focus: True,
)
def check_physics_scene_exists(
    stage: Usd.Stage, focus: Usd.Prim | None,
) -> list[Finding]:
    """A populated physics scene needs a UsdPhysics.Scene for the solver."""
    del focus
    has_authoring = bool(_iter_rigid_bodies(stage)) or bool(_iter_joints(stage))
    if not has_authoring:
        return []
    if any(p.IsA(UsdPhysics.Scene) for p in stage.Traverse()):
        return []
    return [Finding(
        check_id="physics:has_physics_scene",
        subsystem="physics",
        status=FindingStatus.FAIL,
        severity=Severity.ERROR,
        message=(
            "Scene has RigidBody/joint authoring but no UsdPhysics.Scene; "
            "the solver will not run."
        ),
        fix_hint=(
            f"Call setup_physics_scene to create one at "
            f"{SceneNamespace.PHYSICS}/PhysicsScene."
        ),
    )]


@register(
    check_id="physics:joint_has_body",
    subsystem="physics",
    applies_to=lambda stage, focus: _joint_focus_matches(stage, focus),
)
def check_joint_has_body(
    stage: Usd.Stage, focus: Usd.Prim | None,
) -> list[Finding]:
    """At least one of body0 / body1 must reference a target."""
    joints = _joints_for_focus(stage, focus)
    findings: list[Finding] = []
    for joint in joints:
        b0 = _target_prim(stage, joint, "physics:body0")
        b1 = _target_prim(stage, joint, "physics:body1")
        if b0 is not None or b1 is not None:
            continue
        findings.append(Finding(
            check_id="physics:joint_has_body",
            subsystem="physics",
            status=FindingStatus.FAIL,
            severity=Severity.ERROR,
            prim_path=str(joint.GetPath()),
            message="Joint has no body0 or body1 target; nothing to constrain.",
            fix_hint="Set body0 and/or body1 to an Xformable in the scene.",
        ))
    return findings


@register(
    check_id="physics:joint_reaches_rigid_body",
    subsystem="physics",
    applies_to=lambda stage, focus: _joint_focus_matches(stage, focus),
)
def check_joint_reaches_rigid_body(
    stage: Usd.Stage, focus: Usd.Prim | None,
) -> list[Finding]:
    """At least one body in the joint pair must reach PhysicsRigidBodyAPI."""
    joints = _joints_for_focus(stage, focus)
    findings: list[Finding] = []
    for joint in joints:
        bodies = [
            _target_prim(stage, joint, "physics:body0"),
            _target_prim(stage, joint, "physics:body1"),
        ]
        bodies = [b for b in bodies if b is not None]
        if not bodies or any(_ancestor_has_rigid_body(b) for b in bodies):
            continue
        findings.append(Finding(
            check_id="physics:joint_reaches_rigid_body",
            subsystem="physics",
            status=FindingStatus.FAIL,
            severity=Severity.ERROR,
            prim_path=str(joint.GetPath()),
            message=(
                "Neither connected body reaches PhysicsRigidBodyAPI; the "
                "solver will ignore this joint."
            ),
            fix_hint="Apply PhysicsRigidBodyAPI to one of the body prims.",
        ))
    return findings


@register(
    check_id="physics:joint_has_dynamic_body",
    subsystem="physics",
    applies_to=lambda stage, focus: _joint_focus_matches(stage, focus),
)
def check_joint_has_dynamic_body(
    stage: Usd.Stage, focus: Usd.Prim | None,
) -> list[Finding]:
    """A joint pair where every connected body is kinematic cannot move."""
    joints = _joints_for_focus(stage, focus)
    findings: list[Finding] = []
    for joint in joints:
        bodies = [
            _target_prim(stage, joint, "physics:body0"),
            _target_prim(stage, joint, "physics:body1"),
        ]
        rigid = [b for b in bodies if b is not None and _ancestor_has_rigid_body(b)]
        if not rigid:
            continue
        if any(not _is_kinematic(b) for b in rigid):
            continue
        findings.append(Finding(
            check_id="physics:joint_has_dynamic_body",
            subsystem="physics",
            status=FindingStatus.FAIL,
            severity=Severity.WARNING,
            prim_path=str(joint.GetPath()),
            message=(
                "Every connected rigid body is kinematic; the joint will "
                "constrain motion but nothing will move."
            ),
            fix_hint=(
                "Clear physics:kinematicEnabled on one body so the joint "
                "has a dynamic side."
            ),
        ))
    return findings


def _is_kinematic(prim: Usd.Prim) -> bool:
    attr = prim.GetAttribute("physics:kinematicEnabled")
    return bool(attr and attr.HasAuthoredValue() and attr.Get())


@register(
    check_id="physics:joint_axis_valid",
    subsystem="physics",
    applies_to=lambda stage, focus: _joint_focus_matches(stage, focus),
)
def check_joint_axis_valid(
    stage: Usd.Stage, focus: Usd.Prim | None,
) -> list[Finding]:
    """Revolute and Prismatic joints declare physics:axis in {X, Y, Z}."""
    joints = _joints_for_focus(stage, focus)
    findings: list[Finding] = []
    for joint in joints:
        if not (
            joint.IsA(UsdPhysics.RevoluteJoint)
            or joint.IsA(UsdPhysics.PrismaticJoint)
        ):
            continue
        attr = joint.GetAttribute("physics:axis")
        value = attr.Get() if attr else None
        if value in _VALID_AXIS_TOKENS:
            continue
        findings.append(Finding(
            check_id="physics:joint_axis_valid",
            subsystem="physics",
            status=FindingStatus.FAIL,
            severity=Severity.ERROR,
            prim_path=str(joint.GetPath()),
            message=(
                f"{joint.GetTypeName()} requires physics:axis in "
                f"{{X, Y, Z}}; got {value!r}."
            ),
            fix_hint="Set physics:axis via set_prim_attribute.",
        ))
    return findings


@register(
    check_id="physics:joint_local_pos_within_bounds",
    subsystem="physics",
    applies_to=lambda stage, focus: _joint_focus_matches(stage, focus),
)
def check_joint_local_pos_within_bounds(
    stage: Usd.Stage, focus: Usd.Prim | None,
) -> list[Finding]:
    """Each localPos must sit inside its body's bounds or the pivot detaches."""
    joints = _joints_for_focus(stage, focus)
    findings: list[Finding] = []
    for joint in joints:
        for rel_name, attr_name in (
            ("physics:body0", "physics:localPos0"),
            ("physics:body1", "physics:localPos1"),
        ):
            body = _target_prim(stage, joint, rel_name)
            if body is None:
                continue
            local_attr = joint.GetAttribute(attr_name)
            if not local_attr or not local_attr.HasAuthoredValue():
                continue
            local_pos = local_attr.Get()
            half_extent = _max_half_extent(body)
            if half_extent is None or half_extent <= 0:
                continue
            mag = (
                local_pos[0] ** 2 + local_pos[1] ** 2 + local_pos[2] ** 2
            ) ** 0.5
            if mag <= half_extent + 1e-4:
                continue
            findings.append(Finding(
                check_id="physics:joint_local_pos_within_bounds",
                subsystem="physics",
                status=FindingStatus.FAIL,
                severity=Severity.WARNING,
                prim_path=str(joint.GetPath()),
                message=(
                    f"{attr_name} = ({local_pos[0]:.3f}, {local_pos[1]:.3f}, "
                    f"{local_pos[2]:.3f}) is outside the body's bounds "
                    f"(max half-extent {half_extent:.3f}); the joint pivot "
                    f"is detached from {body.GetPath()}."
                ),
                evidence={
                    "local_pos": [float(c) for c in local_pos],
                    "body_max_half_extent": half_extent,
                    "body_prim_path": str(body.GetPath()),
                },
                fix_hint=(
                    "Set the local position inside the body's geometry "
                    "(e.g. half-extent on one axis to attach at an edge)."
                ),
            ))
    return findings


@register(
    check_id="physics:dynamic_body_has_nonzero_mass",
    subsystem="physics",
    applies_to=lambda _stage, focus: focus is None or is_rigid_body(focus),
)
def check_dynamic_body_has_nonzero_mass(
    stage: Usd.Stage, focus: Usd.Prim | None,
) -> list[Finding]:
    """A dynamic RigidBody with an explicit zero mass cannot move."""
    bodies = [focus] if focus is not None else _iter_rigid_bodies(stage)
    findings: list[Finding] = []
    for body in bodies:
        if _is_kinematic(body):
            continue
        mass_attr = body.GetAttribute("physics:mass")
        if not mass_attr or not mass_attr.HasAuthoredValue():
            continue
        if float(mass_attr.Get()) > 0.0:
            continue
        findings.append(Finding(
            check_id="physics:dynamic_body_has_nonzero_mass",
            subsystem="physics",
            status=FindingStatus.FAIL,
            severity=Severity.ERROR,
            prim_path=str(body.GetPath()),
            message=(
                "Dynamic RigidBody has physics:mass = 0; the solver cannot "
                "move a zero-mass body."
            ),
            fix_hint=(
                "Set physics:mass to a positive value or clear it to fall "
                "back to density-derived mass."
            ),
        ))
    return findings


@register(
    check_id="physics:articulation_root_not_nested",
    subsystem="physics",
    applies_to=lambda _stage, focus: focus is None or is_articulation_root(focus),
)
def check_articulation_root_not_nested(
    stage: Usd.Stage, focus: Usd.Prim | None,
) -> list[Finding]:
    """No ancestor or descendant of an ArticulationRootAPI may also carry it."""
    roots = (
        [focus] if focus is not None
        else [p for p in stage.Traverse() if is_articulation_root(p)]
    )
    findings: list[Finding] = []
    for prim in roots:
        nested = _find_nested_articulation_root(prim)
        if nested is None:
            continue
        findings.append(Finding(
            check_id="physics:articulation_root_not_nested",
            subsystem="physics",
            status=FindingStatus.FAIL,
            severity=Severity.ERROR,
            prim_path=str(prim.GetPath()),
            message=(
                f"ArticulationRootAPI also applied at {nested.GetPath()}; "
                "the UsdPhysics spec forbids nested articulation roots."
            ),
            fix_hint="Remove ArticulationRootAPI from one of the prims.",
        ))
    return findings


def _find_nested_articulation_root(prim: Usd.Prim) -> Usd.Prim | None:
    cursor = prim.GetParent()
    while cursor and cursor.IsValid() and cursor.GetPath() != Sdf.Path.absoluteRootPath:
        if is_articulation_root(cursor):
            return cursor
        cursor = cursor.GetParent()
    for descendant in Usd.PrimRange(prim):
        if descendant == prim:
            continue
        if is_articulation_root(descendant):
            return descendant
    return None
