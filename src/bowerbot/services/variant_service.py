# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant service — orchestrates variant set operations for the variant tools."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pxr import Sdf, Usd, UsdShade

from bowerbot.schemas import VariantCategory
from bowerbot.state import SceneState
from bowerbot.utils import asset_intake_utils, stage_utils, variant_utils
from bowerbot.utils.asset_folder_utils import (
    asset_has_root_payload,
    list_alternate_geo_files,
    normalize_asset_prim_path,
    require_asset_context,
    resolve_asset_file_path,
    resolve_default_prim_name,
)

logger = logging.getLogger(__name__)


# ── Category orchestrators ──


def add_asset_material_variant(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a material-binding variant on the asset's root prim."""
    asset_dir, ref_prim_path = require_asset_context(state.stage, params["prim_path"])
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = variant_utils.require_dict_param(
        params, "bindings",
        "Each entry maps a mesh prim path to a material prim path "
        "(e.g. {'/Geo/Top': '/Materials/wood'}).",
    )
    default_prim = resolve_default_prim_name(asset_dir)
    bindings = {
        normalize_asset_prim_path(k, ref_prim_path, default_prim):
            normalize_asset_prim_path(v, ref_prim_path, default_prim)
        for k, v in raw.items()
    }
    set_as_default = bool(params.get("set_as_default", False))
    confirm_masked = bool(params.get("confirm_masked", False))
    clear_masking = bool(params.get("clear_masking_overrides", False))
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)

    if variant_utils.enforce_no_masking_overrides(
        state.stage, asset_dir, default_prim,
        {path: ["material:binding"] for path in bindings},
        "relationship", "material",
        clear=clear_masking, confirm=confirm_masked,
    ):
        state.stage = stage_utils.open_stage(state.stage_path)

    def author_fn(stage, _prim_path: str) -> None:
        for mesh_path, material_path in bindings.items():
            mesh_over = stage.OverridePrim(mesh_path)
            binding_api = UsdShade.MaterialBindingAPI.Apply(mesh_over)
            binding_api.GetDirectBindingRel().SetTargets([Sdf.Path(material_path)])

    variant_utils.apply_variant(
        asset_dir, set_name, variant_name, author_fn, set_as_default,
    )
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": VariantCategory.MATERIAL.value,
        "default_selected": set_as_default,
        "bindings": bindings,
        "message": (
            f"Added material variant '{variant_name}' to '{set_name}' "
            f"in {asset_dir.name}"
        ),
    }


def add_asset_geometry_variant(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a geometry/LOD variant via payload arc overrides."""
    asset_dir, ref_prim_path = require_asset_context(state.stage, params["prim_path"])
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = variant_utils.require_dict_param(
        params, "payloads",
        "Each entry maps a prim path to a payload asset path "
        "(e.g. {'/Geo': './geo_low.usda'}).",
    )
    default_prim = resolve_default_prim_name(asset_dir)
    payloads = {
        normalize_asset_prim_path(k, ref_prim_path, default_prim): v
        for k, v in raw.items()
    }
    set_as_default = bool(params.get("set_as_default", False))
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)
    for payload_ref in payloads.values():
        variant_utils.validate_payload_path(asset_dir, payload_ref)

    summary = variant_utils.get_variant_summary(asset_dir)
    existing = any(s.name == set_name for s in summary.variant_sets)
    if not existing and asset_has_root_payload(asset_dir):
        raise ValueError(
            f"{asset_dir.name} has a direct payload on its root prim, which "
            "blocks variant payload swapping per LIVRPS. Run "
            "setup_asset_geometry_variants first to restructure the asset into "
            "the Pixar-canonical pattern (no root payload, all payloads "
            "inside variants).",
        )

    existing_refs = variant_utils.get_variant_payload_refs(asset_dir, set_name)
    new_payload_ref = next(iter(payloads.values()))
    variant_utils.validate_lod_namespace_stability(
        asset_dir, {**existing_refs, variant_name: new_payload_ref},
    )

    def author_fn(stage, _prim_path: str) -> None:
        for target_path, payload_asset in payloads.items():
            target = stage.OverridePrim(target_path)
            target.GetPayloads().ClearPayloads()
            target.GetPayloads().AddPayload(payload_asset)

    variant_utils.apply_variant(
        asset_dir, set_name, variant_name, author_fn, set_as_default,
    )
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": VariantCategory.GEOMETRY.value,
        "default_selected": set_as_default,
        "payloads": payloads,
        "message": (
            f"Added geometry variant '{variant_name}' to '{set_name}' "
            f"in {asset_dir.name}"
        ),
    }


def setup_asset_geometry_variants(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Initial setup of an LOD variant set in Pixar's canonical pattern."""
    asset_dir, _ = require_asset_context(state.stage, params["prim_path"])
    set_name = params["variant_set"]
    default_variant = params["default_variant"]
    variants = variant_utils.require_dict_param(
        params, "variants",
        "Each entry maps a variant name to its payload path "
        "(e.g. {'high': './geo.usda', 'low': './geo_low.usda'}).",
    )

    variant_utils.setup_geometry_variant_set(
        asset_dir, set_name, variants, default_variant,
    )
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variants": variants,
        "default_variant": default_variant,
        "message": (
            f"Set up '{set_name}' variant set in {asset_dir.name} with "
            f"{len(variants)} variant(s); default '{default_variant}'. "
            f"Asset root payload was cleared (Pixar pattern)."
        ),
    }


