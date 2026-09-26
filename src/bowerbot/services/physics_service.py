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

from bowerbot.schemas import PhysicsApiName, PhysicsJointType
from bowerbot.state import SceneState
from bowerbot.utils import physics
from bowerbot.utils.core.asset_folder import (
    normalize_asset_prim_path,
    require_asset_context,
    resolve_asset_dir_for_prim,
    resolve_default_prim_name,
)
from bowerbot.utils.core.integrity import scrub_dangling_refs
from bowerbot.utils.core.values import parse_vec3

logger = logging.getLogger(__name__)


def list_physics_api_properties(
    _state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every property the given UsdPhysics API declares."""
    api_name = PhysicsApiName(params["api_name"])
    return physics.schema_info.list_api_properties(
        api_name, instance_name=params.get("instance_name"),
    ).model_dump()


def apply_physics_api(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Apply a UsdPhysics API. Auto-detects scope when not explicitly given."""
    stage = state.require_stage()
    api_name = PhysicsApiName(params["api_name"])
    prim_path = params["prim_path"]
    attributes = params.get("attributes") or {}
    relationships = params.get("relationships") or {}
    instance_name = params.get("instance_name")
    explicit_scope = params.get("scope")
    scope = (
        physics.scope.validate_scope(explicit_scope) if explicit_scope
        else physics.scope.autodetect_scope(stage, prim_path)
    )

    if scope == "scene":
        result = physics.apis.apply_api_scene(
            stage, prim_path, api_name, attributes, relationships,
            instance_name=instance_name,
        )
        state.touch_project()
        logger.info(
            "Service applied %s scene-level on %s", api_name.value, prim_path,
        )
        return result

    try:
        asset_dir, ref_prim_path = require_asset_context(
            stage, prim_path,
        )
    except ValueError as exc:
        raise ValueError(
            f"{exc} This prim is authored directly in scene.usda, not as "
            "an asset placement. Retry the call with scope='scene' to "
            "author physics on this prim directly in scene.usda.",
        ) from None
    asset_local_path = normalize_asset_prim_path(
        prim_path, ref_prim_path, resolve_default_prim_name(asset_dir),
    )

    cleared = physics.masking.enforce_masking_policy(
        stage, asset_dir, asset_local_path,
        api_name, attributes, relationships,
        clear=bool(params.get("clear_masking_overrides", False)),
        confirm=bool(params.get("confirm_masked", False)),
    )

    result = physics.apis.apply_api(
        asset_dir, asset_local_path, api_name, attributes, relationships,
        instance_name=instance_name,
    )
    state.reopen_stage()
    state.touch_project()

    logger.info(
        "Service applied %s asset-level on %s (asset %s)",
        api_name.value, prim_path, asset_dir.name,
    )
    return {
        **result,
        "scope": "asset",
        "asset_folder": asset_dir.name,
        "scene_prim_path": prim_path,
        "asset_prim_path": asset_local_path,
        "cleared_masking_opinions": [
            {"prim_path": p, "kind": k, "key": key}
            for p, k, key in cleared
        ],
    }


def remove_physics_api(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove a UsdPhysics API. Auto-detects scope when not explicitly given."""
    stage = state.require_stage()
    api_name = PhysicsApiName(params["api_name"])
    prim_path = params["prim_path"]
    instance_name = params.get("instance_name")
    explicit_scope = params.get("scope")
    scope = (
        physics.scope.validate_scope(explicit_scope) if explicit_scope
        else physics.scope.autodetect_scope(stage, prim_path)
    )

    if scope == "scene":
        changed = physics.apis.remove_api_scene(
            stage, prim_path, api_name,
            instance_name=instance_name,
        )
        if changed:
            state.touch_project()
        api_label = (
            f"{api_name.value}:{instance_name}" if instance_name
            else api_name.value
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

    try:
        asset_dir, ref_prim_path = require_asset_context(
            stage, prim_path,
        )
    except ValueError as exc:
        raise ValueError(
            f"{exc} This prim is authored directly in scene.usda, not as "
            "an asset placement. Retry the call with scope='scene' to "
            "remove physics from this prim directly in scene.usda.",
        ) from None
    asset_local_path = normalize_asset_prim_path(
        prim_path, ref_prim_path, resolve_default_prim_name(asset_dir),
    )

    api_props = physics.schema_info.list_api_properties(
        api_name, instance_name=instance_name,
    ).properties
    attr_names = {p.name: None for p in api_props if p.kind == "attribute"}
    rel_names: dict[str, list[str]] = {p.name: [] for p in api_props if p.kind == "relationship"}

    cleared = physics.masking.enforce_masking_policy(
        stage, asset_dir, asset_local_path,
        api_name, attr_names, rel_names,
        clear=bool(params.get("clear_masking_overrides", False)),
        confirm=bool(params.get("confirm_masked", False)),
    )

    changed = physics.apis.remove_api(
        asset_dir, asset_local_path, api_name,
        instance_name=instance_name,
    )
    if changed:
        physics.summary.remove_physics_layer_if_empty(asset_dir)
    state.reopen_stage()
    state.touch_project()

    api_label = (
        f"{api_name.value}:{instance_name}" if instance_name
        else api_name.value
    )
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
        "cleared_masking_opinions": [
            {"prim_path": p, "kind": k, "key": key}
            for p, k, key in cleared
        ],
    }


def setup_physics_scene(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Create ``/Scene/Physics`` and a ``UsdPhysics.Scene`` child."""
    stage = state.require_stage()
    name = params.get("name", "PhysicsScene")
    gravity_magnitude = params.get("gravity_magnitude")
    gravity_direction = parse_vec3(
        params.get("gravity_direction"), "gravity_direction",
    )

    scene_path = physics.scene.ensure_physics_scene(
        stage,
        name=name,
        gravity_magnitude=gravity_magnitude,
        gravity_direction=gravity_direction,
    )
    resolved_magnitude, resolved_direction = physics.scene.resolve_gravity(
        stage, gravity_magnitude, gravity_direction,
    )
    state.touch_project()
    logger.info("setup_physics_scene -> %s", scene_path)
    return {
        "prim_path": scene_path,
        "gravity_magnitude": resolved_magnitude,
        "gravity_direction": list(resolved_direction),
    }


def list_physics_scenes(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every UsdPhysics.Scene prim under /Scene/Physics."""
    stage = state.require_stage()
    scenes = physics.scene.list_physics_scenes(stage)
    return {"scenes": scenes, "count": len(scenes)}


def remove_physics_scene(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Remove a UsdPhysics.Scene prim by name."""
    stage = state.require_stage()
    name = params["name"]
    removed = physics.scene.remove_physics_scene(stage, name)
    if removed:
        state.touch_project()
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
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return asset-side + scene-side physics opinions for a prim path."""
    stage = state.require_stage()
    prim_path = params["prim_path"]
    asset_dir, _ = resolve_asset_dir_for_prim(stage, prim_path)

    asset_summary = (
        physics.summary.get_physics_summary(asset_dir)
        if asset_dir is not None else None
    )
    scene_summary = physics.summary.get_scene_physics_summary(
        stage, prim_path,
    )
    return {
        "asset": asset_summary.model_dump() if asset_summary else None,
        "scene": scene_summary.model_dump(),
    }


# ── Joints + articulation ──


def list_joint_properties(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every property the given joint typed prim declares."""
    state.require_stage()
    joint_type = PhysicsJointType(params["joint_type"])
    return physics.schema_info.list_joint_properties(joint_type).model_dump()


def create_joint(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create a typed joint connecting two bodies. Routes by ``scope``."""
    stage = state.require_stage()
    joint_type = PhysicsJointType(params["joint_type"])
    name = params["name"]
    body0 = params.get("body0")
    body1 = params.get("body1")
    attributes = params.get("attributes") or {}
    scope = physics.scope.validate_scope(params.get("scope", "scene"))

    if scope == "scene":
        result = physics.joints.create_joint_scene(
            stage, joint_type, name, body0, body1, attributes,
        )
        state.touch_project()
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
    asset_dir, ref_prim_path = require_asset_context(stage, asset_anchor)

    for label, body in (("body0", body0), ("body1", body1)):
        if not body:
            continue
        body_asset_dir, _ = resolve_asset_dir_for_prim(stage, body)
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

    default_prim = resolve_default_prim_name(asset_dir)
    asset_body0 = (
        normalize_asset_prim_path(body0, ref_prim_path, default_prim)
        if body0 else None
    )
    asset_body1 = (
        normalize_asset_prim_path(body1, ref_prim_path, default_prim)
        if body1 else None
    )

    result = physics.joints.create_joint_asset(
        asset_dir, joint_type, name,
        asset_body0, asset_body1, attributes,
    )
    state.reopen_stage()
    state.touch_project()
    logger.info(
        "Service created %s asset-level (%s in %s)",
        joint_type.value, name, asset_dir.name,
    )
    return {
        **result,
        "scene_body0": body0,
        "scene_body1": body1,
    }


def remove_joint(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove a joint prim. Routes by ``scope``."""
    stage = state.require_stage()
    scope = physics.scope.validate_scope(params.get("scope", "scene"))

    if scope == "scene":
        prim_path = params["prim_path"]
        removed = physics.joints.remove_joint_scene(stage, prim_path)
        if removed:
            state.touch_project()
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
    asset_dir, _ = require_asset_context(stage, asset_anchor)
    name = params["name"]
    removed = physics.joints.remove_joint_asset(asset_dir, name)
    if removed:
        physics.summary.remove_physics_layer_if_empty(asset_dir)
        state.reopen_stage()
        state.touch_project()
    return {
        "scope": "asset",
        "asset_folder": asset_dir.name,
        "name": name,
        "removed": removed,
    }


def list_joints(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List joints scene-wide, scoped under a prim, or inside an asset folder."""
    stage = state.require_stage()
    scope = physics.scope.validate_scope(params.get("scope", "scene"))

    if scope == "scene":
        under = params.get("under_prim_path")
        return physics.joints.list_joints_scene(stage, under).model_dump()

    asset_anchor = params.get("asset_anchor_prim_path")
    if not asset_anchor:
        raise ValueError(
            "scope='asset' requires asset_anchor_prim_path (a scene "
            "placement of the asset) to locate the asset folder.",
        )
    asset_dir, _ = require_asset_context(stage, asset_anchor)
    return physics.joints.list_joints_asset(asset_dir).model_dump()


def create_or_update_collision_group(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Create or update a ``UsdPhysicsCollisionGroup`` under /Scene/Physics/Groups."""
    stage = state.require_stage()
    result = physics.groups.create_or_update_collision_group(
        stage,
        params["name"],
        includes=params.get("includes"),
        excludes=params.get("excludes"),
        filtered_groups=params.get("filtered_groups"),
        invert_filter=params.get("invert_filter"),
        merge_group=params.get("merge_group"),
    )
    state.touch_project()
    return result


def remove_collision_group(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Remove a collision group; relies on scene_integrity to scrub dangling rels."""
    stage = state.require_stage()
    name = params["name"]
    force = bool(params.get("force", False))
    removed = physics.groups.remove_collision_group(
        stage, name, force=force,
    )
    scrubbed = (
        scrub_dangling_refs(stage) if removed else {}
    )
    if removed:
        state.touch_project()
    return {
        "name": name,
        "removed": removed,
        "scrubbed_dangling_refs": scrubbed,
    }


def list_collision_groups(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every collision group with its membership, filters, and merge token."""
    stage = state.require_stage()
    summary = physics.groups.list_collision_groups(stage)
    return summary.model_dump()
