# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter tools — surface scatter, path scatter, and drop-to-surface."""

from __future__ import annotations

from typing import Any

from bowerbot.schemas import (
    ScatterAlign,
    ScatterArrangement,
    ScatterAssetOrder,
    ScatterDropAlign,
    ScatterNamespace,
    ScatterOutput,
    ScatterPathFacing,
    ScatterPathSide,
    ScatterRegionFalloff,
    ScatterRules,
)
from bowerbot.services import scatter_service
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.state import SceneState


def scatter_on_surface(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Distribute assets over surfaces, each resting on the surface it lands on."""
    try:
        data = scatter_service.scatter_on_surface(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def scatter_along_path(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Place assets along a path, circle or curve, resting on the surface below."""
    try:
        data = scatter_service.scatter_along_path(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


def drop_to_surface(state: SceneState, params: dict[str, Any]) -> ToolResult:
    """Drop existing placements onto the surface beneath them."""
    try:
        data = scatter_service.drop_to_surface(state, params)
    except (ValueError, RuntimeError) as e:
        return ToolResult(success=False, error=str(e))
    return ToolResult(success=True, data=data)


_VEC3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}

_ASSETS = {
    "type": "array",
    "minItems": 1,
    "description": (
        "The asset mix. Each item: { asset: root FILE path in the asset library "
        "(absolute, project- or library-relative, e.g. 'pebble/pebble.usda'; "
        "files outside the library are refused), weight?: relative "
        "share (default 1), fix_root_prim?, fix_root_transforms? (intake "
        "fixes; only with user confirmation) }."
    ),
    "items": {
        "type": "object",
        "properties": {
            "asset": {"type": "string", "minLength": 1},
            "weight": {"type": "number", "exclusiveMinimum": 0},
            "fix_root_prim": {"type": "boolean"},
            "fix_root_transforms": {"type": "boolean"},
        },
        "required": ["asset"],
        "additionalProperties": False,
    },
}

_COMMON = {
    "name": {
        "type": "string", "minLength": 1,
        "description": "Scatter name, e.g. 'Pebbles'. Becomes /Scene/<group>/<name>.",
    },
    "group": {
        "type": "string", "minLength": 1,
        "description": (
            "Scene group, e.g. 'Nature' or 'Street/Props' "
            f"(default '{ScatterNamespace.DEFAULT_GROUP}')."
        ),
    },
    "assets": _ASSETS,
    "scale_range": {
        "type": "array", "items": {"type": "number", "exclusiveMinimum": 0},
        "minItems": 2, "maxItems": 2,
        "description": "[min, max] uniform random scale per instance (default [1, 1]).",
    },
    "embed": {
        "type": "number", "minimum": 0, "maximum": 1,
        "description": (
            "Fraction (0-1) of each piece's height sunk into the surface, e.g. "
            "0.3 for half-buried stones (default 0)."
        ),
    },
    "seed": {
        "type": "integer", "minimum": 0,
        "description": (
            "Random seed. Same inputs + same seed = identical result. Omit for "
            "a stable seed derived from the scatter path."
        ),
    },
    "replace": {
        "type": "boolean",
        "description": (
            "Regenerate an existing scatter with the same name in place. It is "
            "rebuilt from scratch: prototypes are named after the assets again "
            "and edits on them (renames, variant sets) are lost. To fix sunken "
            "or floating pieces instead, use drop_to_surface."
        ),
    },
    "validate_only": {
        "type": "boolean",
        "description": "Check the request and estimate the instance count; write nothing.",
    },
}

TOOLS: list[Tool] = [
    Tool(
        name="scatter_on_surface",
        description=(
            "Distribute many copies of one or more assets over surface prims "
            "(ground, floors, terrain, rocks, hulls, shelves), from a handful to "
            f"a million (max {ScatterRules.MAX_INSTANCES:,}). Every piece rests on the "
            "actual triangles it lands on, however uneven, sloped or curved, "
            "conformed to the scene's up-axis and units. Arrangements: 'random' "
            "(count or density; optional min_spacing, patchy 'variation', "
            "region with falloff), 'rows' (crop/vine rows draped over terrain), "
            "'pile' (a heap settling at an angle of repose). 'avoid' keeps pieces "
            "off anything under the plan-view footprint of the listed prims (a "
            "path, shelving, another scatter). Assets are staged and referenced exactly like "
            "place_asset. Default output is one PointInstancer at "
            "/Scene/<group>/<name> whose prototypes reference the assets (light "
            "for large counts; the scatter moves or is removed as one prim); "
            f"output='placements' writes up to {ScatterRules.MAX_PLACEMENTS:,} "
            "individually editable placements, like place_layout. Lengths are "
            "scene units; density is instances per square meter. Use "
            "validate_only first for large densities."
        ),
        parameters={
            "type": "object",
            "properties": {
                **_COMMON,
                "surfaces": {
                    "type": "array", "items": {"type": "string"}, "minItems": 1,
                    "description": (
                        "Prim paths whose Mesh/Cube/Sphere/Plane geometry is "
                        "scattered over (placements, groups, or mesh parts)."
                    ),
                },
                "arrangement": {
                    "type": "string", "enum": [a.value for a in ScatterArrangement],
                    "description": "random (default), rows, or pile.",
                },
                "count": {
                    "type": "integer", "minimum": 1,
                    "description": "Exact number of instances.",
                },
                "density": {
                    "type": "number", "exclusiveMinimum": 0,
                    "description": "Instances per square meter (random arrangement).",
                },
                "min_spacing": {
                    "type": "number", "exclusiveMinimum": 0,
                    "description": "Minimum distance between instances (random only).",
                },
                "variation": {
                    "type": "number", "minimum": 0, "maximum": 1,
                    "description": (
                        "0-1 patchiness: 0 even, 1 dense clumps and bare patches."
                    ),
                },
                "variation_scale": {
                    "type": "number", "exclusiveMinimum": 0,
                    "description": "Size of the patches in scene units (default auto).",
                },
                "region": {
                    "type": "object",
                    "description": (
                        "Limit to a plan-view area: a circle { center: [x,y,z] or "
                        "center_prim, radius, falloff?: none|linear|smooth } or "
                        "{ polygon: [[x,y,z], ...] }. Required for 'pile'."
                    ),
                    "additionalProperties": False,
                    "properties": {
                        "center": _VEC3,
                        "center_prim": {"type": "string"},
                        "radius": {"type": "number", "exclusiveMinimum": 0},
                        "falloff": {
                            "type": "string", "enum": [f.value for f in ScatterRegionFalloff],
                        },
                        "polygon": {"type": "array", "items": _VEC3, "minItems": 3},
                    },
                },
                "avoid": {
                    "type": "array", "items": {"type": "string"},
                    "description": (
                        "Prims whose plan-view footprint stays clear. A scatter "
                        "clears each of its instances' footprints."
                    ),
                },
                "avoid_margin": {
                    "type": "number", "minimum": 0,
                    "description": "Extra clearance around avoided footprints.",
                },
                "max_slope_degrees": {
                    "type": "number", "minimum": 0, "maximum": 180,
                    "description": (
                        "Skip faces steeper than this from up (default 60). Use "
                        "180 to cover every face of a rock or hull."
                    ),
                },
                "align": {
                    "type": "string", "enum": [a.value for a in ScatterAlign],
                    "description": (
                        "'surface' (default) tilts pieces to the surface normal "
                        "(stones, debris, moss); 'up' keeps them upright (trees, "
                        "grass, crops, posts)."
                    ),
                },
                "random_yaw": {
                    "type": "boolean",
                    "description": "Random spin about the up axis (default true).",
                },
                "tilt_jitter_degrees": {
                    "type": "number", "minimum": 0, "maximum": 90,
                    "description": "Random extra tilt up to this angle (default 0).",
                },
                "spacing": {
                    "type": "number", "exclusiveMinimum": 0,
                    "description": "rows: distance along a row.",
                },
                "row_spacing": {
                    "type": "number", "exclusiveMinimum": 0,
                    "description": "rows: distance between rows.",
                },
                "row_direction_degrees": {
                    "type": "number",
                    "description": (
                        "rows: plan-view row heading (0 = +X; 90 = +Z in Y-up, "
                        "+Y in Z-up)."
                    ),
                },
                "jitter": {
                    "type": "number", "minimum": 0,
                    "description": "rows: random position offset per plant.",
                },
                "repose_degrees": {
                    "type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 90,
                    "description": "pile: steepest slope the heap holds (default 35).",
                },
                "output": {
                    "type": "string", "enum": [o.value for o in ScatterOutput],
                    "description": "instancer (default) or placements.",
                },
            },
            "required": ["name", "assets", "surfaces"],
        },
    ),
    Tool(
        name="scatter_along_path",
        description=(
            "Place assets along a path: a polyline ('points'), a circle around a "
            "point or prim ('circle'), or a BasisCurves prim ('curve_prim'). "
            "For streetlights or fence posts along a road, fence sections "
            "following a boundary, products along a shelf, chairs round a "
            "table. Spacing comes from 'count', 'spacing', or (neither) the "
            "asset's own length plus 'gap', so sections butt end to end. Each "
            "piece is snapped straight down onto the nearest surface (all scene "
            "geometry unless 'surfaces' is given) and rests on it. 'facing' "
            "turns each piece's front (+Z in Y-up scenes, -Y in Z-up) toward "
            "the path direction, the path line, the centre, outward, a fixed "
            "direction, or random; correct odd assets with yaw_offset_degrees. "
            "Default output is individually editable placements."
        ),
        parameters={
            "type": "object",
            "properties": {
                **_COMMON,
                "points": {
                    "type": "array", "items": _VEC3, "minItems": 2,
                    "description": "Polyline points in scene units (at least 2).",
                },
                "closed": {
                    "type": "boolean", "description": "Treat 'points' as a loop.",
                },
                "circle": {
                    "type": "object",
                    "description": (
                        "{ center: [x,y,z] or center_prim, radius, "
                        "start_angle_degrees? }."
                    ),
                    "additionalProperties": False,
                    "properties": {
                        "center": _VEC3,
                        "center_prim": {"type": "string"},
                        "radius": {"type": "number", "exclusiveMinimum": 0},
                        "start_angle_degrees": {"type": "number"},
                    },
                    "required": ["radius"],
                },
                "curve_prim": {
                    "type": "string", "description": "A BasisCurves prim to follow.",
                },
                "count": {
                    "type": "integer", "minimum": 1, "description": "Number of stations.",
                },
                "spacing": {
                    "type": "number", "exclusiveMinimum": 0,
                    "description": "Distance between stations.",
                },
                "gap": {
                    "type": "number", "minimum": 0,
                    "description": "Extra gap added to automatic (asset-length) spacing.",
                },
                "start_offset": {
                    "type": "number", "minimum": 0,
                    "description": "Distance along the path before the first station.",
                },
                "sides": {
                    "type": "string", "enum": [s.value for s in ScatterPathSide],
                    "description": "On the line (center, default), left, right, or both.",
                },
                "offset": {
                    "type": "number", "minimum": 0,
                    "description": "Sideways distance from the line for left/right/both.",
                },
                "facing": {
                    "type": "string", "enum": [f.value for f in ScatterPathFacing],
                    "description": (
                        "tangent (default; long axis follows the path), path "
                        "(face the line), center, outward, fixed, random."
                    ),
                },
                "direction_degrees": {
                    "type": "number",
                    "description": "facing 'fixed': plan heading of the front (0 = +X).",
                },
                "yaw_offset_degrees": {
                    "type": "number",
                    "description": "Extra spin for assets whose front is not the convention.",
                },
                "align": {
                    "type": "string", "enum": [a.value for a in ScatterAlign],
                    "description": "'up' (default) keeps pieces upright; 'surface' tilts.",
                },
                "follow_slope": {
                    "type": "boolean",
                    "description": "Pitch pieces along the slope of the path (fence sections).",
                },
                "surfaces": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Surfaces to snap onto (default: all scene geometry).",
                },
                "snap": {
                    "type": "boolean",
                    "description": (
                        "Snap onto the surface (default true); false keeps path heights."
                    ),
                },
                "asset_order": {
                    "type": "string", "enum": [o.value for o in ScatterAssetOrder],
                    "description": "random (weighted, default) or cycle through assets in order.",
                },
                "output": {
                    "type": "string", "enum": [o.value for o in ScatterOutput],
                    "description": "placements (default) or instancer.",
                },
            },
            "required": ["name", "assets"],
        },
    ),
    Tool(
        name="drop_to_surface",
        description=(
            "Drop objects already in the scene onto the surface beneath them so "
            "they rest on it (lifting objects sunk into the ground, lowering "
            "floating ones). Each placement lands on the highest surface under "
            "its footprint. align='keep' (default) only moves vertically; "
            "align='surface' also tilts it to the ground's slope. A scatter is "
            "reseated in place: every instance moves vertically until no part of "
            "its base (a trunk, not the crown) floats, keeping its prototypes and "
            "their variant sets; align='surface' first re-tilts each instance onto "
            "the ground under its footprint, keeping its heading. Pass placement "
            "or scatter paths (/Scene/<Group>/<Name>) or whole groups."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prim_paths": {
                    "type": "array", "items": {"type": "string"}, "minItems": 1,
                    "description": "Placements, scatters or groups to drop.",
                },
                "surfaces": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Surfaces to land on (default: all other scene geometry).",
                },
                "align": {
                    "type": "string", "enum": [a.value for a in ScatterDropAlign],
                    "description": "keep (default) or surface.",
                },
            },
            "required": ["prim_paths"],
        },
    ),
]


HANDLERS = {
    "scatter_on_surface": scatter_on_surface,
    "scatter_along_path": scatter_along_path,
    "drop_to_surface": drop_to_surface,
}
