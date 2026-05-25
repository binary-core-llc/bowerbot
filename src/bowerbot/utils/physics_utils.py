# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""UsdPhysics applied-API authoring on ``phy.usda``.

Generic over the four supported APIs (RigidBody, Mass, Collision,
MeshCollision). Property names and types are discovered from the live
USD schema registry; callers pass free ``{name: value}`` dicts and the
declared types are resolved at write time.

phy.usda is composed into the asset via a reference arc (matching the
lgt/mtl/contents convention), so it sits outside the asset stage's local
LayerStack. Writes go to phy.usda opened as its own stage; the schema
registry exposes API-declared properties on Over prims after ``Apply()``.
Validation against the asset's composed types is a separate read pass.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

from bowerbot.schemas import (
    AssetPhysicsSummary,
    ASWFLayerNames,
    CollisionGroupsSummary,
    CollisionGroupSummary,
    JointsSummary,
    JointSummary,
    PhysicsApiName,
    PhysicsApiSchemaInfo,
    PhysicsJointType,
    PhysicsPrimSummary,
    PhysicsPropertySpec,
    SceneNamespace,
    ScenePhysicsSummary,
)
from bowerbot.utils import stage_utils
from bowerbot.utils.asset_folder_utils import (
    ensure_root_reference,
    find_root_file,
    resolve_default_prim_name,
)

logger = logging.getLogger(__name__)


# ── API registry ──

_API_CLASSES: dict[PhysicsApiName, type] = {
    PhysicsApiName.RIGID_BODY: UsdPhysics.RigidBodyAPI,
    PhysicsApiName.MASS: UsdPhysics.MassAPI,
    PhysicsApiName.COLLISION: UsdPhysics.CollisionAPI,
    PhysicsApiName.MESH_COLLISION: UsdPhysics.MeshCollisionAPI,
    PhysicsApiName.ARTICULATION_ROOT: UsdPhysics.ArticulationRootAPI,
}

# Prim base type each API requires per the UsdPhysics spec.
_TARGET_TYPE: dict[PhysicsApiName, type] = {
    PhysicsApiName.RIGID_BODY: UsdGeom.Xformable,
    PhysicsApiName.MASS: UsdGeom.Xformable,
    PhysicsApiName.COLLISION: UsdGeom.Gprim,
    PhysicsApiName.MESH_COLLISION: UsdGeom.Mesh,
    PhysicsApiName.ARTICULATION_ROOT: UsdGeom.Xformable,
}

_JOINT_CLASSES: dict[PhysicsJointType, type] = {
    PhysicsJointType.REVOLUTE: UsdPhysics.RevoluteJoint,
    PhysicsJointType.PRISMATIC: UsdPhysics.PrismaticJoint,
    PhysicsJointType.SPHERICAL: UsdPhysics.SphericalJoint,
    PhysicsJointType.FIXED: UsdPhysics.FixedJoint,
    PhysicsJointType.DISTANCE: UsdPhysics.DistanceJoint,
}

_JOINTS_SCOPE_NAME = "joints"

# MeshCollisionAPI is meaningless without CollisionAPI per the spec.
_COMPANION: dict[PhysicsApiName, PhysicsApiName] = {
    PhysicsApiName.MESH_COLLISION: PhysicsApiName.COLLISION,
}

# Dropping CollisionAPI also drops MeshCollisionAPI.
_DEPENDENTS: dict[PhysicsApiName, tuple[PhysicsApiName, ...]] = {
    PhysicsApiName.COLLISION: (PhysicsApiName.MESH_COLLISION,),
}


# ── Layer lifecycle ──


def _phy_layer_path(asset_dir: Path) -> Path:
    """Path to the asset's ``phy.usda``."""
    return asset_dir / ASWFLayerNames.PHY


def ensure_physics_layer(asset_dir: Path) -> Path:
    """Create ``phy.usda`` if missing."""
    path = _phy_layer_path(asset_dir)
    if path.exists():
        return path

    default_prim_name = resolve_default_prim_name(asset_dir)
    layer = Sdf.Layer.CreateNew(str(path))
    layer.defaultPrim = default_prim_name
    over = Sdf.CreatePrimInLayer(layer, Sdf.Path(f"/{default_prim_name}"))
    over.specifier = Sdf.SpecifierOver
    layer.Save()
    return path


