# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics materials: friction and bounce bound to colliders with the physics purpose."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Sdf
from pxr import Usd
from pxr import UsdPhysics
from pxr import UsdShade

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import physics
from bowerbot.utils import usd

logger = logging.getLogger(__name__)

# ── Creating and binding ──


def create_in_scene(
    stage: Usd.Stage,
    prim_path: str,
    params: schemas.PhysicsMaterialParams,
    *,
    project_mpu: float,
    project_up_axis: str,
) -> dict[str, Any]:
    """Create or update a physics material under ``/Scene/Physics`` and bind it to *prim_path*."""
    refuse_bad_values(params)
    target = require_prim(stage, prim_path)
    material_path = f"{constants.SceneNamespace.PHYSICS}/{params.name}"
    known = physics.rules.errors(stage)
    physics.scenes.ensure_default(
        stage, project_mpu=project_mpu, project_up_axis=project_up_axis,
    )
    _author(stage, material_path, params)
    _bind(target, stage.GetPrimAtPath(material_path))
    physics.rules.refuse_new_errors(
        stage, known, f"Binding the physics material {material_path} to {prim_path}",
    )
    stage.Save()
    logger.info("Physics material %s bound to %s scene-level", material_path, prim_path)
    return {"material": material_path, "scope": "scene"}


def create_in_asset(
    asset_dir: Path,
    prim_path: str,
    params: schemas.PhysicsMaterialParams,
    *,
    scene_stage: Usd.Stage,
) -> dict[str, Any]:
    """Create or update a physics material in ``phy.usda`` and bind it to *prim_path*."""
    refuse_bad_values(params)
    _require_asset_prim(asset_dir, prim_path)
    refuse_masked_binding(scene_stage, asset_dir, prim_path)
    material_path = _asset_material_path(asset_dir, params.name)
    doing = f"Binding the physics material {material_path} to {prim_path} in asset {asset_dir.name}"
    with physics.layer.edit(asset_dir, scene_stage, doing) as stage:
        _author(stage, material_path, params)
        _bind(stage.OverridePrim(prim_path), stage.GetPrimAtPath(material_path))
    logger.info("Physics material %s bound to %s in %s", material_path, prim_path, asset_dir.name)
    return {"material": material_path, "scope": "asset"}


def bind_in_scene(stage: Usd.Stage, prim_path: str, name: str) -> dict[str, Any]:
    """Bind the scene's physics material *name* to *prim_path*."""
    target = require_prim(stage, prim_path)
    material_path = f"{constants.SceneNamespace.PHYSICS}/{name}"
    material = _require_material(stage, material_path, "the scene")
    known = physics.rules.errors(stage)
    _bind(target, material)
    physics.rules.refuse_new_errors(
        stage, known, f"Binding the physics material {material_path} to {prim_path}",
    )
    stage.Save()
    return {"material": material_path, "scope": "scene"}


def bind_in_asset(
    asset_dir: Path, prim_path: str, name: str, *, scene_stage: Usd.Stage,
) -> dict[str, Any]:
    """Bind the asset's physics material *name* to *prim_path*, in its ``phy.usda``."""
    composed = _require_asset_prim(asset_dir, prim_path)
    material_path = _asset_material_path(asset_dir, name)
    _require_material(composed, material_path, f"asset {asset_dir.name}")
    del composed
    refuse_masked_binding(scene_stage, asset_dir, prim_path)
    doing = f"Binding the physics material {material_path} to {prim_path} in asset {asset_dir.name}"
    with physics.layer.edit(asset_dir, scene_stage, doing) as stage:
        _bind(stage.OverridePrim(prim_path), stage.GetPrimAtPath(material_path))
    return {"material": material_path, "scope": "asset"}


