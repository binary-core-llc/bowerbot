# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant service — orchestrates variant set operations for the variant tools."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from bowerbot import scene_state
from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import usd
from bowerbot.utils import variants

logger = logging.getLogger(__name__)


# ── Category orchestrators ──


def add_asset_material_variant(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a material-binding variant on the asset's root prim."""
    asset_dir, ref_prim_path = authoring.placement.require_asset_context(
        state.stage, params["prim_path"],
    )
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = usd.values.require_dict_param(
        params, "bindings",
        "Each entry maps a mesh prim path to a material prim path "
        "(e.g. {'/Geo/Top': '/Materials/wood'}).",
    )
    default_prim = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    bindings = {
        authoring.placement.normalize_asset_prim_path(k, ref_prim_path, default_prim):
            authoring.placement.normalize_asset_prim_path(v, ref_prim_path, default_prim)
        for k, v in raw.items()
    }
    set_as_default = bool(params.get("set_as_default", False))
    confirm_masked = bool(params.get("confirm_masked", False))
    clear_masking = bool(params.get("clear_masking_overrides", False))
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)
    variants.asset.refuse_unknown_materials(asset_dir, bindings)

    masking = authoring.opinions.find_variant_masking_opinions(
        state.stage, asset_dir, default_prim,
        {path: ["material:binding"] for path in bindings}, "relationship",
    )
    if variants.masking.enforce(
        state.stage, masking, "relationship", "material",
        clear=clear_masking, confirm=confirm_masked,
    ):
        state.reload_stage()

    variants.asset.add(
        asset_dir, set_name, variant_name,
        lambda stage, _prim_path: variants.bodies.author_bindings(stage, bindings),
        set_as_default,
    )
    state.reload_stage()
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": schemas.VariantCategory.MATERIAL.value,
        "default_selected": set_as_default,
        "bindings": bindings,
        "message": (
            f"Added material variant '{variant_name}' to '{set_name}' "
            f"in {asset_dir.name}"
        ),
    }


def add_asset_geometry_variant(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a geometry/LOD variant via payload arc overrides."""
    asset_dir, ref_prim_path = authoring.placement.require_asset_context(
        state.stage, params["prim_path"],
    )
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = usd.values.require_dict_param(
        params, "payloads",
        "Each entry maps a prim path to a payload asset path "
        "(e.g. {'/Geo': './geo_low.usda'}).",
    )
    default_prim = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    payloads = {
        authoring.placement.normalize_asset_prim_path(k, ref_prim_path, default_prim): v
        for k, v in raw.items()
    }
    set_as_default = bool(params.get("set_as_default", False))
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)
    for payload_ref in payloads.values():
        variants.geometry.validate_payload_path(asset_dir, payload_ref)

    summary = authoring.asset_variants.get_variant_summary(asset_dir)
    existing = any(s.name == set_name for s in summary.variant_sets)
    if not existing and authoring.asset_folder.asset_has_root_payload(asset_dir):
        raise ValueError(
            f"{asset_dir.name} has a direct payload on its root prim, which "
            "blocks variant payload swapping per LIVRPS. Run "
            "setup_asset_geometry_variants first to restructure the asset into "
            "the Pixar-canonical pattern (no root payload, all payloads "
            "inside variants).",
        )

    existing_refs = authoring.asset_variants.get_variant_payload_refs(asset_dir, set_name)
    new_payload_ref = next(iter(payloads.values()))
    variants.geometry.validate_lod_namespace_stability(
        asset_dir, {**existing_refs, variant_name: new_payload_ref},
    )

    variants.asset.add(
        asset_dir, set_name, variant_name,
        lambda stage, _prim_path: variants.bodies.author_payloads(stage, payloads),
        set_as_default,
    )
    state.reload_stage()
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": schemas.VariantCategory.GEOMETRY.value,
        "default_selected": set_as_default,
        "payloads": payloads,
        "message": (
            f"Added geometry variant '{variant_name}' to '{set_name}' "
            f"in {asset_dir.name}"
        ),
    }


def setup_asset_geometry_variants(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Initial setup of an LOD variant set in Pixar's canonical pattern."""
    asset_dir, _ = authoring.placement.require_asset_context(state.stage, params["prim_path"])
    set_name = params["variant_set"]
    default_variant = params["default_variant"]
    payloads = usd.values.require_dict_param(
        params, "variants",
        "Each entry maps a variant name to its payload path "
        "(e.g. {'high': './geo.usda', 'low': './geo_low.usda'}).",
    )

    variants.geometry.setup(
        asset_dir, set_name, payloads, default_variant,
    )
    state.reload_stage()
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variants": payloads,
        "default_variant": default_variant,
        "message": (
            f"Set up '{set_name}' variant set in {asset_dir.name} with "
            f"{len(payloads)} variant(s); default '{default_variant}'. "
            f"Asset root payload was cleared (Pixar pattern)."
        ),
    }


