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

from pxr import Sdf, Usd, UsdGeom, UsdPhysics

from bowerbot.schemas import (
    ASWFLayerNames,
    AssetPhysicsSummary,
    PhysicsApiName,
    PhysicsApiSchemaInfo,
    PhysicsPrimSummary,
    PhysicsPropertySpec,
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
}

# Prim base type each API requires per the UsdPhysics spec.
_TARGET_TYPE: dict[PhysicsApiName, type] = {
    PhysicsApiName.RIGID_BODY: UsdGeom.Xformable,
    PhysicsApiName.MASS: UsdGeom.Xformable,
    PhysicsApiName.COLLISION: UsdGeom.Gprim,
    PhysicsApiName.MESH_COLLISION: UsdGeom.Mesh,
}

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