def require_prim(stage: Usd.Stage, prim_path: str) -> Usd.Prim:
    """The prim a physics material is bound to; it must exist."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")
    return prim


def refuse_bad_values(params: schemas.PhysicsMaterialParams) -> None:
    """Refuse a name USD cannot take, friction below zero, or bounce outside 0 to 1."""
    usd.naming.require_prim_name(params.name, "Physics material name")
    below_zero = [
        f"{label}={value:g}" for label, value in (
            ("static_friction", params.static_friction),
            ("dynamic_friction", params.dynamic_friction),
        ) if value < 0
    ]
    if below_zero:
        raise ValueError(f"Friction cannot be below zero; got {', '.join(below_zero)}.")
    if params.restitution is not None and not 0.0 <= params.restitution <= 1.0:
        raise ValueError(
            f"restitution goes from 0 (no bounce) to 1 (full bounce); got {params.restitution:g}.",
        )


def refuse_masked_binding(stage: Usd.Stage, asset_dir: Path, asset_prim_path: str) -> None:
    """Refuse an asset binding that a scene binding on a placement would hide."""
    masking = authoring.opinions.find_physics_masking_opinions(
        stage, asset_dir, asset_prim_path,
        relationships={_binding_name(): []},
    )
    if masking:
        placements = ", ".join(sorted(path for path, _, _ in masking))
        raise ValueError(
            f"{len(masking)} placement(s) already bind a physics material in scene.usda, "
            f"which wins over the asset's: {placements}. Remove those first with "
            "remove_physics_material, or bind this one with scope='scene'.",
        )

# ── Removing ──


def unbind_from_scene(stage: Usd.Stage, prim_path: str) -> dict[str, Any] | None:
    """Take the scene's physics binding off *prim_path*; None when it has none there.

    The material is deleted too once nothing in the scene binds it.
    """
    layer = stage.GetRootLayer()
    material_path = _unbind(layer, prim_path)
    if material_path is None:
        return None
    deleted = _delete_if_unused(layer, stage, material_path)
    layer.Save()
    return {"material": material_path, "material_deleted": deleted, "scope": "scene"}


def unbind_from_asset(
    asset_dir: Path, prim_path: str, *, scene_stage: Usd.Stage,
) -> dict[str, Any] | None:
    """Take the asset's physics binding off *prim_path*; None when ``phy.usda`` has none.

    The material is deleted too once nothing in the asset binds it.
    """
    phy_path = physics.layer.file_path(asset_dir)
    layer = Sdf.Layer.FindOrOpen(str(phy_path)) if phy_path.exists() else None
    spec = layer.GetPrimAtPath(prim_path) if layer is not None else None
    if spec is None or _binding_name() not in spec.relationships:
        return None
    doing = f"Removing the physics material from {prim_path} in asset {asset_dir.name}"
    with physics.layer.edit(asset_dir, scene_stage, doing) as stage:
        edit_layer = stage.GetRootLayer()
        material_path = _unbind(edit_layer, prim_path)
        root_file = authoring.asset_folder.find_root_file(asset_dir)
        composed = Usd.Stage.Open(str(root_file))
        deleted = _delete_if_unused(edit_layer, composed, str(material_path))
        del composed
    return {"material": material_path, "material_deleted": deleted, "scope": "asset"}

# ── Helpers ──


def _binding_name() -> str:
    """The relationship a physics binding is written as: ``material:binding:physics``."""
    return f"{UsdShade.Tokens.materialBinding}:{constants.PhysicsRules.MATERIAL_PURPOSE}"


def _asset_material_path(asset_dir: Path, name: str) -> str:
    """Where the asset keeps the physics material *name*."""
    default_prim = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    return f"/{default_prim}/{constants.PhysicsNamespace.MATERIALS_SCOPE}/{name}"


def _require_asset_prim(asset_dir: Path, prim_path: str) -> Usd.Stage:
    """The asset's composed stage, after checking *prim_path* exists in it."""
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        raise ValueError(f"No root file in asset {asset_dir.name}")
    composed = Usd.Stage.Open(str(root_file))
    prim = composed.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found in asset {asset_dir.name}: {prim_path}")
    return composed