def add_asset_attribute_variant(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author an attribute-override variant on the asset's root prim."""
    asset_dir, ref_prim_path = require_asset_context(state.stage, params["prim_path"])
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = variant_utils.require_dict_param(
        params, "overrides",
        "Each entry maps a prim path to attribute_name -> value "
        "(e.g. {'lgt/Bulb': {'inputs:color': [0.2, 0.4, 1.0]}}).",
    )
    default_prim = resolve_default_prim_name(asset_dir)
    overrides = {
        normalize_asset_prim_path(k, ref_prim_path, default_prim): dict(v)
        for k, v in raw.items()
    }
    set_as_default = bool(params.get("set_as_default", False))
    confirm_masked = bool(params.get("confirm_masked", False))
    clear_masking = bool(params.get("clear_masking_overrides", False))
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)

    if variant_utils.enforce_no_masking_overrides(
        state.stage, asset_dir, default_prim,
        {path: list(attrs) for path, attrs in overrides.items()},
        "attribute", "attribute",
        clear=clear_masking, confirm=confirm_masked,
    ):
        state.stage = stage_utils.open_stage(state.stage_path)

    resolved_types = variant_utils.resolve_attribute_types_for_overrides(
        asset_dir, overrides,
    )
    variant_utils.refuse_unknown_asset_attributes(asset_dir, resolved_types)
    overrides = variant_utils.stage_asset_typed_overrides(
        overrides, resolved_types,
        state.project.path if state.project else None,
        state.library_dir,
    )

    def author_fn(stage, _prim_path: str) -> None:
        for path, attrs in overrides.items():
            stage.OverridePrim(path)
            types = resolved_types[path]
            for attr_name, value in attrs.items():
                stage_utils.set_prim_attribute(
                    stage, path, attr_name, value,
                    expected_type=types[attr_name],
                )

    variant_utils.apply_variant(
        asset_dir, set_name, variant_name, author_fn, set_as_default,
    )
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": VariantCategory.ATTRIBUTE.value,
        "default_selected": set_as_default,
        "overrides": overrides,
        "message": (
            f"Added attribute variant '{variant_name}' to '{set_name}' "
            f"in {asset_dir.name}"
        ),
    }


