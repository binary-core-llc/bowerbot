# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics schema info — what each API and joint declares and accepts."""

from __future__ import annotations

from collections.abc import Iterable

from pxr import Usd

from bowerbot.schemas import (
    PhysicsApiName,
    PhysicsApiSchemaInfo,
    PhysicsJointType,
    PhysicsRules,
)
from bowerbot.utils.core.schema_registry import schema_properties


def list_api_properties(
    api_name: PhysicsApiName,
    *,
    instance_name: str | None = None,
) -> PhysicsApiSchemaInfo:
    """Live schema-registry view of every property the API declares.

    For multi-apply APIs (DriveAPI, LimitAPI) *instance_name* is
    required; property names are returned with the instance substituted
    (e.g. ``drive:angular:physics:stiffness``).
    """
    if api_name in PhysicsRules.MULTI_APPLY_APIS and not instance_name:
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

    properties = schema_properties(
        prim_def,
        prim_def.GetPropertyNames(),
        rename=(
            (lambda name: name.replace(PhysicsRules.INSTANCE_NAME_PLACEHOLDER, instance_name))
            if instance_name else None
        ),
    )

    target_req = (
        "UsdPhysics joint prim" if api_name in PhysicsRules.MULTI_APPLY_APIS
        else f"UsdGeom.{PhysicsRules.TARGET_TYPES[api_name]}"
    )
    companion = PhysicsRules.COMPANIONS.get(api_name)
    return PhysicsApiSchemaInfo(
        api_name=api_name.value,
        target_requirement=target_req,
        requires_companion_api=companion.value if companion else None,
        properties=properties,
    )


def list_joint_properties(joint_type: PhysicsJointType) -> PhysicsApiSchemaInfo:
    """Schema-registry view of every property a typed joint declares."""
    prim_def = Usd.SchemaRegistry().FindConcretePrimDefinition(joint_type.value)
    if prim_def is None:
        raise ValueError(
            f"USD schema registry does not know {joint_type.value}. "
            "USD build is missing UsdPhysics.",
        )
    return PhysicsApiSchemaInfo(
        api_name=joint_type.value,
        target_requirement="(typed prim)",
        properties=schema_properties(prim_def, prim_def.GetPropertyNames()),
    )


def validate_instance_name(
    api_name: PhysicsApiName,
    instance_name: str | None,
    joint_type_name: str,
) -> str:
    """Return *instance_name*, refusing it if invalid for *api_name* on *joint_type*."""
    try:
        jt = PhysicsJointType(joint_type_name)
    except ValueError:
        raise ValueError(
            f"{api_name.value} can only be applied to a UsdPhysics "
            f"joint prim; got type {joint_type_name!r}.",
        ) from None

    valid = PhysicsRules.INSTANCE_NAMES[api_name].get(jt, frozenset())
    if not valid:
        raise ValueError(
            f"{api_name.value} is not supported on {jt.value}.",
        )
    if instance_name is None or instance_name not in valid:
        raise ValueError(
            f"instance_name {instance_name!r} is not valid for "
            f"{api_name.value} on {jt.value}. "
            f"Allowed: {sorted(valid)}",
        )
    return instance_name


def refuse_unknown(
    schema: PhysicsApiSchemaInfo, provided: Iterable[str], kind: str,
) -> None:
    """Refuse property names the schema does not declare."""
    valid = {p.name for p in schema.properties if p.kind == kind}
    unknown = sorted(n for n in provided if n not in valid)
    if unknown:
        raise ValueError(
            f"{schema.api_name} does not declare {kind}(s) {unknown}. "
            f"Allowed: {sorted(valid)}",
        )
