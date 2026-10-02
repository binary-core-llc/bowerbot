# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics service — UsdPhysics applied-API orchestration.

Routes writes based on the ``scope`` param:

- ``"asset"`` (default): authors into the asset's ``phy.usda`` after a
  masking scan of ``scene.usda``. Refuses when scene overrides would
  mask the write unless ``clear_masking_overrides`` or ``confirm_masked``
  is set.
- ``"scene"``: authors directly on the scene stage at the given prim
  path (per-placement override or scene-only prim). No masking scan.

Also exposes ``setup_physics_scene`` (creates ``/Scene/Physics`` +
``UsdPhysics.Scene``) and ``get_physics_summary`` (asset + scene).
"""

from __future__ import annotations

import logging
from typing import Any

from bowerbot import constants
from bowerbot import scene_state
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import physics
from bowerbot.utils import usd

logger = logging.getLogger(__name__)


def list_physics_api_properties(
    _state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every property the given UsdPhysics API declares."""
    api_name = schemas.PhysicsApiName(params["api_name"])
    return physics.apis.list_properties(
        api_name, instance_name=params.get("instance_name"),
    ).model_dump()


def apply_physics_api(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Apply a UsdPhysics API. Auto-detects scope when not explicitly given."""
    api_name = schemas.PhysicsApiName(params["api_name"])
    prim_path = params["prim_path"]
    attributes = params.get("attributes") or {}
    relationships = params.get("relationships") or {}
    instance_name = params.get("instance_name")
    scope = physics.scope.resolve(state.stage, prim_path, params.get("scope"))

    if scope == "scene":
        result = physics.apis.apply_in_scene(
            state.stage, prim_path, api_name, attributes, relationships,
            instance_name=instance_name,
            project_mpu=state.meters_per_unit, project_up_axis=state.up_axis.value,
        )
        logger.info(
            "Service applied %s scene-level on %s", api_name.value, prim_path,
        )
        return result

    asset_dir, asset_local_path = physics.scope.require_asset_target(
        state.stage, prim_path, scene_retry="author physics on this prim",
    )

    cleared = physics.masking.enforce(
        state.stage, asset_dir, asset_local_path,
        api_name, attributes, relationships,
        clear=bool(params.get("clear_masking_overrides", False)),
        confirm=bool(params.get("confirm_masked", False)),
    )

    result = physics.apis.apply_in_asset(
        asset_dir, asset_local_path, api_name, attributes, relationships,
        instance_name=instance_name, scene_stage=state.stage,
    )
    state.reload_stage()

    logger.info(
        "Service applied %s asset-level on %s (asset %s)",
        api_name.value, prim_path, asset_dir.name,
    )
    # prim_path is where the API landed in the scene; the path inside the asset's
    # own files is asset_prim_path.
    asset_target = result["prim_path"]
    scene_target = (
        prim_path + asset_target[len(asset_local_path):]
        if asset_target.startswith(asset_local_path) else prim_path
    )
    return {
        **result,
        "prim_path": scene_target,
        "scope": "asset",
        "asset_folder": asset_dir.name,
        "scene_prim_path": prim_path,
        "asset_prim_path": asset_target,
        "cleared_masking_opinions": physics.masking.cleared_rows(cleared),
    }


def remove_physics_api(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove a UsdPhysics API. Auto-detects scope when not explicitly given."""
    api_name = schemas.PhysicsApiName(params["api_name"])
    prim_path = params["prim_path"]
    instance_name = params.get("instance_name")
    scope = physics.scope.resolve(state.stage, prim_path, params.get("scope"))
    api_label = (
        f"{api_name.value}:{instance_name}" if instance_name
        else api_name.value
    )

    if scope == "scene":
        changed = physics.apis.remove_from_scene(
            state.stage, prim_path, api_name,
            instance_name=instance_name,
        )
        return {
            "scope": "scene",
            "prim_path": prim_path,
            "api_name": api_name.value,
            "instance_name": instance_name,
            "removed": changed,
            "message": (
                f"Removed {api_label} from {prim_path}"
                if changed
                else f"{api_label} was not present on {prim_path}"
            ),
        }

    asset_dir, asset_local_path = physics.scope.require_asset_target(
        state.stage, prim_path, scene_retry="remove physics from this prim",
    )

    api_props = physics.apis.list_properties(
        api_name, instance_name=instance_name,
    ).properties
    attr_names = {p.name: None for p in api_props if p.kind == "attribute"}
    rel_names = {p.name: [] for p in api_props if p.kind == "relationship"}

    cleared = physics.masking.enforce(
        state.stage, asset_dir, asset_local_path,
        api_name, attr_names, rel_names,
        clear=bool(params.get("clear_masking_overrides", False)),
        confirm=bool(params.get("confirm_masked", False)),
    )

    changed = physics.apis.remove_from_asset(
        asset_dir, asset_local_path, api_name,
        instance_name=instance_name, scene_stage=state.stage,
    )
    if changed:
        physics.layer.cleanup_if_empty(asset_dir)
    state.reload_stage()

    return {
        "scope": "asset",
        "scene_prim_path": prim_path,
        "asset_prim_path": asset_local_path,
        "asset_folder": asset_dir.name,
        "api_name": api_name.value,
        "removed": changed,
        "message": (
            f"Removed {api_label} from {asset_local_path}"
            if changed
            else f"{api_label} was not present on {asset_local_path}"
        ),
        "cleared_masking_opinions": physics.masking.cleared_rows(cleared),
    }


def setup_physics_scene(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Create ``/Scene/Physics`` and a ``UsdPhysics.Scene`` child."""
    name = params.get("name", "PhysicsScene")
    gravity_magnitude = params.get("gravity_magnitude")
    gravity_direction = usd.values.parse_vec3(
        params.get("gravity_direction"), "gravity_direction",
    )

    scene_path, resolved_magnitude, resolved_direction = physics.scenes.setup(
        state.stage,
        name=name,
        gravity_magnitude=gravity_magnitude,
        gravity_direction=gravity_direction,
        project_mpu=state.meters_per_unit,
        project_up_axis=state.up_axis.value,
    )
    logger.info("setup_physics_scene -> %s", scene_path)
    return {
        "prim_path": scene_path,
        "gravity_magnitude": resolved_magnitude,
        "gravity_direction": list(resolved_direction),
    }


def list_physics_scenes(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every UsdPhysics.Scene prim under /Scene/Physics."""
    scenes = physics.scenes.list_all(state.stage)
    return {"scenes": scenes, "count": len(scenes)}


def remove_physics_scene(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Remove a UsdPhysics.Scene prim by name."""
    name = params["name"]
    removed = physics.scenes.remove(state.stage, name)
    return {
        "name": name,
        "removed": removed,
        "message": (
            f"Removed PhysicsScene '{name}'"
            if removed
            else f"PhysicsScene '{name}' not found under /Scene/Physics"
        ),
    }


def get_physics_summary(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return asset-side + scene-side physics opinions for a prim path."""
    prim_path = params["prim_path"]
    asset_dir, _ = authoring.placement.resolve_asset_dir_for_prim(state.stage, prim_path)

    asset_summary = (
        physics.summary.summarize_asset(asset_dir)
        if asset_dir is not None else None
    )
    scene_summary = physics.summary.summarize_scene_prim(
        state.stage, prim_path,
    )
    return {
        "asset": asset_summary.model_dump() if asset_summary else None,
        "scene": scene_summary.model_dump(),
    }


# ── Collider shapes ──


def add_collider_shape(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Add a basic collider shape under a part. Auto-detects scope when not explicitly given."""
    parent_path = params["prim_path"]
    shape = physics.colliders.shape_from_params(params)
    scope = physics.scope.resolve(state.stage, parent_path, params.get("scope"))

    if scope == "scene":
        result = physics.colliders.add_in_scene(state.stage, parent_path, shape)
        return {
            **result,
            "parent_prim_path": parent_path,
            "message": (
                f"Added a {shape.shape.value} collider at {result['prim_path']}. "
                "Only physics uses it: its purpose is guide, so renders skip it."
            ),
        }

    asset_dir, asset_parent = physics.scope.require_asset_target(
        state.stage, parent_path, scene_retry="add the collider under this prim",
    )
    _, ref_prim_path = authoring.placement.require_asset_context(state.stage, parent_path)
    default_prim = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    scene_parent = ref_prim_path + asset_parent[len(f"/{default_prim}"):]

    result = physics.colliders.add_in_asset(
        asset_dir, asset_parent, shape,
        scene_stage=state.stage, scene_parent_path=scene_parent,
    )
    state.reload_stage()
    prim_path = f"{scene_parent}/{shape.name}"
    return {
        **result,
        "prim_path": prim_path,
        "parent_prim_path": scene_parent,
        "asset_prim_path": result["prim_path"],
        "asset_folder": asset_dir.name,
        "message": (
            f"Added a {shape.shape.value} collider at {prim_path}, in "
            f"{asset_dir.name}/{constants.ASWFLayerNames.PHY}: every placement of the asset "
            "has it. Only physics uses it: its purpose is guide, so renders skip it."
        ),
    }


def remove_collider_shape(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove a collider shape added with add_collider_shape, wherever it was written."""
    prim_path = params["prim_path"]
    removed = physics.colliders.remove_from_scene(state.stage, prim_path)
    scope = "scene"
    if not removed and physics.scope.autodetect(state.stage, prim_path) == "asset":
        scope = "asset"
        asset_dir, asset_prim_path = physics.scope.require_asset_target(
            state.stage, prim_path, scene_retry="remove the collider from this prim",
        )
        removed = physics.colliders.remove_from_asset(asset_dir, asset_prim_path)
        if removed:
            physics.layer.cleanup_if_empty(asset_dir)
            state.reload_stage()
    if not removed:
        physics.colliders.refuse_other_prim(state.stage, prim_path)
    return {
        "prim_path": prim_path,
        "removed": removed,
        "scope": scope if removed else None,
        "message": (
            f"Removed the collider shape {prim_path}" if removed
            else f"No collider shape at {prim_path}"
        ),
    }


# ── Joints + articulation ──


def list_joint_properties(
    _state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every property the given joint typed prim declares."""
    joint_type = schemas.PhysicsJointType(params["joint_type"])
    return physics.joints.list_properties(joint_type).model_dump()


def create_joint(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create a typed joint connecting two bodies. Routes by ``scope``."""
    joint_type = schemas.PhysicsJointType(params["joint_type"])
    name = params["name"]
    body0 = params.get("body0")
    body1 = params.get("body1")
    attributes = params.get("attributes") or {}
    scope = physics.scope.validate(params.get("scope", "scene"))

    if scope == "scene":
        result = physics.joints.create_in_scene(
            state.stage, joint_type, name, body0, body1, attributes,
            project_mpu=state.meters_per_unit, project_up_axis=state.up_axis.value,
        )
        logger.info(
            "Service created %s scene-level (%s)", joint_type.value, name,
        )
        return result

    asset_anchor = params.get("asset_anchor_prim_path") or body0 or body1
    if not asset_anchor:
        raise ValueError(
            "scope='asset' requires body0, body1, or "
            "asset_anchor_prim_path so BowerBot can find the asset folder.",
        )
    asset_dir, ref_prim_path = authoring.placement.require_asset_context(state.stage, asset_anchor)

    for label, body in (("body0", body0), ("body1", body1)):
        if not body:
            continue
        body_asset_dir, _ = authoring.placement.resolve_asset_dir_for_prim(state.stage, body)
        if body_asset_dir is None:
            raise ValueError(
                f"scope='asset' but {label}={body!r} is not inside "
                "any asset placement. Use scope='scene' for joints "
                "that connect to scene-only prims.",
            )
        if body_asset_dir != asset_dir:
            raise ValueError(
                f"scope='asset' requires both bodies in the SAME asset "
                f"placement. The anchor resolves to {asset_dir.name!r}, "
                f"but {label}={body!r} resolves to {body_asset_dir.name!r}. "
                "Use scope='scene' for cross-asset joints.",
            )

    default_prim = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    asset_body0 = (
        authoring.placement.normalize_asset_prim_path(body0, ref_prim_path, default_prim)
        if body0 else None
    )
    asset_body1 = (
        authoring.placement.normalize_asset_prim_path(body1, ref_prim_path, default_prim)
        if body1 else None
    )

    result = physics.joints.create_in_asset(
        asset_dir, joint_type, name,
        asset_body0, asset_body1, attributes, scene_stage=state.stage,
    )
    state.reload_stage()
    logger.info(
        "Service created %s asset-level (%s in %s)",
        joint_type.value, name, asset_dir.name,
    )
    asset_joint = result["prim_path"]
    return {
        **result,
        "prim_path": ref_prim_path + asset_joint[len(f"/{default_prim}"):],
        "asset_prim_path": asset_joint,
        "scene_body0": body0,
        "scene_body1": body1,
    }


def remove_joint(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove a joint prim. Routes by ``scope``."""
    scope = physics.scope.validate(params.get("scope", "scene"))

    if scope == "scene":
        prim_path = params["prim_path"]
        removed = physics.joints.remove_from_scene(state.stage, prim_path)
        return {"scope": "scene", "prim_path": prim_path, "removed": removed}

    asset_anchor = (
        params.get("asset_anchor_prim_path")
        or params.get("prim_path")
    )
    if not asset_anchor:
        raise ValueError(
            "scope='asset' requires asset_anchor_prim_path (a scene "
            "placement of the asset) to locate the asset folder.",
        )
    asset_dir, _ = authoring.placement.require_asset_context(state.stage, asset_anchor)
    name = params["name"]
    removed = physics.joints.remove_from_asset(asset_dir, name)
    if removed:
        physics.layer.cleanup_if_empty(asset_dir)
        state.reload_stage()
    return {
        "scope": "asset",
        "asset_folder": asset_dir.name,
        "name": name,
        "removed": removed,
    }


def list_joints(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List joints scene-wide, scoped under a prim, or inside an asset folder."""
    scope = physics.scope.validate(params.get("scope", "scene"))

    if scope == "scene":
        under = params.get("under_prim_path")
        return physics.joints.list_on_stage(state.stage, under).model_dump()

    asset_anchor = params.get("asset_anchor_prim_path")
    if not asset_anchor:
        raise ValueError(
            "scope='asset' requires asset_anchor_prim_path (a scene "
            "placement of the asset) to locate the asset folder.",
        )
    asset_dir, _ = authoring.placement.require_asset_context(state.stage, asset_anchor)
    return physics.joints.list_in_asset(asset_dir).model_dump()


def create_or_update_collision_group(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Create or update a ``UsdPhysicsCollisionGroup`` under /Scene/Physics/Groups."""
    result = physics.collision_groups.create_or_update(
        state.stage,
        params["name"],
        includes=params.get("includes"),
        excludes=params.get("excludes"),
        filtered_groups=params.get("filtered_groups"),
        invert_filter=params.get("invert_filter"),
        merge_group=params.get("merge_group"),
        project_mpu=state.meters_per_unit,
        project_up_axis=state.up_axis.value,
    )
    return result


def remove_collision_group(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Remove a collision group; relies on scene_integrity to scrub dangling rels."""
    name = params["name"]
    force = bool(params.get("force", False))
    removed = physics.collision_groups.remove(
        state.stage, name, force=force,
    )
    scrubbed = (
        usd.namespace.scrub_dangling_refs(state.stage) if removed else {}
    )
    authoring.stage.save_stage(state.stage)
    return {
        "name": name,
        "removed": removed,
        "scrubbed_dangling_refs": scrubbed,
    }


def list_collision_groups(
    _state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every collision group with its membership, filters, and merge token."""
    summary = physics.collision_groups.list_all(_state.stage)
    return summary.model_dump()