def add_asset_attribute_variant(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author an attribute-override variant on the asset's root prim."""
    asset_dir, ref_prim_path = authoring.placement.require_asset_context(
        state.stage, params["prim_path"],
    )
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = usd.values.require_dict_param(
        params, "overrides",
        "Each entry maps a prim path to attribute_name -> value "
        "(e.g. {'lgt/Bulb': {'inputs:color': [0.2, 0.4, 1.0]}}).",
    )
    default_prim = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    overrides = {
        authoring.placement.normalize_asset_prim_path(k, ref_prim_path, default_prim): dict(v)
        for k, v in raw.items()
    }
    set_as_default = bool(params.get("set_as_default", False))
    confirm_masked = bool(params.get("confirm_masked", False))
    clear_masking = bool(params.get("clear_masking_overrides", False))
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)

    masking = authoring.opinions.find_variant_masking_opinions(
        state.stage, asset_dir, default_prim,
        {path: list(attrs) for path, attrs in overrides.items()}, "attribute",
    )
    if variants.masking.enforce(
        state.stage, masking, "attribute", "attribute",
        clear=clear_masking, confirm=confirm_masked,
    ):
        state.reload_stage()

    resolved_types = variants.asset.resolve_attribute_types_for_overrides(
        asset_dir, overrides,
    )
    variants.asset.refuse_unknown_attributes(asset_dir, resolved_types)
    overrides = authoring.textures.stage_asset_typed_overrides(
        overrides, resolved_types,
        state.project_dir,
        state.library_dir,
    )

    variants.asset.add(
        asset_dir, set_name, variant_name,
        lambda stage, _prim_path: variants.bodies.author_overrides(
            stage, overrides, resolved_types,
        ),
        set_as_default,
    )
    state.reload_stage()
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": schemas.VariantCategory.ATTRIBUTE.value,
        "default_selected": set_as_default,
        "overrides": overrides,
        "message": (
            f"Added attribute variant '{variant_name}' to '{set_name}' "
            f"in {asset_dir.name}"
        ),
    }


def add_asset_configuration_variant(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a configuration variant via prim activation toggles."""
    asset_dir, ref_prim_path = authoring.placement.require_asset_context(
        state.stage, params["prim_path"],
    )
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = usd.values.require_dict_param(
        params, "activations",
        "Each entry maps a prim path to a boolean active flag "
        "(e.g. {'/Geo/Door': false}).",
    )
    default_prim = authoring.asset_folder.resolve_default_prim_name(asset_dir)
    activations = {
        authoring.placement.normalize_asset_prim_path(k, ref_prim_path, default_prim): bool(v)
        for k, v in raw.items()
    }
    set_as_default = bool(params.get("set_as_default", False))
    confirm_masked = bool(params.get("confirm_masked", False))
    clear_masking = bool(params.get("clear_masking_overrides", False))
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)

    masking = authoring.opinions.find_variant_masking_opinions(
        state.stage, asset_dir, default_prim,
        {path: ["active"] for path in activations}, "active",
    )
    if variants.masking.enforce(
        state.stage, masking, "active", "configuration",
        clear=clear_masking, confirm=confirm_masked,
    ):
        state.reload_stage()

    variants.asset.add(
        asset_dir, set_name, variant_name,
        lambda stage, _prim_path: variants.bodies.author_activations(stage, activations),
        set_as_default,
    )
    state.reload_stage()
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": schemas.VariantCategory.CONFIGURATION.value,
        "default_selected": set_as_default,
        "activations": activations,
        "message": (
            f"Added configuration variant '{variant_name}' to '{set_name}' "
            f"in {asset_dir.name}"
        ),
    }


def add_scene_lighting_attribute_variant(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a scene-lighting attribute variant on UsdLux children of /Scene/Lighting."""
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = usd.values.require_dict_param(
        params, "overrides",
        "Each entry maps a UsdLux prim path under /Scene/Lighting to "
        "attribute_name -> value (e.g. {'/Scene/Lighting/Key_01': "
        "{'inputs:intensity': 1500, 'inputs:color': [1.0, 0.8, 0.6]}}).",
    )
    overrides = {k: dict(v) for k, v in raw.items()}
    set_as_default = bool(params.get("set_as_default", False))
    confirm_masked = bool(params.get("confirm_masked", False))
    clear_masking = bool(params.get("clear_masking_overrides", False))
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)

    carrier = variants.scene.require_lighting_carrier(state.stage)
    variants.scene.validate_lighting_targets(
        state.stage, carrier, overrides.keys(),
    )

    masking = authoring.opinions.find_masking_scene_opinions_direct(
        state.stage, {p: list(a) for p, a in overrides.items()}, "attribute",
    )
    if variants.masking.enforce(
        state.stage, masking, "attribute", "lighting attribute",
        clear=clear_masking, confirm=confirm_masked,
    ):
        state.reload_stage()

    resolved_types = usd.attributes.resolve_attribute_types(
        state.stage, overrides,
    )
    usd.attributes.refuse_unknown_attributes(state.stage, resolved_types)
    overrides = authoring.textures.stage_asset_typed_overrides(
        overrides, resolved_types,
        state.project_dir,
        state.library_dir,
    )

    variants.scene.add(
        state.stage, carrier, set_name, variant_name,
        lambda stage, _carrier: variants.bodies.author_overrides(
            stage, overrides, resolved_types,
        ),
        set_as_default,
    )
    state.reload_stage()
    return {
        "carrier_prim_path": carrier,
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": schemas.VariantCategory.LIGHTING.value,
        "default_selected": set_as_default,
        "overrides": overrides,
        "message": (
            f"Added scene lighting attribute variant '{variant_name}' "
            f"to '{set_name}' on {carrier}"
        ),
    }