def _require_material(stage: Usd.Stage, material_path: str, where: str) -> Usd.Prim:
    """The physics material at *material_path*; refused when *where* has none by that name."""
    prim = stage.GetPrimAtPath(material_path)
    if not prim or not prim.IsValid() or not prim.HasAPI(UsdPhysics.MaterialAPI):
        raise ValueError(
            f"No physics material named '{Sdf.Path(material_path).name}' in {where}. "
            "Create it with create_physics_material; get_physics_summary shows the ones there are.",
        )
    return prim


def _author(stage: Usd.Stage, material_path: str, params: schemas.PhysicsMaterialParams) -> None:
    """Write the material at the stage's edit target, or update the values it has."""
    existing = stage.GetPrimAtPath(material_path)
    if existing and existing.IsValid() and not existing.HasAPI(UsdPhysics.MaterialAPI):
        raise ValueError(
            f"The name '{params.name}' is taken: {material_path} is a "
            f"{existing.GetTypeName() or 'prim'}, not a physics material. Use another name.",
        )
    layer = stage.GetEditTarget().GetLayer()
    registry = Usd.SchemaRegistry()
    path = Sdf.Path(material_path)
    scope = path.GetParentPath()
    if layer.GetPrimAtPath(scope) is None or not stage.GetPrimAtPath(scope).IsDefined():
        scope_spec = Sdf.CreatePrimInLayer(layer, scope)
        scope_spec.specifier = Sdf.SpecifierDef
        scope_spec.typeName = "Scope"
    spec = Sdf.CreatePrimInLayer(layer, path)
    spec.specifier = Sdf.SpecifierDef
    spec.typeName = registry.GetConcreteSchemaTypeName(UsdShade.Material)

    api = UsdPhysics.MaterialAPI.Apply(stage.GetPrimAtPath(path))
    api.CreateStaticFrictionAttr(params.static_friction)
    api.CreateDynamicFrictionAttr(params.dynamic_friction)
    if params.restitution is not None:
        api.CreateRestitutionAttr(params.restitution)


def _bind(target: Usd.Prim, material: Usd.Prim) -> None:
    """Bind *material* to *target* for physics only; the look it renders with is left as it is."""
    UsdShade.MaterialBindingAPI.Apply(target).Bind(
        UsdShade.Material(material),
        UsdShade.Tokens.fallbackStrength,
        constants.PhysicsRules.MATERIAL_PURPOSE,
    )


def _unbind(layer: Sdf.Layer, prim_path: str) -> str | None:
    """Delete the physics binding *layer* writes on *prim_path*; return the material it named."""
    spec = layer.GetPrimAtPath(prim_path)
    rel = spec.relationships.get(_binding_name()) if spec is not None else None
    if rel is None:
        return None
    targets = [str(target) for target in rel.targetPathList.GetAddedOrExplicitItems()]
    spec.RemoveProperty(rel)
    still_binds = any(
        name.startswith(UsdShade.Tokens.materialBinding) for name in spec.relationships.keys()
    )
    if not still_binds:
        usd.attributes.drop_api_schema(
            spec, Usd.SchemaRegistry().GetAPISchemaTypeName(UsdShade.MaterialBindingAPI),
        )
    usd.namespace.prune_empty_overrides(layer, prim_path)
    return targets[0] if targets else ""


def _delete_if_unused(layer: Sdf.Layer, stage: Usd.Stage, material_path: str) -> bool:
    """Delete the material from *layer* when no prim on *stage* binds it for physics any more."""
    if not material_path or layer.GetPrimAtPath(material_path) is None:
        return False
    for prim in stage.TraverseAll():
        rel = prim.GetRelationship(_binding_name())
        if rel and material_path in {str(target) for target in rel.GetTargets()}:
            return False
    edit = Sdf.BatchNamespaceEdit()
    edit.Add(Sdf.Path(material_path), Sdf.Path.emptyPath)
    if not layer.Apply(edit):
        return False
    scope = layer.GetPrimAtPath(Sdf.Path(material_path).GetParentPath())
    if scope is not None and scope.typeName == "Scope" and not scope.nameChildren:
        scope_edit = Sdf.BatchNamespaceEdit()
        scope_edit.Add(scope.path, Sdf.Path.emptyPath)
        layer.Apply(scope_edit)
    return True