def add_asset_configuration_variant(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a configuration variant via prim activation toggles."""
    asset_dir, ref_prim_path = require_asset_context(state.stage, params["prim_path"])
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = variant_utils.require_dict_param(
        params, "activations",
        "Each entry maps a prim path to a boolean active flag "
        "(e.g. {'/Geo/Door': false}).",
    )
    default_prim = resolve_default_prim_name(asset_dir)
    activations = {
        normalize_asset_prim_path(k, ref_prim_path, default_prim): bool(v)
        for k, v in raw.items()
    }
    set_as_default = bool(params.get("set_as_default", False))
    confirm_masked = bool(params.get("confirm_masked", False))
    clear_masking = bool(params.get("clear_masking_overrides", False))
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)

    if variant_utils.enforce_no_masking_overrides(
        state.stage, asset_dir, default_prim,
        {path: ["active"] for path in activations},
        "active", "configuration",
        clear=clear_masking, confirm=confirm_masked,
    ):
        state.stage = stage_utils.open_stage(state.stage_path)

    def author_fn(stage, _prim_path: str) -> None:
        for prim_path, active in activations.items():
            target = stage.OverridePrim(prim_path)
            target.SetActive(active)

    variant_utils.apply_variant(
        asset_dir, set_name, variant_name, author_fn, set_as_default,
    )
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": VariantCategory.CONFIGURATION.value,
        "default_selected": set_as_default,
        "activations": activations,
        "message": (
            f"Added configuration variant '{variant_name}' to '{set_name}' "
            f"in {asset_dir.name}"
        ),
    }


def add_scene_lighting_attribute_variant(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a scene-lighting attribute variant on UsdLux children of /Scene/Lighting."""
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = variant_utils.require_dict_param(
        params, "overrides",
        "Each entry maps a UsdLux prim path under /Scene/Lighting to "
        "attribute_name -> value (e.g. {'/Scene/Lighting/Key_01': "
        "{'inputs:intensity': 1500, 'inputs:color': [1.0, 0.8, 0.6]}}).",
    )
    overrides = {k: dict(v) for k, v in raw.items()}
    set_as_default = bool(params.get("set_as_default", False))
    confirm_masked = bool(params.get("confirm_masked", False))
    clear_masking = bool(params.get("clear_masking_overrides", False))
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)

    carrier = variant_utils.require_scene_lighting_carrier(state.stage)
    variant_utils.validate_scene_lighting_targets(
        state.stage, carrier, overrides.keys(),
    )

    if variant_utils.enforce_no_scene_masking_overrides(
        state.stage,
        {p: list(a) for p, a in overrides.items()},
        "attribute", "lighting attribute",
        clear=clear_masking, confirm=confirm_masked,
    ):
        state.stage = stage_utils.open_stage(state.stage_path)

    resolved_types = variant_utils.resolve_scene_attribute_types(
        state.stage, overrides,
    )
    variant_utils.refuse_unknown_attributes(state.stage, resolved_types)
    overrides = variant_utils.stage_asset_typed_overrides(
        overrides, resolved_types,
        state.project.path if state.project else None,
        state.library_dir,
    )

    def author_fn(stage, _carrier: str) -> None:
        for path, attrs in overrides.items():
            stage.OverridePrim(path)
            types = resolved_types[path]
            for attr_name, value in attrs.items():
                stage_utils.set_prim_attribute(
                    stage, path, attr_name, value,
                    expected_type=types[attr_name],
                )

    variant_utils.apply_scene_variant(
        state.stage, carrier, set_name, variant_name,
        author_fn, set_as_default,
    )
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
    return {
        "carrier_prim_path": carrier,
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": VariantCategory.LIGHTING.value,
        "default_selected": set_as_default,
        "overrides": overrides,
        "message": (
            f"Added scene lighting attribute variant '{variant_name}' "
            f"to '{set_name}' on {carrier}"
        ),
    }