def ensure_physics_referenced(asset_dir: Path) -> None:
    """Ensure the asset root references ``phy.usda``."""
    ensure_root_reference(asset_dir, ASWFLayerNames.PHY)


# ── Schema introspection ──


def list_api_properties(api_name: PhysicsApiName) -> PhysicsApiSchemaInfo:
    """Live schema-registry view of every property the API declares.

    Callers query this before authoring to discover attributes, types,
    defaults, and allowed-token sets without hardcoding any of them.
    """
    prim_def = Usd.SchemaRegistry().FindAppliedAPIPrimDefinition(api_name.value)
    if prim_def is None:
        raise ValueError(
            f"USD schema registry does not know {api_name.value}. "
            "USD build is missing UsdPhysics.",
        )

    properties: list[PhysicsPropertySpec] = []
    for prop_name in prim_def.GetPropertyNames():
        attr_spec = prim_def.GetSchemaAttributeSpec(prop_name)
        if attr_spec is not None:
            properties.append(PhysicsPropertySpec(
                name=prop_name,
                kind="attribute",
                type_name=str(attr_spec.typeName),
                default=_to_jsonable(attr_spec.default),
                allowed_tokens=[
                    str(t) for t in (attr_spec.allowedTokens or [])
                ],
                documentation=_property_doc(prim_def, prop_name, attr_spec),
            ))
            continue
        rel_spec = prim_def.GetSchemaRelationshipSpec(prop_name)
        if rel_spec is not None:
            properties.append(PhysicsPropertySpec(
                name=prop_name,
                kind="relationship",
                documentation=_property_doc(prim_def, prop_name, rel_spec),
            ))

    companion = _COMPANION.get(api_name)
    return PhysicsApiSchemaInfo(
        api_name=api_name.value,
        target_requirement=f"UsdGeom.{_TARGET_TYPE[api_name].__name__}",
        requires_companion_api=companion.value if companion else None,
        properties=properties,
    )


# ── API application ──


