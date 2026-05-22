# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Physics service — asset-level UsdPhysics applied-API orchestration.

Writes default opinions to ``phy.usda``. Refuses to write when
``scene.usda`` already has authored opinions that would mask the asset
default, unless the caller passes ``clear_masking_overrides=True`` (drop
the scene opinions and write phy.usda) or ``confirm_masked=True`` (write
phy.usda anyway, knowing scene overrides will keep winning on those
placements). Mirrors the variant authoring discipline.
"""

from __future__ import annotations

import logging
from typing import Any

from bowerbot.schemas import PhysicsApiName
from bowerbot.state import SceneState
from bowerbot.utils import physics_utils, stage_utils
from bowerbot.utils.asset_folder_utils import (
    normalize_asset_prim_path,
    require_asset_context,
    resolve_default_prim_name,
)

logger = logging.getLogger(__name__)


def list_api_properties(
    _state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return every property the given UsdPhysics API declares."""
    api_name = PhysicsApiName(params["api_name"])
    return physics_utils.list_api_properties(api_name).model_dump()


def apply_api(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Apply a UsdPhysics API to a prim and author opinions in the asset."""
    api_name = PhysicsApiName(params["api_name"])
    prim_path = params["prim_path"]
    attributes = params.get("attributes") or {}
    relationships = params.get("relationships") or {}

    asset_dir, ref_prim_path = require_asset_context(state.stage, prim_path)
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
        "Service applied %s on %s (asset %s)",
        api_name.value, prim_path, asset_dir.name,
    )
    return {
        **result,
        "asset_folder": asset_dir.name,
        "scene_prim_path": prim_path,
        "asset_prim_path": asset_local_path,
        "cleared_masking_opinions": [
            {"prim_path": p, "kind": k, "key": key}
            for p, k, key in cleared
        ],
    }


def remove_api(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove a UsdPhysics API from a prim's asset-level opinions."""
    api_name = PhysicsApiName(params["api_name"])
    prim_path = params["prim_path"]

    asset_dir, ref_prim_path = require_asset_context(state.stage, prim_path)
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


def get_physics_summary(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Return the physics opinions authored in an asset's ``phy.usda``."""
    prim_path = params["prim_path"]
    asset_dir, _ = require_asset_context(state.stage, prim_path)
    return physics_utils.get_physics_summary(asset_dir).model_dump()