def add_scene_lighting_selection_variant(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a scene-lighting variant: active toggles on UsdLux children of /Scene/Lighting."""
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = usd.values.require_dict_param(
        params, "activations",
        "Each entry maps a UsdLux prim path under /Scene/Lighting to a "
        "boolean active flag (e.g. {'/Scene/Lighting/Key_Disk': true, "
        "'/Scene/Lighting/Key_Rect': false}). Pre-place the alternative "
        "lights as siblings first.",
    )
    activations = {k: bool(v) for k, v in raw.items()}
    set_as_default = bool(params.get("set_as_default", False))
    confirm_masked = bool(params.get("confirm_masked", False))
    clear_masking = bool(params.get("clear_masking_overrides", False))
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)

    carrier = variants.scene.require_lighting_carrier(state.stage)
    variants.scene.validate_lighting_targets(
        state.stage, carrier, activations.keys(),
    )

    masking = authoring.opinions.find_masking_scene_opinions_direct(
        state.stage, {p: ["active"] for p in activations}, "active",
    )
    if variants.masking.enforce(
        state.stage, masking, "active", "lighting selection",
        clear=clear_masking, confirm=confirm_masked,
    ):
        state.reload_stage()

    variants.scene.add(
        state.stage, carrier, set_name, variant_name,
        lambda stage, _carrier: variants.bodies.author_activations(stage, activations),
        set_as_default,
    )
    state.reload_stage()
    return {
        "carrier_prim_path": carrier,
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": schemas.VariantCategory.LIGHTING.value,
        "default_selected": set_as_default,
        "activations": activations,
        "message": (
            f"Added scene lighting selection variant '{variant_name}' "
            f"to '{set_name}' on {carrier}"
        ),
    }


def add_scene_model_selection_variant(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a scene model-selection variant; first call auto-promotes existing direct ref."""
    prim_path = params["prim_path"]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    set_as_default = bool(params.get("set_as_default", False))
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)
    if state.stage is None:
        raise ValueError("No scene stage is open.")
    if state.project is None:
        raise ValueError("No project set; cannot stage assets for variant.")

    wrapper = state.stage.GetPrimAtPath(prim_path)
    if not wrapper or not wrapper.IsValid():
        raise ValueError(f"Scene placement not found: {prim_path}")
    asset_child = f"{prim_path}/asset"
    if not state.stage.GetPrimAtPath(asset_child).IsValid():
        raise ValueError(
            f"{prim_path} has no '/asset' child — not a valid placement wrapper.",
        )

    resolved_path = authoring.library.resolve_source_file(
        params["asset_file_path"],
        project_dir=state.project_dir,
        library_dir=state.library_dir,
    )
    report = authoring.intake.prepare_asset(
        resolved_path, state.resolve_assets_dir(),
        library_dir=state.library_dir,
        project_mpu=state.meters_per_unit,
        project_up_axis=state.up_axis.value,
        fix_root_prim=bool(params.get("fix_root_prim", False)),
        fix_root_transforms=bool(params.get("fix_root_transforms", False)),
    )
    new_ref = f"./{report.scene_ref_path}"

    promoted: str | None = None
    set_exists = set_name in wrapper.GetVariantSets().GetNames()
    if not set_exists and usd.references.has_direct_references(state.stage, asset_child):
        existing = usd.references.get_prim_ref_paths(state.stage.GetPrimAtPath(asset_child))
        if existing:
            raw = Path(existing[0]).parent.name or Path(existing[0]).stem
            if raw == "assets":
                raw = Path(existing[0]).stem
            promoted = usd.naming.safe_variant_name(raw) or "original"
            if promoted == variant_name:
                raise ValueError(
                    f"variant_name='{variant_name}' collides with auto-promoted "
                    f"name '{promoted}'. Pick a different variant_name.",
                )
            usd.naming.validate_variant_name(promoted)
            variants.scene.add(
                state.stage, prim_path, set_name, promoted,
                lambda stage, _carrier: variants.bodies.author_references(
                    stage, asset_child, list(existing),
                ),
                set_as_default=True,
            )
            usd.references.clear_direct_references(state.stage, asset_child)
            state.reload_stage()

    variants.scene.add(
        state.stage, prim_path, set_name, variant_name,
        lambda stage, _carrier: variants.bodies.author_references(stage, asset_child, [new_ref]),
        set_as_default,
    )
    state.reload_stage()
    suffix = f" (auto-promoted existing as '{promoted}')" if promoted else ""
    return {
        "carrier_prim_path": prim_path,
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": schemas.VariantCategory.MODEL_SELECTION.value,
        "default_selected": set_as_default,
        "asset_reference": new_ref,
        "asset_folder": report.asset_folder_name,
        "promoted_existing_variant": promoted,
        "message": (
            f"Added scene model-selection variant '{variant_name}' "
            f"to '{set_name}' on {prim_path}{suffix}"
        ),
    }