def apply_api(
    asset_dir: Path,
    prim_path: str,
    api_name: PhysicsApiName,
    attributes: dict[str, Any] | None = None,
    relationships: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Apply ``api_name`` to *prim_path* and author opinions in ``phy.usda``.

    Validates the target's prim type against the composed asset stage and
    refuses any property name not declared by the API. Companion APIs
    (MeshCollisionAPI requires CollisionAPI) are applied first.
    """
    attributes = attributes or {}
    relationships = relationships or {}

    schema_info = list_api_properties(api_name)
    _refuse_unknown(api_name, attributes, schema_info, "attribute")
    _refuse_unknown(api_name, relationships, schema_info, "relationship")

    root_file = find_root_file(asset_dir)
    if root_file is None:
        raise ValueError(f"No root file in asset {asset_dir.name}")

    composed = Usd.Stage.Open(str(root_file))
    target = composed.GetPrimAtPath(prim_path)
    if not target or not target.IsValid():
        raise ValueError(
            f"Prim not found in asset {asset_dir.name}: {prim_path}",
        )
    _require_target_type(target, api_name)
    if api_name == PhysicsApiName.ARTICULATION_ROOT:
        check_articulation_root_nesting(composed, prim_path)
    del composed

    ensure_physics_layer(asset_dir)
    stage = Usd.Stage.Open(str(_phy_layer_path(asset_dir)))
    prim = stage.OverridePrim(Sdf.Path(prim_path))

    companion = _COMPANION.get(api_name)
    if companion is not None:
        _API_CLASSES[companion].Apply(prim)
    _API_CLASSES[api_name].Apply(prim)

    for name, value in attributes.items():
        attr = prim.GetAttribute(name)
        stage_utils.set_prim_attribute(
            stage, prim_path, name, value, expected_type=attr.GetTypeName(),
        )

    for name, targets in relationships.items():
        prim.GetRelationship(name).SetTargets(
            [Sdf.Path(t) for t in targets],
        )

    stage.Save()
    ensure_physics_referenced(asset_dir)

    logger.info(
        "Applied %s on %s in %s/phy.usda",
        api_name.value, prim_path, asset_dir.name,
    )
    return {
        "prim_path": prim_path,
        "api_name": api_name.value,
        "companion_api": companion.value if companion else None,
        "attributes_set": sorted(attributes),
        "relationships_set": sorted(relationships),
    }


# ── API removal ──


def remove_api(
    asset_dir: Path, prim_path: str, api_name: PhysicsApiName,
) -> bool:
    """Remove ``api_name`` (and any dependent APIs) from *prim_path*."""
    phy_path = _phy_layer_path(asset_dir)
    if not phy_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is None:
        return False
    return _remove_api_from_layer(layer, prim_path, api_name)


# ── Scene-level authoring ──


def ensure_physics_scope(stage: Usd.Stage) -> str:
    """Create ``/Scene/Physics`` as a Scope if missing; return its path."""
    scope_path = SceneNamespace.PHYSICS
    if not stage.GetPrimAtPath(scope_path).IsValid():
        stage.DefinePrim(scope_path, "Scope")
    return scope_path


def ensure_physics_scene(
    stage: Usd.Stage,
    name: str = "PhysicsScene",
    gravity_magnitude: float | None = None,
    gravity_direction: tuple[float, float, float] | None = None,
) -> str:
    """Create the physics scope and a ``UsdPhysics.Scene`` child prim.

    Gravity magnitude defaults to ``9.81 / metersPerUnit`` (Earth gravity
    in stage units) and direction defaults to ``(0, -1, 0)``.
    """
    scope_path = ensure_physics_scope(stage)
    scene_path = f"{scope_path}/{name}"
    scene_prim = UsdPhysics.Scene.Define(stage, scene_path)

    if gravity_magnitude is None:
        mpu = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
        gravity_magnitude = 9.81 / mpu
    if gravity_direction is None:
        gravity_direction = (0.0, -1.0, 0.0)

    scene_prim.CreateGravityDirectionAttr(Gf.Vec3f(*gravity_direction))
    scene_prim.CreateGravityMagnitudeAttr(float(gravity_magnitude))

    stage.Save()
    logger.info(
        "Set up PhysicsScene at %s (gravity magnitude %s)",
        scene_path, gravity_magnitude,
    )
    return scene_path


def apply_api_scene(
    stage: Usd.Stage,
    prim_path: str,
    api_name: PhysicsApiName,
    attributes: dict[str, Any] | None = None,
    relationships: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Apply ``api_name`` directly on scene.usda at *prim_path*.

    For per-placement overrides (e.g. disable collision on one chair
    instance) and physics on scene-only prims. scene.usda is the
    strongest layer in LIVRPS so opinions here win over the asset's
    ``phy.usda`` defaults.
    """
    attributes = attributes or {}
    relationships = relationships or {}

    schema_info = list_api_properties(api_name)
    _refuse_unknown(api_name, attributes, schema_info, "attribute")
    _refuse_unknown(api_name, relationships, schema_info, "relationship")

    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found in scene: {prim_path}")
    _require_target_type(prim, api_name)
    if api_name == PhysicsApiName.ARTICULATION_ROOT:
        check_articulation_root_nesting(stage, prim_path)

    companion = _COMPANION.get(api_name)
    if companion is not None:
        _API_CLASSES[companion].Apply(prim)
    _API_CLASSES[api_name].Apply(prim)

    for name, value in attributes.items():
        attr = prim.GetAttribute(name)
        stage_utils.set_prim_attribute(
            stage, prim_path, name, value, expected_type=attr.GetTypeName(),
        )

    for name, targets in relationships.items():
        prim.GetRelationship(name).SetTargets(
            [Sdf.Path(t) for t in targets],
        )

    stage.Save()
    logger.info(
        "Applied %s scene-level on %s", api_name.value, prim_path,
    )
    return {
        "prim_path": prim_path,
        "api_name": api_name.value,
        "companion_api": companion.value if companion else None,
        "attributes_set": sorted(attributes),
        "relationships_set": sorted(relationships),
        "scope": "scene",
    }


def remove_api_scene(
    stage: Usd.Stage, prim_path: str, api_name: PhysicsApiName,
) -> bool:
    """Remove ``api_name`` opinions from scene.usda at *prim_path*."""
    return _remove_api_from_layer(stage.GetRootLayer(), prim_path, api_name)


# ── Scene masking detection (refuse-or-acknowledge) ──


def find_masking_scene_opinions(
    stage: Usd.Stage,
    asset_dir: Path,
    asset_local_path: str,
    attributes: dict[str, Any] | None = None,
    relationships: dict[str, list[str]] | None = None,
) -> list[tuple[str, str, str]]:
    """Scene.usda opinions on placements that would mask a phy.usda write.

    Returns ``(placement_prim_path, kind, key)`` tuples; ``kind`` is
    ``"attribute"`` or ``"relationship"``. Empty list when no masking
    opinions exist or the asset has no placements in the open scene.
    """
    attr_names = set((attributes or {}).keys())
    rel_names = set((relationships or {}).keys())
    if not attr_names and not rel_names:
        return []

    placements = stage_utils.find_asset_placements(stage, asset_dir)
    if not placements:
        return []

    default_prim = resolve_default_prim_name(asset_dir)
    asset_prefix = f"/{default_prim}"
    tail = (
        asset_local_path[len(asset_prefix):]
        if asset_local_path.startswith(asset_prefix)
        else asset_local_path
    )

    layer = stage.GetRootLayer()
    masking: list[tuple[str, str, str]] = []
    for placement in placements:
        scene_path = f"{placement}{tail}" if tail else placement
        spec = layer.GetPrimAtPath(scene_path)
        if spec is None:
            continue
        for name in attr_names:
            if name in spec.attributes:
                masking.append((scene_path, "attribute", name))
        for name in rel_names:
            if name in spec.relationships:
                masking.append((scene_path, "relationship", name))
    return masking


def clear_masking_scene_opinions(
    stage: Usd.Stage,
    masking: list[tuple[str, str, str]],
) -> None:
    """Remove every masking opinion in *masking* from scene.usda."""
    layer = stage.GetRootLayer()
    touched_paths: set[str] = set()
    for prim_path, kind, key in masking:
        spec = layer.GetPrimAtPath(prim_path)
        if spec is None:
            continue
        container = spec.attributes if kind == "attribute" else spec.relationships
        prop_spec = container.get(key)
        if prop_spec is not None:
            spec.RemoveProperty(prop_spec)
            touched_paths.add(prim_path)
    for prim_path in touched_paths:
        stage_utils.prune_empty_overrides(layer, prim_path)
    if touched_paths:
        layer.Save()


def enforce_masking_policy(
    stage: Usd.Stage,
    asset_dir: Path,
    asset_local_path: str,
    api_name: PhysicsApiName,
    attributes: dict[str, Any] | None,
    relationships: dict[str, list[str]] | None,
    *,
    clear: bool,
    confirm: bool,
) -> list[tuple[str, str, str]]:
    """Detect / clear / refuse scene.usda opinions that would mask a phy.usda write.

    Returns the list of opinions that were cleared (empty when none or when
    *confirm* was used). Raises ``ValueError`` with a per-opinion breakdown
    when masking exists and neither *clear* nor *confirm* is set.
    """
    masking = find_masking_scene_opinions(
        stage, asset_dir, asset_local_path,
        attributes=attributes, relationships=relationships,
    )
    if not masking:
        return []
    if clear:
        clear_masking_scene_opinions(stage, masking)
        return masking
    if confirm:
        return []
    raise ValueError(format_masking_override_error(api_name, masking))


def format_masking_override_error(
    api_name: PhysicsApiName, masking: list[tuple[str, str, str]],
) -> str:
    """Render a refuse-or-acknowledge error listing every masking opinion."""
    lines = [
        f"Cannot author {api_name.value} on phy.usda: "
        f"{len(masking)} scene.usda opinion(s) would mask it. Per LIVRPS, "
        "the asset opinions would be silently overridden at composition "
        "time. Conflicts:",
    ]
    for prim_path, kind, key in masking:
        lines.append(f"  {prim_path}.{key} ({kind})")
    lines.append(
        "Retry with clear_masking_overrides=true to remove these scene "
        "opinions and write to phy.usda, OR confirm_masked=true to write "
        "anyway (scene overrides will keep winning on those placements).",
    )
    return "\n".join(lines)


# ── Inspection ──


def get_physics_summary(asset_dir: Path) -> AssetPhysicsSummary:
    """Every authored physics opinion in the asset's ``phy.usda``."""
    phy_path = _phy_layer_path(asset_dir)
    if not phy_path.exists():
        return AssetPhysicsSummary(asset_path=str(asset_dir))
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is None:
        return AssetPhysicsSummary(
            asset_path=str(asset_dir), has_physics_layer=True,
        )

    prims: list[PhysicsPrimSummary] = []

    def visit(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if not isinstance(spec, Sdf.PrimSpec):
            return
        apis = _read_api_schemas(spec)
        attrs = {a.name: _to_jsonable(a.default) for a in spec.attributes}
        rels = {
            r.name: [str(t) for t in r.targetPathList.explicitItems]
            for r in spec.relationships
        }
        if apis or attrs or rels:
            prims.append(PhysicsPrimSummary(
                prim_path=str(path),
                applied_apis=apis,
                attributes=attrs,
                relationships=rels,
            ))

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return AssetPhysicsSummary(
        asset_path=str(asset_dir), has_physics_layer=True, prims=prims,
    )


def get_scene_physics_summary(
    stage: Usd.Stage, prim_path: str,
) -> ScenePhysicsSummary:
    """Scene-side physics opinions on *prim_path* and its descendants."""
    layer = stage.GetRootLayer()
    if layer.GetPrimAtPath(prim_path) is None:
        return ScenePhysicsSummary(prim_path=prim_path)

    prims: list[PhysicsPrimSummary] = []

    def visit(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if not isinstance(spec, Sdf.PrimSpec):
            return
        apis = _read_api_schemas(spec)
        attrs = {
            a.name: _to_jsonable(a.default)
            for a in spec.attributes
            if a.name.startswith("physics:")
        }
        rels = {
            r.name: [str(t) for t in r.targetPathList.explicitItems]
            for r in spec.relationships
            if r.name.startswith("physics:")
            or r.name == "material:binding:physics"
        }
        if apis or attrs or rels:
            prims.append(PhysicsPrimSummary(
                prim_path=str(path),
                applied_apis=apis,
                attributes=attrs,
                relationships=rels,
            ))

    layer.Traverse(Sdf.Path(prim_path), visit)
    return ScenePhysicsSummary(prim_path=prim_path, prims=prims)


def _group_prim_path(name: str) -> str:
    """Path to a group prim, flat-sibling of PhysicsScene under /Scene/Physics."""
    return f"{SceneNamespace.PHYSICS}/{name}"


def _resolve_group_path(name_or_path: str) -> str:
    """Accept either a bare group name or a full prim path; return prim path."""
    if name_or_path.startswith("/"):
        return name_or_path
    return _group_prim_path(name_or_path)


def create_or_update_collision_group(
    stage: Usd.Stage,
    name: str,
    *,
    includes: list[str] | None = None,
    excludes: list[str] | None = None,
    filtered_groups: list[str] | None = None,
    invert_filter: bool | None = None,
    merge_group: str | None = None,
) -> dict[str, Any]:
    """Create or update a ``UsdPhysicsCollisionGroup`` under the Groups scope.

    Each list-shaped kwarg REPLACES the existing collection / rel targets
    when provided (not appended). Pass ``None`` to leave that property
    untouched on an existing group. ``filtered_groups`` accepts bare group
    names; they are resolved to ``/Scene/Physics/Groups/<name>``.
    """
    _validate_group_name(name)
    ensure_physics_scope(stage)

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


def remove_collision_group(
    stage: Usd.Stage, name: str, *, force: bool = False,
) -> bool:
    """Remove a collision group. Refuses if any other group filters against it."""
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
                "anyway (dangling rels will be left).",
            )

    removed = stage.RemovePrim(prim_path)
    if removed:
        stage.Save()
    return removed


def list_collision_groups(stage: Usd.Stage) -> CollisionGroupsSummary:
    """Return every ``UsdPhysicsCollisionGroup`` under ``/Scene/Physics``."""
    scope = stage.GetPrimAtPath(SceneNamespace.PHYSICS)
    if not scope or not scope.IsValid():
        return CollisionGroupsSummary()

    summaries = [
        _summarize_group(child)
        for child in scope.GetChildren()
        if child.IsA(UsdPhysics.CollisionGroup)
    ]
    return CollisionGroupsSummary(groups=summaries)


def get_collision_group_summary(
    stage: Usd.Stage, name: str,
) -> CollisionGroupSummary | None:
    """Return one group's summary, or ``None`` if not defined."""
    prim = stage.GetPrimAtPath(_group_prim_path(name))
    if not prim or not prim.IsValid():
        return None
    if not prim.IsA(UsdPhysics.CollisionGroup):
        return None
    return _summarize_group(prim)


def cleanup_if_empty(asset_dir: Path) -> bool:
    """Delete ``phy.usda`` and drop its reference when no opinions remain."""
    phy_path = _phy_layer_path(asset_dir)
    if not phy_path.exists():
        return False
    if get_physics_summary(asset_dir).prims:
        return False

    _drop_physics_reference(asset_dir)
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is not None:
        layer.Clear()
    phy_path.unlink()
    return True


# ── Internal helpers ──


def validate_scope(scope: str) -> str:
    """Refuse any value other than ``'asset'`` or ``'scene'``."""
    if scope not in ("asset", "scene"):
        raise ValueError(
            f"Invalid scope {scope!r}; must be 'asset' or 'scene'.",
        )
    return scope


def parse_vec3(
    value: Any, name: str = "vector",
) -> tuple[float, float, float] | None:
    """Coerce a JSON-shaped triple to ``(float, float, float)`` or None."""
    if value is None:
        return None
    if len(value) != 3:
        raise ValueError(f"{name!r} must be a length-3 vector; got {value!r}")
    return float(value[0]), float(value[1]), float(value[2])


def _require_target_type(prim: Usd.Prim, api_name: PhysicsApiName) -> None:
    """Refuse if *prim* is not the schema's required prim type."""
    cls = _TARGET_TYPE[api_name]
    if not prim.IsA(cls):
        raise ValueError(
            f"{api_name.value} requires UsdGeom.{cls.__name__}; "
            f"{prim.GetPath()} is a {prim.GetTypeName()!r}",
        )


def _refuse_unknown(
    api_name: PhysicsApiName,
    provided: dict[str, Any],
    schema_info: PhysicsApiSchemaInfo,
    kind: str,
) -> None:
    """Refuse property names the schema does not declare."""
    valid = {p.name for p in schema_info.properties if p.kind == kind}
    unknown = sorted(n for n in provided if n not in valid)
    if not unknown:
        return
    raise ValueError(
        f"{api_name.value} does not declare {kind}(s) {unknown}. "
        f"Allowed: {sorted(valid)}",
    )


def _read_api_schemas(prim_spec: Sdf.PrimSpec) -> list[str]:
    """Union of every apiSchemas list-op slot on *prim_spec*."""
    list_op = prim_spec.GetInfo("apiSchemas")
    if list_op is None:
        return []
    apis: list[str] = []
    for slot in ("prependedItems", "appendedItems", "explicitItems"):
        apis.extend(getattr(list_op, slot, ()))
    return apis


# ── Joints + articulations ──


def list_joint_properties(joint_type: PhysicsJointType) -> PhysicsApiSchemaInfo:
    """Schema-registry view of every property a typed joint declares."""
    prim_def = Usd.SchemaRegistry().FindConcretePrimDefinition(joint_type.value)
    if prim_def is None:
        raise ValueError(
            f"USD schema registry does not know {joint_type.value}. "
            "USD build is missing UsdPhysics.",
        )

    properties: list[PhysicsPropertySpec] = []
    for prop_name in prim_def.GetPropertyNames():
        attr_spec = prim_def.GetSchemaAttributeSpec(prop_name)
        if attr_spec is not None:
            properties.append(PhysicsPropertySpec(
                name=prop_name,
                kind="attribute",
                type_name=str(attr_spec.typeName),
                default=_to_jsonable(attr_spec.default),
                allowed_tokens=[
                    str(t) for t in (attr_spec.allowedTokens or [])
                ],
                documentation=_property_doc(prim_def, prop_name, attr_spec),
            ))
            continue
        rel_spec = prim_def.GetSchemaRelationshipSpec(prop_name)
        if rel_spec is not None:
            properties.append(PhysicsPropertySpec(
                name=prop_name,
                kind="relationship",
                documentation=_property_doc(prim_def, prop_name, rel_spec),
            ))

    return PhysicsApiSchemaInfo(
        api_name=joint_type.value,
        target_requirement="(typed prim)",
        properties=properties,
    )


def create_joint_scene(
    stage: Usd.Stage,
    joint_type: PhysicsJointType,
    name: str,
    body0: str | None,
    body1: str | None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a typed joint at ``/Scene/Physics/<name>`` connecting two bodies.

    Used for joints that span separate assets in a scene. Validates both
    body targets are Xformables and at least one reaches RigidBodyAPI.
    An empty / None body rel is treated as 'attach to world' per the spec.
    """
    _validate_joint_name(name)
    attributes = attributes or {}
    _validate_joint_bodies(stage, body0, body1)
    _refuse_unknown_joint_properties(joint_type, attributes)

    ensure_physics_scope(stage)
    prim_path = f"{SceneNamespace.PHYSICS}/{name}"
    joint = _JOINT_CLASSES[joint_type].Define(stage, prim_path)

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
    """Create a typed joint inside the asset's ``phy.usda`` at ``/<defaultPrim>/joints/<name>``.

    body0 / body1 are asset-namespace prim paths (e.g.
    ``/AssetName/base_link``). At least one must reach RigidBodyAPI in
    the composed asset stage. The asset reference rebases the joint's
    body rels automatically when placed in a scene.
    """
    _validate_joint_name(name)
    attributes = attributes or {}
    _refuse_unknown_joint_properties(joint_type, attributes)

    root_file = find_root_file(asset_dir)
    if root_file is None:
        raise ValueError(f"No root file in asset {asset_dir.name}")
    composed = Usd.Stage.Open(str(root_file))
    _validate_joint_bodies(composed, body0, body1)
    del composed

    ensure_physics_layer(asset_dir)
    stage = Usd.Stage.Open(str(_phy_layer_path(asset_dir)))
    default_prim_name = resolve_default_prim_name(asset_dir)
    joints_scope_path = f"/{default_prim_name}/{_JOINTS_SCOPE_NAME}"
    if not stage.GetPrimAtPath(joints_scope_path).IsValid():
        stage.DefinePrim(joints_scope_path, "Scope")

    prim_path = f"{joints_scope_path}/{name}"
    joint = _JOINT_CLASSES[joint_type].Define(stage, prim_path)

    _set_body_rel(joint, "physics:body0", body0)
    _set_body_rel(joint, "physics:body1", body1)
    _author_joint_attributes(joint, attributes, joint_type)

    stage.Save()
    ensure_physics_referenced(asset_dir)

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
    phy_path = _phy_layer_path(asset_dir)
    if not phy_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(phy_path))
    if layer is None:
        return False
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_path = f"/{default_prim_name}/{_JOINTS_SCOPE_NAME}/{name}"
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
        if _is_supported_joint_prim(prim):
            joints.append(_summarize_joint(prim))
    return JointsSummary(joints=joints)


def list_joints_asset(asset_dir: Path) -> JointsSummary:
    """Return every joint prim authored in the asset's ``phy.usda``."""
    phy_path = _phy_layer_path(asset_dir)
    if not phy_path.exists():
        return JointsSummary()
    stage = Usd.Stage.Open(str(phy_path))
    if stage is None:
        return JointsSummary()
    return list_joints_scene(stage)


def _validate_joint_name(name: str) -> None:
    """Refuse empty names or names with whitespace / path separators."""
    if not name:
        raise ValueError("Joint name cannot be empty.")
    bad = [c for c in name if c in _GROUP_NAME_FORBIDDEN_CHARS]
    if bad:
        raise ValueError(
            f"Joint name {name!r} has invalid characters "
            f"{sorted(set(bad))}; use letters, digits, and underscores.",
        )


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
    joint_type: PhysicsJointType, attributes: dict[str, Any],
) -> None:
    """Refuse attribute names the joint schema does not declare."""
    info = list_joint_properties(joint_type)
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
        stage_utils.set_prim_attribute(
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


def _is_supported_joint_prim(prim: Usd.Prim) -> bool:
    """Whether *prim* is one of the five supported joint typed prims."""
    return any(prim.IsA(cls) for cls in _JOINT_CLASSES.values())


def _is_supported_joint_spec(spec: Sdf.PrimSpec) -> bool:
    """Spec-side check (no stage) for joint typeName in our whitelist."""
    type_name = str(spec.typeName) if spec.typeName else ""
    return type_name in {jt.value for jt in PhysicsJointType}


_JOINT_TYPE_TO_ENUM: dict[str, PhysicsJointType] = {
    jt.value: jt for jt in PhysicsJointType
}


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
        attrs[name] = _to_jsonable(a.Get())

    return JointSummary(
        prim_path=str(prim.GetPath()),
        joint_type=str(type_name),
        body0=str(body0_targets[0]) if body0_targets else None,
        body1=str(body1_targets[0]) if body1_targets else None,
        attributes=attrs,
        applied_apis=list(prim.GetAppliedSchemas()),
    )


# ── ArticulationRootAPI nesting guard ──


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


_GROUP_NAME_FORBIDDEN_CHARS = frozenset(" \t\n\r/\\")


def _validate_group_name(name: str) -> None:
    """Refuse empty names or names with whitespace / path separators."""
    if not name:
        raise ValueError("Collision group name cannot be empty.")
    bad = [c for c in name if c in _GROUP_NAME_FORBIDDEN_CHARS]
    if bad:
        raise ValueError(
            f"Collision group name {name!r} has invalid characters "
            f"{sorted(set(bad))}; use letters, digits, and underscores.",
        )


def _summarize_group(prim: Usd.Prim) -> CollisionGroupSummary:
    """Read a ``UsdPhysicsCollisionGroup`` prim into a summary model."""
    group = UsdPhysics.CollisionGroup(prim)
    collection = group.GetCollidersCollectionAPI()

    includes_rel = collection.GetIncludesRel()
    excludes_rel = collection.GetExcludesRel()
    filtered_rel = group.GetFilteredGroupsRel()
    invert_attr = group.GetInvertFilteredGroupsAttr()
    merge_attr = group.GetMergeGroupNameAttr()

    return CollisionGroupSummary(
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
    scope = stage.GetPrimAtPath(SceneNamespace.PHYSICS)
    if not scope or not scope.IsValid():
        return []
    target = Sdf.Path(group_prim_path)
    dependents: list[str] = []
    for child in scope.GetChildren():
        if not child.IsA(UsdPhysics.CollisionGroup):
            continue
        if str(child.GetPath()) == group_prim_path:
            continue
        rel = UsdPhysics.CollisionGroup(child).GetFilteredGroupsRel()
        if rel and target in rel.GetTargets():
            dependents.append(child.GetName())
    return dependents


def _remove_api_from_layer(
    layer: Sdf.Layer, prim_path: str, api_name: PhysicsApiName,
) -> bool:
    """Drop ``api_name`` + dependents + their opinions from *layer* at *prim_path*."""
    prim_spec = layer.GetPrimAtPath(prim_path)
    if prim_spec is None:
        return False

    authored = set(_read_api_schemas(prim_spec))
    targets: list[PhysicsApiName] = [api_name]
    for dependent in _DEPENDENTS.get(api_name, ()):
        if dependent.value in authored:
            targets.append(dependent)

    touched = False
    for name in targets:
        if _drop_from_api_listop(prim_spec, name.value):
            touched = True
        for prop in list_api_properties(name).properties:
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
        stage_utils.prune_empty_overrides(layer, prim_path)
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


def _drop_physics_reference(asset_dir: Path) -> None:
    """Remove ``./phy.usda`` from the asset root's reference list."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    prim_spec = layer.GetPrimAtPath(
        f"/{resolve_default_prim_name(asset_dir)}",
    )
    if prim_spec is None:
        return
    target = f"./{ASWFLayerNames.PHY}"
    ref_list = prim_spec.referenceList
    for items in (
        ref_list.prependedItems,
        ref_list.appendedItems,
        ref_list.addedItems,
        ref_list.explicitItems,
        ref_list.orderedItems,
    ):
        for r in [x for x in items if x.assetPath == target]:
            items.remove(r)
    layer.Save()


def _property_doc(
    prim_def: Usd.PrimDefinition, prop_name: str, spec: Sdf.PropertySpec,
) -> str:
    """Best-effort documentation lookup across USD versions."""
    getter = getattr(prim_def, "GetPropertyDocumentation", None)
    if callable(getter):
        return getter(prop_name) or ""
    return spec.GetInfo("documentation") or ""


def _to_jsonable(value: Any) -> Any:
    """Convert pxr values to JSON-friendly Python for summaries."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if hasattr(value, "__iter__") and not isinstance(value, str):
        try:
            return [float(c) for c in value]
        except (TypeError, ValueError):
            return str(value)
    return str(value)