def add_scene_lighting_selection_variant(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a scene-lighting variant: active toggles on UsdLux children of /Scene/Lighting."""
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    raw = variant_utils.require_dict_param(
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
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)

    carrier = variant_utils.require_scene_lighting_carrier(state.stage)
    variant_utils.validate_scene_lighting_targets(
        state.stage, carrier, activations.keys(),
    )

    if variant_utils.enforce_no_scene_masking_overrides(
        state.stage,
        {p: ["active"] for p in activations},
        "active", "lighting selection",
        clear=clear_masking, confirm=confirm_masked,
    ):
        state.stage = stage_utils.open_stage(state.stage_path)

    def author_fn(stage, _carrier: str) -> None:
        for path, active in activations.items():
            stage.OverridePrim(path).SetActive(active)

    variant_utils.apply_scene_variant(
        state.stage, carrier, set_name, variant_name,
        author_fn, set_as_default,
    )
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
    return {
        "carrier_prim_path": carrier,
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": VariantCategory.LIGHTING.value,
        "default_selected": set_as_default,
        "activations": activations,
        "message": (
            f"Added scene lighting selection variant '{variant_name}' "
            f"to '{set_name}' on {carrier}"
        ),
    }


def add_scene_model_selection_variant(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a scene model-selection variant; first call auto-promotes existing direct ref."""
    prim_path = params["prim_path"]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    set_as_default = bool(params.get("set_as_default", False))
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)
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

    resolved_path = resolve_asset_file_path(
        params["asset_file_path"],
        state.project.path if state.project else None,
        state.library_dir,
    )
    report = asset_intake_utils.prepare_asset(
        resolved_path, state.resolve_assets_dir(),
        library_dir=state.library_dir,
        fix_root_prim=bool(params.get("fix_root_prim", False)),
        fix_root_transforms=bool(params.get("fix_root_transforms", False)),
    )
    new_ref = f"./{report.scene_ref_path}"

    def author_refs(refs: list[str]):
        def fn(stage: Usd.Stage, _carrier: str) -> None:
            ov = stage.OverridePrim(asset_child)
            ov.GetReferences().ClearReferences()
            for r in refs:
                ov.GetReferences().AddReference(r)
        return fn

    promoted: str | None = None
    set_exists = set_name in wrapper.GetVariantSets().GetNames()
    if not set_exists and variant_utils.has_direct_references(state.stage, asset_child):
        existing = stage_utils.get_prim_ref_paths(state.stage.GetPrimAtPath(asset_child))
        if existing:
            raw = Path(existing[0]).parent.name or Path(existing[0]).stem
            if raw == "assets":
                raw = Path(existing[0]).stem
            promoted = "".join(
                c if c not in " \t\n\r/\\" else "_" for c in raw
            ) or "original"
            if promoted == variant_name:
                raise ValueError(
                    f"variant_name='{variant_name}' collides with auto-promoted "
                    f"name '{promoted}'. Pick a different variant_name.",
                )
            variant_utils.validate_variant_name(promoted)
            variant_utils.apply_scene_variant(
                state.stage, prim_path, set_name, promoted,
                author_refs(list(existing)), set_as_default=True,
            )
            variant_utils.clear_direct_references(state.stage, asset_child)
            state.stage = stage_utils.open_stage(state.stage_path)

    variant_utils.apply_scene_variant(
        state.stage, prim_path, set_name, variant_name,
        author_refs([new_ref]), set_as_default,
    )
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
    suffix = f" (auto-promoted existing as '{promoted}')" if promoted else ""
    return {
        "carrier_prim_path": prim_path,
        "variant_set": set_name,
        "variant_name": variant_name,
        "category": VariantCategory.MODEL_SELECTION.value,
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
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """List alternate geometry files available for geometry variants."""
    asset_dir = require_asset_context(state.stage, params["prim_path"])[0]
    files = list_alternate_geo_files(asset_dir)
    return {
        "asset_path": str(asset_dir),
        "geo_files": files,
        "message": (
            f"{len(files)} alternate geometry file(s) in {asset_dir.name}"
        ),
    }


def list_variants(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """List every variant carrier visible under a scene placement."""
    prim_path = params["prim_path"]
    if state.stage is None:
        raise ValueError("No scene stage is open.")
    summary = variant_utils.get_scene_variants_summary(state.stage, prim_path)
    return {
        "prim_path": summary.prim_path,
        "carriers": [c.model_dump() for c in summary.carriers],
        "message": (
            f"{sum(len(c.variant_sets) for c in summary.carriers)} variant "
            f"set(s) across {len(summary.carriers)} carrier(s) under {prim_path}"
        ),
    }


def select_asset_variant(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Set the asset's ship default variant selection."""
    asset_dir = require_asset_context(state.stage, params["prim_path"])[0]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)

    variant_utils.set_default_variant(asset_dir, set_name, variant_name)
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
    return {
        "asset_path": str(asset_dir),
        "variant_set": set_name,
        "variant_name": variant_name,
        "message": (
            f"Selected '{variant_name}' for '{set_name}' in {asset_dir.name}"
        ),
    }


def select_asset_variant_for_instance(
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Override variant selection on one scene placement (authoring-layer routing)."""
    prim_path = params["prim_path"]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)

    if state.stage is None:
        raise ValueError("No scene stage is open.")
    carriers = variant_utils.find_variant_carriers(
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
    target = state.stage.GetPrimAtPath(target_path)
    vset = target.GetVariantSets().GetVariantSet(set_name)
    if variant_name not in vset.GetVariantNames():
        raise ValueError(
            f"Variant '{variant_name}' does not exist in set '{set_name}' "
            f"on {target_path}. Available: {list(vset.GetVariantNames())}",
        )

    vset.SetVariantSelection(variant_name)
    state.stage.Save()

    return {
        "prim_path": target_path,
        "requested_prim_path": prim_path,
        "variant_set": set_name,
        "variant_name": variant_name,
        "effective_selection": vset.GetVariantSelection(),
        "message": (
            f"Set {target_path} variant '{set_name}' to '{variant_name}'"
        ),
    }


def remove_asset_variant(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Remove a single variant from a variant set."""
    asset_dir = require_asset_context(state.stage, params["prim_path"])[0]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)

    removed = variant_utils.remove_variant(asset_dir, set_name, variant_name)
    if removed:
        summary = variant_utils.get_variant_summary(asset_dir)
        still_has_set = any(s.name == set_name for s in summary.variant_sets)
        scrub_target = None if not still_has_set else variant_name
        if not still_has_set:
            variant_utils.clear_default_variant(asset_dir, set_name)
        else:
            current = next(
                (s.selection for s in summary.variant_sets if s.name == set_name),
                None,
            )
            if current == variant_name:
                variant_utils.clear_default_variant(asset_dir, set_name)
        variant_utils.clear_scene_variant_selections(
            state.stage, asset_dir, set_name, scrub_target,
        )
        variant_utils.restore_canonical_geo_if_needed(asset_dir)
        variant_utils.cleanup_if_empty(asset_dir)

    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
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
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Author a variant selection on a scene-level carrier prim in scene.usda."""
    prim_path = params["prim_path"]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)

    if state.stage is None:
        raise ValueError("No scene stage is open.")
    prim = state.stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Carrier prim not found: {prim_path}")
    vset = prim.GetVariantSets().GetVariantSet(set_name)
    if not vset.IsValid():
        raise ValueError(
            f"Variant set '{set_name}' not found on {prim_path}",
        )
    if variant_name not in vset.GetVariantNames():
        raise ValueError(
            f"Variant '{variant_name}' not in '{set_name}' on {prim_path}. "
            f"Available: {list(vset.GetVariantNames())}",
        )

    variant_utils.set_scene_variant_default(
        state.stage, prim_path, set_name, variant_name,
    )
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
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
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Remove a single variant from a scene-level variant set on a carrier prim."""
    prim_path = params["prim_path"]
    set_name = params["variant_set"]
    variant_name = params["variant_name"]
    variant_utils.validate_variant_name(set_name, "variant set")
    variant_utils.validate_variant_name(variant_name)

    if state.stage is None:
        raise ValueError("No scene stage is open.")
    removed = variant_utils.remove_scene_variant(
        state.stage, prim_path, set_name, variant_name,
    )
    suspects: list[dict] = []
    if removed:
        suspects = variant_utils.suspect_variant_sets_on_scene_carrier(
            state.stage, prim_path,
        )
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
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
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Remove a scene variant set; demote model-selection active variant back to direct ref."""
    prim_path = params["prim_path"]
    set_name = params["variant_set"]
    variant_utils.validate_variant_name(set_name, "variant set")

    if state.stage is None:
        raise ValueError("No scene stage is open.")
    demoted = variant_utils.restore_active_scene_variant_references_to_direct_ref(
        state.stage, prim_path, set_name,
    )
    removed = variant_utils.remove_scene_variant_set(
        state.stage, prim_path, set_name,
    )
    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
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
    state: SceneState, params: dict[str, Any],
) -> dict[str, Any]:
    """Remove an entire variant set from one asset."""
    asset_dir = require_asset_context(state.stage, params["prim_path"])[0]
    set_name = params["variant_set"]
    variant_utils.validate_variant_name(set_name, "variant set")

    removed = variant_utils.remove_variant_set(asset_dir, set_name)
    if removed:
        variant_utils.clear_default_variant(asset_dir, set_name)
        variant_utils.clear_scene_variant_selections(
            state.stage, asset_dir, set_name,
        )
        variant_utils.restore_canonical_geo_if_needed(asset_dir)
        variant_utils.cleanup_if_empty(asset_dir)

    if state.stage_path is not None:
        state.stage = stage_utils.open_stage(state.stage_path)
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
