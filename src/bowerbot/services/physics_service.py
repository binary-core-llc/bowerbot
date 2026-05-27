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
from bowerbot.utils import physics_utils, scene_integrity_utils, stage_utils
from bowerbot.utils.asset_folder_utils import (
    normalize_asset_prim_path,
    require_asset_context,
    resolve_asset_dir_for_prim,
    resolve_default_prim_name,
)

logger = logging.getLogger(__name__)


def list_physics_api_properties(
    _state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every property the given UsdPhysics API declares."""
    api_name = PhysicsApiName(params["api_name"])
    return physics_utils.list_api_properties(api_name).model_dump()


def apply_physics_api(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Apply a UsdPhysics API. Auto-detects scope when not explicitly given."""
    api_name = PhysicsApiName(params["api_name"])
    prim_path = params["prim_path"]
    attributes = params.get("attributes") or {}
    relationships = params.get("relationships") or {}
    explicit_scope = params.get("scope")
    scope = (
        physics_utils.validate_scope(explicit_scope) if explicit_scope
        else physics_utils.autodetect_scope(state.stage, prim_path)
    )

    if scope == "scene":
        result = physics_utils.apply_api_scene(
            state.stage, prim_path, api_name, attributes, relationships,
        )
        state.touch_project()
        logger.info(
            "Service applied %s scene-level on %s", api_name.value, prim_path,
        )
        return result

    try:
        asset_dir, ref_prim_path = require_asset_context(
            state.stage, prim_path,
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

    cleared = physics_utils.enforce_masking_policy(
        state.stage, asset_dir, asset_local_path,
        api_name, attributes, relationships,
        clear=bool(params.get("clear_masking_overrides", False)),
        confirm=bool(params.get("confirm_masked", False)),
    )

    result = physics_utils.apply_api(
        asset_dir, asset_local_path, api_name, attributes, relationships,
    )
    state.stage = stage_utils.open_stage(state.stage_path)
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
    api_name = PhysicsApiName(params["api_name"])
    prim_path = params["prim_path"]
    explicit_scope = params.get("scope")
    scope = (
        physics_utils.validate_scope(explicit_scope) if explicit_scope
        else physics_utils.autodetect_scope(state.stage, prim_path)
    )

    if scope == "scene":
        changed = physics_utils.remove_api_scene(
            state.stage, prim_path, api_name,
        )
        if changed:
            state.touch_project()
        return {
            "scope": "scene",
            "prim_path": prim_path,
            "api_name": api_name.value,
            "removed": changed,
        }

    try:
        asset_dir, ref_prim_path = require_asset_context(
            state.stage, prim_path,
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

    api_props = physics_utils.list_api_properties(api_name).properties
    attr_names = {p.name: None for p in api_props if p.kind == "attribute"}
    rel_names = {p.name: [] for p in api_props if p.kind == "relationship"}

    cleared = physics_utils.enforce_masking_policy(
        state.stage, asset_dir, asset_local_path,
        api_name, attr_names, rel_names,
        clear=bool(params.get("clear_masking_overrides", False)),
        confirm=bool(params.get("confirm_masked", False)),
    )

    changed = physics_utils.remove_api(
        asset_dir, asset_local_path, api_name,
    )
    if changed:
        physics_utils.cleanup_if_empty(asset_dir)
    state.stage = stage_utils.open_stage(state.stage_path)
    state.touch_project()

    return {
        "scope": "asset",
        "scene_prim_path": prim_path,
        "asset_prim_path": asset_local_path,
        "asset_folder": asset_dir.name,
        "api_name": api_name.value,
        "removed": changed,
        "cleared_masking_opinions": [
            {"prim_path": p, "kind": k, "key": key}
            for p, k, key in cleared
        ],
    }


def setup_physics_scene(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Create ``/Scene/Physics`` and a ``UsdPhysics.Scene`` child."""
    name = params.get("name", "PhysicsScene")
    gravity_magnitude = params.get("gravity_magnitude")
    gravity_direction = physics_utils.parse_vec3(
        params.get("gravity_direction"), "gravity_direction",
    )

    scene_path = physics_utils.ensure_physics_scene(
        state.stage,
        name=name,
        gravity_magnitude=gravity_magnitude,
        gravity_direction=gravity_direction,
    )
    state.touch_project()
    logger.info("setup_physics_scene -> %s", scene_path)
    return {
        "prim_path": scene_path,
        "gravity_magnitude": gravity_magnitude,
        "gravity_direction": gravity_direction,
    }


def get_physics_summary(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return asset-side + scene-side physics opinions for a prim path."""
    prim_path = params["prim_path"]
    asset_dir, _ = resolve_asset_dir_for_prim(state.stage, prim_path)

    asset_summary = (
        physics_utils.get_physics_summary(asset_dir)
        if asset_dir is not None else None
    )
    scene_summary = physics_utils.get_scene_physics_summary(
        state.stage, prim_path,
    )
    return {
        "asset": asset_summary.model_dump() if asset_summary else None,
        "scene": scene_summary.model_dump(),
    }


# ── Joints + articulation ──


def list_joint_properties(
    _state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every property the given joint typed prim declares."""
    joint_type = PhysicsJointType(params["joint_type"])
    return physics_utils.list_joint_properties(joint_type).model_dump()


def create_joint(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Create a typed joint connecting two bodies. Routes by ``scope``."""
    joint_type = PhysicsJointType(params["joint_type"])
    name = params["name"]
    body0 = params.get("body0")
    body1 = params.get("body1")
    attributes = params.get("attributes") or {}
    scope = physics_utils.validate_scope(params.get("scope", "scene"))

    if scope == "scene":
        result = physics_utils.create_joint_scene(
            state.stage, joint_type, name, body0, body1, attributes,
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
    asset_dir, ref_prim_path = require_asset_context(state.stage, asset_anchor)

    for label, body in (("body0", body0), ("body1", body1)):
        if not body:
            continue
        body_asset_dir, _ = resolve_asset_dir_for_prim(state.stage, body)
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

    result = physics_utils.create_joint_asset(
        asset_dir, joint_type, name,
        asset_body0, asset_body1, attributes,
    )
    state.stage = stage_utils.open_stage(state.stage_path)
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
    scope = physics_utils.validate_scope(params.get("scope", "scene"))

    if scope == "scene":
        prim_path = params["prim_path"]
        removed = physics_utils.remove_joint_scene(state.stage, prim_path)
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
    asset_dir, _ = require_asset_context(state.stage, asset_anchor)
    name = params["name"]
    removed = physics_utils.remove_joint_asset(asset_dir, name)
    if removed:
        physics_utils.cleanup_if_empty(asset_dir)
        state.stage = stage_utils.open_stage(state.stage_path)
        state.touch_project()
    return {
        "scope": "asset",
        "asset_folder": asset_dir.name,
        "name": name,
        "removed": removed,
    }


def list_joints(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List joints scene-wide, scoped under a prim, or inside an asset folder."""
    scope = physics_utils.validate_scope(params.get("scope", "scene"))

    if scope == "scene":
        under = params.get("under_prim_path")
        return physics_utils.list_joints_scene(state.stage, under).model_dump()

    asset_anchor = params.get("asset_anchor_prim_path")
    if not asset_anchor:
        raise ValueError(
            "scope='asset' requires asset_anchor_prim_path (a scene "
            "placement of the asset) to locate the asset folder.",
        )
    asset_dir, _ = require_asset_context(state.stage, asset_anchor)
    return physics_utils.list_joints_asset(asset_dir).model_dump()


def create_or_update_collision_group(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Create or update a ``UsdPhysicsCollisionGroup`` under /Scene/Physics/Groups."""
    result = physics_utils.create_or_update_collision_group(
        state.stage,
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
    name = params["name"]
    force = bool(params.get("force", False))
    removed = physics_utils.remove_collision_group(
        state.stage, name, force=force,
    )
    scrubbed = (
        scene_integrity_utils.scrub_dangling_refs(state.stage) if removed else {}
    )
    if removed:
        state.touch_project()
    return {
        "name": name,
        "removed": removed,
        "scrubbed_dangling_refs": scrubbed,
    }


def list_collision_groups(
    _state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every collision group with its membership, filters, and merge token."""
    summary = physics_utils.list_collision_groups(_state.stage)
    return summary.model_dump()