# ── Generic operations ──


def list_asset_geo_files(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """List alternate geometry files available for geometry variants."""
    asset_dir = authoring.placement.require_asset_context(state.stage, params["prim_path"])[0]
    files = authoring.asset_folder.list_alternate_geo_files(asset_dir)
    return {
        "asset_path": str(asset_dir),
        "geo_files": files,
        "message": (
            f"{len(files)} alternate geometry file(s) in {asset_dir.name}"
        ),
    }


def list_variants(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every variant carrier visible under a scene placement."""
    prim_path = params["prim_path"]
    if state.stage is None:
        raise ValueError("No scene stage is open.")
    summary = usd.variant_sets.get_scene_variants_summary(state.stage, prim_path)
    return {
        "prim_path": summary.prim_path,
        "carriers": [c.model_dump() for c in summary.carriers],
        "message": (
            f"{sum(len(c.variant_sets) for c in summary.carriers)} variant "
            f"set(s) across {len(summary.carriers)} carrier(s) under {prim_path}"
        ),
    }


def select_asset_variant(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Set the asset's ship default variant selection."""
    asset_dir = authoring.placement.require_asset_context(state.stage, params["prim_path"])[0]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)

    authoring.asset_variants.set_default_variant(asset_dir, set_name, variant_name)
    state.reload_stage()
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variant_name": variant_name,
        "message": (
            f"Selected '{variant_name}' for '{set_name}' in {asset_dir.name}"
        ),
    }


