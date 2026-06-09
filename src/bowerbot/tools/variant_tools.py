# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant tools — author / select / list / remove variant sets and variants."""

from __future__ import annotations

from typing import Any

from bowerbot.services import variant_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState
from bowerbot.tools._helpers import require_stage


def add_asset_material_variant(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Author a material-binding variant on the asset's root prim."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.add_asset_material_variant(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def add_asset_geometry_variant(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Author a geometry/LOD variant via payload arc overrides."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.add_asset_geometry_variant(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def setup_asset_geometry_variants(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Initial setup of an LOD variant set in Pixar's canonical pattern."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.setup_asset_geometry_variants(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def add_asset_attribute_variant(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Author an attribute-override variant on the asset's root prim."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.add_asset_attribute_variant(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def add_asset_configuration_variant(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Author a configuration variant via prim activation toggles."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.add_asset_configuration_variant(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def add_scene_lighting_attribute_variant(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Author a scene-lighting attribute variant on /Scene/Lighting children."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.add_scene_lighting_attribute_variant(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def add_scene_lighting_selection_variant(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Author a scene-lighting selection variant via active toggles on /Scene/Lighting children."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.add_scene_lighting_selection_variant(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def add_scene_model_selection_variant(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Author a scene model-selection variant: swap which asset is referenced at a placement."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.add_scene_model_selection_variant(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def select_scene_variant(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Set the active variant on a scene-level carrier prim."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.select_scene_variant(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def remove_scene_variant(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Remove a single variant from a scene-level variant set on a carrier prim."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.remove_scene_variant(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def remove_scene_variant_set(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Remove an entire scene-level variant set from a carrier prim."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.remove_scene_variant_set(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def list_variants(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List variant sets, variants, and selections on an asset."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.list_variants(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def list_asset_geo_files(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """List alternate geometry files available for geometry variants."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.list_asset_geo_files(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def select_asset_variant(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Set the asset's ship default variant selection."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.select_asset_variant(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def select_asset_variant_for_instance(
    state: SceneState, params: dict[str, Any],
) -> ToolResult:
    """Override variant selection on one scene placement."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.select_asset_variant_for_instance(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def remove_asset_variant(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove a single variant from a variant set on one asset."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.remove_asset_variant(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


def remove_asset_variant_set(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Remove an entire variant set from one asset."""
    if (err := require_stage(state)):
        return err
    try:
        data = variant_service.remove_asset_variant_set(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    except KeyError as e:
        return ToolResult(success=False, error=f"Missing required parameter: {e.args[0]!r}")
    return ToolResult(success=True, data=data)


_PRIM_PATH = {
    "type": "string",
    "description": (
        "Scene prim path of any placement of the asset, e.g. "
        "'/Scene/Furniture/Table_01'. The asset folder is resolved "
        "from this. Use list_scene to find the path. When multiple "
        "assets could match, ASK the user which one before calling."
    ),
}

_SCENE_CARRIER_PRIM_PATH = {
    "type": "string",
    "description": (
        "Scene-level carrier prim path inside scene.usda (e.g. "
        "'/Scene/Lighting'). The variant set is authored DIRECTLY "
        "on this prim — no asset folder involved."
    ),
}

_VARIANT_SET = {
    "type": "string",
    "description": (
        "Variant set name (e.g. 'finish', 'lod', 'configuration'). "
        "No whitespace or path separators."
    ),
}

_VARIANT_NAME = {
    "type": "string",
    "description": "Variant name (e.g. 'wood', 'low', 'open').",
}

_SET_AS_DEFAULT = {
    "type": "boolean",
    "description": (
        "If true, set this variant as the asset's ship default. "
        "Every scene that references the asset sees this default "
        "until it overrides per-instance."
    ),
    "default": False,
}

_CLEAR_MASKING = {
    "type": "boolean",
    "description": (
        "If true, clear any per-instance scene opinions that would "
        "mask the variant before authoring. Use after the user "
        "confirms they want the variant to take over."
    ),
    "default": False,
}

_CONFIRM_MASKED = {
    "type": "boolean",
    "description": (
        "If true, author the variant even when scene opinions will "
        "mask it on some placements. Variant is visible only on "
        "placements without prior overrides. Use sparingly."
    ),
    "default": False,
}


TOOLS: list[Tool] = [
    Tool(
        name="add_asset_material_variant",
        description=(
            "Author a material-binding variant on an asset. Each entry in "
            "'bindings' maps a mesh prim path to the material prim path it "
            "should bind to when this variant is selected. Materials must "
            "already exist in the asset's mtl.usda; this tool only swaps "
            "bindings, it does not create materials. Mesh and material "
            "paths can be absolute under the asset (e.g. "
            "'/single_table/Geo/Top') or relative ('/Geo/Top'). "
            "REFUSES if any placement of the asset has an existing "
            "per-instance scene-level material:binding on a target mesh "
            "(those mask the variant). Pass clear_masking_overrides=true "
            "to clear them first, or confirm_masked=true to author anyway."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": _PRIM_PATH,
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
                "bindings": {
                    "type": "object",
                    "description": (
                        "Map of mesh prim path -> material prim path."
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "set_as_default": _SET_AS_DEFAULT,
                "clear_masking_overrides": _CLEAR_MASKING,
                "confirm_masked": _CONFIRM_MASKED,
            },
            "required": [
                "prim_path", "variant_set", "variant_name", "bindings",
            ],
        },
    ),
    Tool(
        name="setup_asset_geometry_variants",
        description=(
            "Initial setup of an LOD/geometry-swap variant set on an asset. "
            "Authors the variant set in Pixar's canonical pattern: clears "
            "the asset's direct root payload and moves all payloads INSIDE "
            "variant bodies. This is required because LIVRPS makes a root "
            "local payload stronger than any variant body payload; without "
            "this restructure, switching variants does not actually swap "
            "geometry. Call this ONCE per asset to bootstrap the variant "
            "set; use add_asset_geometry_variant afterwards to extend it. "
            "Provide every variant in one call, including a 'default'-like "
            "variant (commonly 'high' or 'hero') that captures the asset's "
            "current geometry payload. REFUSES if any payload file is "
            "missing or resolves outside the asset folder (ASWF assets must "
            "be self-contained), and REFUSES if the LOD payloads have "
            "divergent geometry prim hierarchies (production LODs must share "
            "prim names so bindings, light-linking, and overrides compose); "
            "the error names the missing/extra prims."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": _PRIM_PATH,
                "variant_set": {
                    "type": "string",
                    "description": (
                        "Variant set name. Common: 'lod', 'geo_vis', "
                        "'model'."
                    ),
                },
                "variants": {
                    "type": "object",
                    "description": (
                        "Map of variant name -> payload asset path "
                        "(relative to the asset folder). One entry per "
                        "LOD level. Common names: 'high', 'hero', 'mid', "
                        "'low', 'proxy'."
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "default_variant": {
                    "type": "string",
                    "description": (
                        "Name of the variant that should be the asset's "
                        "ship default (must be one of the keys in "
                        "'variants'). Typically the original/full geometry."
                    ),
                },
            },
            "required": [
                "prim_path", "variant_set", "variants", "default_variant",
            ],
        },
    ),
    Tool(
        name="add_asset_geometry_variant",
        description=(
            "Author a geometry/LOD variant by overriding payload arcs. Each "
            "entry in 'payloads' maps a prim path to a payload asset path "
            "to load when this variant is selected. Use for LODs, geometry "
            "swaps, or alternative meshes. Use ONLY to EXTEND an existing "
            "geometry variant set: if the set is new and the asset still has "
            "a direct root payload, this REFUSES and tells you to run "
            "setup_asset_geometry_variants first. Also REFUSES if a payload "
            "file is missing or resolves outside the asset folder, or if the "
            "new LOD's geometry prim hierarchy diverges from the existing "
            "LODs in the set."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": _PRIM_PATH,
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
                "payloads": {
                    "type": "object",
                    "description": (
                        "Map of prim path -> payload asset path. The "
                        "payload asset path is relative to variants.usda."
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "set_as_default": _SET_AS_DEFAULT,
            },
            "required": [
                "prim_path", "variant_set", "variant_name", "payloads",
            ],
        },
    ),
    Tool(
        name="add_asset_configuration_variant",
        description=(
            "Author a configuration variant by toggling prim activation. "
            "Use for open/closed states, optional parts, or visibility "
            "configurations. Each entry in 'activations' maps a prim path "
            "to a boolean (true = active, false = deactivated). "
            "REFUSES if any placement of the asset has an existing "
            "per-instance scene-level 'active' opinion on a target prim "
            "(those mask the variant). Pass clear_masking_overrides=true "
            "to clear them first, or confirm_masked=true to author anyway."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": _PRIM_PATH,
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
                "activations": {
                    "type": "object",
                    "description": (
                        "Map of prim path -> active flag. false "
                        "deactivates the prim and its descendants."
                    ),
                    "additionalProperties": {"type": "boolean"},
                },
                "set_as_default": _SET_AS_DEFAULT,
                "clear_masking_overrides": _CLEAR_MASKING,
                "confirm_masked": _CONFIRM_MASKED,
            },
            "required": [
                "prim_path", "variant_set", "variant_name", "activations",
            ],
        },
    ),
    Tool(
        name="add_asset_attribute_variant",
        description=(
            "Author an attribute-override variant on an asset. Use for "
            "swapping ARBITRARY attribute values per variant: light color "
            "or intensity, material sheen or roughness, anything not "
            "covered by material-binding (add_asset_material_variant), payload "
            "swap (add_asset_geometry_variant), or activation toggle "
            "(add_asset_configuration_variant). Each entry in 'overrides' maps "
            "a prim path (under the asset, e.g. 'lgt/Bulb' or "
            "'mtl/walnut/standard_surface') to a dict of attribute_name "
            "-> value. When the variant is selected, those attribute "
            "opinions compose on top of the asset's published baseline. "
            "REFUSES if any placement of the asset has existing "
            "per-instance scene overrides on the variant's attributes "
            "(those would silently mask the variant). Pass "
            "clear_masking_overrides=true to clear them first, or "
            "confirm_masked=true to author anyway."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": _PRIM_PATH,
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
                "overrides": {
                    "type": "object",
                    "description": (
                        "Map of prim path -> { attribute_name: value }. "
                        "Values match the attribute's USD type (float for "
                        "Float, list of 3 for Color3f, etc.). "
                        "Example: {'lgt/Bulb': {'inputs:color': "
                        "[0.2, 0.4, 1.0], 'inputs:intensity': 1500}}."
                    ),
                    "additionalProperties": {"type": "object"},
                },
                "set_as_default": _SET_AS_DEFAULT,
                "clear_masking_overrides": _CLEAR_MASKING,
                "confirm_masked": _CONFIRM_MASKED,
            },
            "required": [
                "prim_path", "variant_set", "variant_name", "overrides",
            ],
        },
    ),
    Tool(
        name="add_scene_lighting_attribute_variant",
        description=(
            "Author a SCENE-LEVEL lighting attribute variant on "
            "'/Scene/Lighting'. The variant set lives INSIDE scene.usda, "
            "not in any asset folder. Use for whole-scene lighting moods "
            "where the same lights take different attribute values per "
            "variant (warm/cool color, intensity profiles, exposure swaps). "
            "Each entry in 'overrides' maps a UsdLux prim path under "
            "/Scene/Lighting to attribute_name -> value. Targets must be "
            "UsdLux lights under /Scene/Lighting (non-light or out-of-carrier "
            "prims are REFUSED), and each attribute must already exist on the "
            "target light (unknown attributes are REFUSED with an "
            "available-inputs / did-you-mean hint). "
            "REFUSES if scene.usda already has direct authored opinions on "
            "those attributes (LIVRPS: local opinion masks same-layer "
            "variant body). Pass clear_masking_overrides=true to remove "
            "them, or confirm_masked=true to author anyway. "
            "For light-type swap (DiskLight vs RectLight) use "
            "add_scene_lighting_selection_variant instead."
        ),
        parameters={
            "type": "object",
            "properties": {
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
                "overrides": {
                    "type": "object",
                    "description": (
                        "Map of UsdLux prim path under /Scene/Lighting "
                        "-> { attribute_name: value }. Example: "
                        "{'/Scene/Lighting/Key_01': "
                        "{'inputs:intensity': 1500, "
                        "'inputs:color': [1.0, 0.8, 0.6]}}."
                    ),
                    "additionalProperties": {"type": "object"},
                },
                "set_as_default": _SET_AS_DEFAULT,
                "clear_masking_overrides": _CLEAR_MASKING,
                "confirm_masked": _CONFIRM_MASKED,
            },
            "required": ["variant_set", "variant_name", "overrides"],
        },
    ),
    Tool(
        name="add_scene_lighting_selection_variant",
        description=(
            "Author a SCENE-LEVEL lighting selection variant on "
            "'/Scene/Lighting' by toggling which lights are active. The "
            "variant set lives INSIDE scene.usda. Use this for "
            "light-TYPE swaps (DiskLight vs RectLight vs TubeLight) by "
            "pre-placing the alternative lights as siblings under "
            "/Scene/Lighting first, then having each variant flip the "
            "'active' flag so only one is on at a time. NEVER author "
            "different typeName per variant body (collides with USD "
            "composition); always toggle activation of pre-placed "
            "alternatives. REFUSES if scene.usda already has a direct "
            "'active' opinion on a target light. "
            "Pass clear_masking_overrides=true / confirm_masked=true to bypass."
        ),
        parameters={
            "type": "object",
            "properties": {
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
                "activations": {
                    "type": "object",
                    "description": (
                        "Map of UsdLux prim path under /Scene/Lighting -> "
                        "boolean active flag. Example: "
                        "{'/Scene/Lighting/Key_Disk': true, "
                        "'/Scene/Lighting/Key_Rect': false}."
                    ),
                    "additionalProperties": {"type": "boolean"},
                },
                "set_as_default": _SET_AS_DEFAULT,
                "clear_masking_overrides": _CLEAR_MASKING,
                "confirm_masked": _CONFIRM_MASKED,
            },
            "required": ["variant_set", "variant_name", "activations"],
        },
    ),
    Tool(
        name="add_scene_model_selection_variant",
        description=(
            "Author a SCENE-LEVEL model-selection variant on a scene "
            "placement wrapper (e.g. '/Scene/Furniture/Table_01'). Each "
            "variant body authors a different USD reference on the "
            "placement's '/asset' child, swapping which asset loads at "
            "that slot. Common use: 'this slot can be a chair, a stool, "
            "or a bench'. The variant set lives INSIDE scene.usda. "
            "BowerBot stages the asset into the project's assets/ folder "
            "automatically (same intake as place_asset). On the FIRST "
            "call, the placement's existing direct reference is "
            "AUTO-PROMOTED into a variant body (named after the source "
            "asset folder) so the user's original choice is preserved as "
            "the default — the set starts with TWO variants minimum. "
            "Refuses with a clear message if your variant_name collides "
            "with the auto-promoted name. Returns asset_reference (the "
            "staged './assets/<folder>/<file>' reference authored in the new "
            "variant body), asset_folder (the staged folder name), and "
            "promoted_existing_variant (the auto-promoted prior reference's "
            "variant name on the first call, else null)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Scene placement wrapper, e.g. "
                        "'/Scene/Furniture/Table_01'. Must have an "
                        "'/asset' child (created by place_asset)."
                    ),
                },
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
                "asset_file_path": {
                    "type": "string",
                    "description": (
                        "Absolute path or library-relative path to the "
                        "asset file (.usda / .usdz / loose geometry). "
                        "Will be staged into <project>/assets/ via the "
                        "same intake path as place_asset."
                    ),
                },
                "set_as_default": _SET_AS_DEFAULT,
                "fix_root_prim": {
                    "type": "boolean",
                    "description": (
                        "If true, auto-fix the asset's root prim during "
                        "intake (renames a single root to match the file)."
                    ),
                    "default": False,
                },
                "fix_root_transforms": {
                    "type": "boolean",
                    "description": (
                        "If true, bake non-identity root-prim transforms "
                        "into descendants during intake."
                    ),
                    "default": False,
                },
            },
            "required": [
                "prim_path", "variant_set", "variant_name", "asset_file_path",
            ],
        },
    ),
    Tool(
        name="select_scene_variant",
        description=(
            "Set the active variant on a scene-level carrier prim "
            "(e.g. '/Scene/Lighting'). Writes the variantSelections "
            "directly on the carrier in scene.usda. Pair with "
            "add_scene_lighting_* tools."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": _SCENE_CARRIER_PRIM_PATH,
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
            },
            "required": ["prim_path", "variant_set", "variant_name"],
        },
    ),
    Tool(
        name="remove_scene_variant",
        description=(
            "Remove a single variant from a scene-level variant set on "
            "a carrier prim (e.g. '/Scene/Lighting'). Idempotent. If "
            "this leaves the variant set empty, the variant set is "
            "auto-removed from the carrier. Operates on scene.usda only "
            "— asset-level variants are untouched."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": _SCENE_CARRIER_PRIM_PATH,
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
            },
            "required": ["prim_path", "variant_set", "variant_name"],
        },
    ),
    Tool(
        name="remove_scene_variant_set",
        description=(
            "Remove an entire scene-level variant set (all variants) "
            "from a scene carrier prim (e.g. '/Scene/Lighting'). "
            "Idempotent. Operates on scene.usda only. For model-selection "
            "sets this AUTO-DEMOTES: the currently-selected variant's "
            "reference is restored as a direct reference on the child prim "
            "before the set is dropped, and that variant name is returned "
            "as demoted_to_direct_ref (None otherwise) so you can confirm "
            "which asset survived. Also returns removed (bool) and scope "
            "('scene')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": _SCENE_CARRIER_PRIM_PATH,
                "variant_set": _VARIANT_SET,
            },
            "required": ["prim_path", "variant_set"],
        },
    ),
    Tool(
        name="list_asset_geo_files",
        description=(
            "List alternate geometry files (LODs, swap geometry, "
            "alt states) inside an asset folder. Canonical layers "
            "(geo.usda, mtl.usda, lgt.usda, phy.usda, contents.usda, "
            "variants.usda, and the root file) are excluded. Call "
            "this before add_asset_geometry_variant so you know which "
            "payload files exist; pick from the returned list."
        ),
        parameters={
            "type": "object",
            "properties": {"prim_path": _PRIM_PATH},
            "required": ["prim_path"],
        },
    ),
    Tool(
        name="list_variants",
        description=(
            "List all variant sets, their variants, and the current "
            "composed (effective) variant selection at each carrier under "
            "the placement, which reflects any per-instance scene override, "
            "not just the asset's ship default. Call this before authoring "
            "or removing variants to see what already exists."
        ),
        parameters={
            "type": "object",
            "properties": {"prim_path": _PRIM_PATH},
            "required": ["prim_path"],
        },
    ),
    Tool(
        name="select_asset_variant",
        description=(
            "Set the asset's SHIP DEFAULT variant selection (in <asset>.usda). "
            "Every consumer of the asset sees this default until they "
            "override it. Use this when the user wants 'change the default' "
            "for the asset itself. For per-scene-instance overrides "
            "('make Table_01 wood but leave Table_02 alone') use "
            "select_asset_variant_for_instance."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": _PRIM_PATH,
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
            },
            "required": ["prim_path", "variant_set", "variant_name"],
        },
    ),
    Tool(
        name="select_asset_variant_for_instance",
        description=(
            "Override the variant selection on ONE scene placement. The "
            "selection is authored inline next to the placement in "
            "scene.usda. The asset's ship default is untouched, so other "
            "scene instances of the same asset are unaffected. Use for "
            "'make THIS one different' requests. Returns prim_path (the "
            "resolved carrier the override was written to, which can differ "
            "from your input when you pass a wrapper), requested_prim_path "
            "(the path you passed), and effective_selection (the composed "
            "selection read back)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": {
                    "type": "string",
                    "description": (
                        "Absolute scene prim path of the specific "
                        "placement to override, e.g. "
                        "'/Scene/Furniture/Table_01'."
                    ),
                },
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
            },
            "required": ["prim_path", "variant_set", "variant_name"],
        },
    ),
    Tool(
        name="remove_asset_variant",
        description=(
            "Remove a single variant from a variant set on one asset. "
            "Idempotent: returns cleanly if the target is not present. "
            "If this leaves the variant set empty, the variant set is "
            "auto-removed; if this leaves no variant sets at all, "
            "variants.usda is auto-deleted and the reference scrubbed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": _PRIM_PATH,
                "variant_set": _VARIANT_SET,
                "variant_name": _VARIANT_NAME,
            },
            "required": ["prim_path", "variant_set", "variant_name"],
        },
    ),
    Tool(
        name="remove_asset_variant_set",
        description=(
            "Remove an entire variant set (all its variants) from one "
            "asset. Idempotent. Operates on this asset only; variants "
            "composed from referenced assets remain. When multiple assets "
            "are in scope, ASK the user which asset before calling."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_path": _PRIM_PATH,
                "variant_set": _VARIANT_SET,
            },
            "required": ["prim_path", "variant_set"],
        },
    ),
]


HANDLERS = {
    "add_asset_material_variant": add_asset_material_variant,
    "setup_asset_geometry_variants": setup_asset_geometry_variants,
    "add_asset_geometry_variant": add_asset_geometry_variant,
    "add_asset_configuration_variant": add_asset_configuration_variant,
    "add_asset_attribute_variant": add_asset_attribute_variant,
    "add_scene_lighting_attribute_variant": add_scene_lighting_attribute_variant,
    "add_scene_lighting_selection_variant": add_scene_lighting_selection_variant,
    "add_scene_model_selection_variant": add_scene_model_selection_variant,
    "list_asset_geo_files": list_asset_geo_files,
    "list_variants": list_variants,
    "select_asset_variant": select_asset_variant,
    "select_asset_variant_for_instance": select_asset_variant_for_instance,
    "select_scene_variant": select_scene_variant,
    "remove_asset_variant": remove_asset_variant,
    "remove_asset_variant_set": remove_asset_variant_set,
    "remove_scene_variant": remove_scene_variant,
    "remove_scene_variant_set": remove_scene_variant_set,
}