def select_asset_variant_for_instance(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Override variant selection on one scene placement (authoring-layer routing)."""
    prim_path = params["prim_path"]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)

    if state.stage is None:
        raise ValueError("No scene stage is open.")
    carriers = usd.variant_sets.find_variant_carriers(
        state.stage, prim_path, set_name,
    )
    if not carriers:
        raise ValueError(
            f"Variant set '{set_name}' is not visible under {prim_path}. "
            "Call list_variants to discover available variant sets.",
        )
    if len(carriers) > 1:
        paths = [c.prim_path for c in carriers]
        raise ValueError(
            f"Variant set '{set_name}' is visible on multiple prims under "
            f"{prim_path}: {paths}. Re-run with one of those exact prim "
            "paths to disambiguate.",
        )

    target_path = carriers[0].prim_path
    effective = usd.variant_sets.select_variant(
        state.stage, target_path, set_name, variant_name,
    )

    return {
        "prim_path": target_path,
        "requested_prim_path": prim_path,
        "variant_set": set_name,
        "variant_name": variant_name,
        "effective_selection": effective,
        "message": (
            f"Set {target_path} variant '{set_name}' to '{variant_name}'"
        ),
    }


def remove_asset_variant(state: scene_state.SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove a single variant from a variant set."""
    asset_dir = authoring.placement.require_asset_context(state.stage, params["prim_path"])[0]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)

    removed = authoring.asset_variants.remove_variant(asset_dir, set_name, variant_name)
    if removed:
        variants.asset.clean_after_removal(state.stage, asset_dir, set_name, variant_name)

    state.reload_stage()
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variant_name": variant_name,
        "removed": removed,
        "message": (
            f"Removed '{variant_name}' from '{set_name}' in {asset_dir.name}"
            if removed else
            f"Variant '{variant_name}' not found in '{set_name}'"
        ),
    }


def select_scene_variant(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a variant selection on a scene-level carrier prim in scene.usda."""
    prim_path = params["prim_path"]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)

    if state.stage is None:
        raise ValueError("No scene stage is open.")
    usd.variant_sets.select_variant(state.stage, prim_path, set_name, variant_name)
    state.reload_stage()
    return {
        "carrier_prim_path": prim_path,
        "variant_set": set_name,
        "variant_name": variant_name,
        "scope": "scene",
        "message": (
            f"Selected '{variant_name}' for '{set_name}' on {prim_path}"
        ),
    }


def remove_scene_variant(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Remove a single variant from a scene-level variant set on a carrier prim."""
    prim_path = params["prim_path"]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    usd.naming.validate_variant_set_name(set_name)
    usd.naming.validate_variant_name(variant_name)

    if state.stage is None:
        raise ValueError("No scene stage is open.")
    removed = usd.variant_sets.remove_scene_variant(
        state.stage, prim_path, set_name, variant_name,
    )
    suspects: list[dict] = []
    if removed:
        suspects = variants.suspect_sets.find_on_scene_carrier(
            state.stage, prim_path,
        )
    state.reload_stage()
    return {
        "carrier_prim_path": prim_path,
        "variant_set": set_name,
        "variant_name": variant_name,
        "removed": removed,
        "scope": "scene",
        "suspect_variant_sets": suspects,
        "message": (
            f"Removed '{variant_name}' from '{set_name}' on {prim_path}"
            if removed else
            f"Variant '{variant_name}' not found in '{set_name}' on {prim_path}"
        ),
    }


def remove_scene_variant_set(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Remove a scene variant set; demote model-selection active variant back to direct ref."""
    prim_path = params["prim_path"]
    set_name = params["variant_set"]
    usd.naming.validate_variant_set_name(set_name)

    if state.stage is None:
        raise ValueError("No scene stage is open.")
    demoted = variants.suspect_sets.restore_direct_reference(
        state.stage, prim_path, set_name,
    )
    removed = usd.variant_sets.remove_scene_variant_set(
        state.stage, prim_path, set_name,
    )
    state.reload_stage()
    suffix = f" (restored '{demoted}' as direct reference)" if demoted else ""
    return {
        "carrier_prim_path": prim_path,
        "variant_set": set_name,
        "removed": removed,
        "demoted_to_direct_ref": demoted,
        "scope": "scene",
        "message": (
            f"Removed variant set '{set_name}' from {prim_path}{suffix}"
            if removed else
            f"Variant set '{set_name}' not found on {prim_path}"
        ),
    }


def remove_asset_variant_set(
    state: scene_state.SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Remove an entire variant set from one asset."""
    asset_dir = authoring.placement.require_asset_context(state.stage, params["prim_path"])[0]
    set_name = params["variant_set"]
    usd.naming.validate_variant_set_name(set_name)

    removed = authoring.asset_variants.remove_variant_set(asset_dir, set_name)
    if removed:
        variants.asset.clean_after_removal(state.stage, asset_dir, set_name)

    state.reload_stage()
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "removed": removed,
        "message": (
            f"Removed variant set '{set_name}' from {asset_dir.name}"
            if removed else
            f"Variant set '{set_name}' not found in {asset_dir.name}"
        ),
    }
