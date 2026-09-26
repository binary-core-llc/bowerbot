# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Scatter service — distribute assets over surfaces, along paths, and drop them to rest."""

from __future__ import annotations

import logging
from typing import Any

from bowerbot.schemas import (
    ScatterAlign,
    ScatterArrangement,
    ScatterAsset,
    ScatterAssetOrder,
    ScatterDropAlign,
    ScatterNamespace,
    ScatterOutput,
    ScatterPathFacing,
    ScatterPathParams,
    ScatterPathSide,
    ScatterPoseParams,
    ScatterSurfaceParams,
    SceneNamespace,
)
from bowerbot.state import SceneState
from bowerbot.utils import stage_utils, surface_utils
from bowerbot.utils.core.metrics import axis_index
from bowerbot.utils.scatter.along_path import estimate_path_scatter, generate_path_scatter
from bowerbot.utils.scatter.authoring import count_by_prototype, write_scatter
from bowerbot.utils.scatter.drop import drop_prim, drop_scatter, drop_targets
from bowerbot.utils.scatter.inputs import (
    check_target,
    derive_seed,
    parse_path_circle,
    parse_region,
    parse_scale_range,
    scatter_prim_path,
)
from bowerbot.utils.scatter.on_surface import estimate_surface_scatter, generate_surface_scatter
from bowerbot.utils.scatter.prototypes import resolve_asset_sources, stage_prototypes

logger = logging.getLogger(__name__)


def scatter_on_surface(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Distribute assets over surface prims, each piece resting on the surface it lands on."""
    stage = state.require_stage()
    project = state.require_project()
    up = axis_index(state.up_axis.value)
    arrangement = ScatterArrangement(params.get("arrangement", ScatterArrangement.RANDOM))
    count = params.get("count")
    density = params.get("density")
    if arrangement is ScatterArrangement.RANDOM and (count is None) == (density is None):
        msg = "arrangement 'random' needs exactly one of 'count' or 'density'."
        raise ValueError(msg)
    if arrangement is ScatterArrangement.ROWS:
        if params.get("spacing") is None or params.get("row_spacing") is None:
            msg = (
                "arrangement 'rows' needs 'spacing' (along a row) and "
                "'row_spacing' (between rows)."
            )
            raise ValueError(msg)
        if count is not None or density is not None:
            msg = (
                "arrangement 'rows' is sized by 'spacing' and 'row_spacing'; "
                "omit 'count' and 'density'."
            )
            raise ValueError(msg)
    if arrangement is ScatterArrangement.PILE and (count is None or density is not None):
        msg = "arrangement 'pile' needs 'count' (and no 'density')."
        raise ValueError(msg)
    if params.get("min_spacing") is not None and arrangement is not ScatterArrangement.RANDOM:
        msg = "'min_spacing' only applies to arrangement 'random'."
        raise ValueError(msg)
    region = parse_region(stage, params.get("region"), up)
    if arrangement is ScatterArrangement.PILE and (region is None or region.radius is None):
        msg = (
            "arrangement 'pile' needs a circular 'region' "
            "(center or center_prim + radius) for where the heap sits."
        )
        raise ValueError(msg)

    surface = ScatterSurfaceParams(
        arrangement=arrangement,
        count=count,
        density=density,
        min_spacing=params.get("min_spacing"),
        variation=params.get("variation", 0.0),
        variation_scale=params.get("variation_scale"),
        region=region,
        avoid_margin=params.get("avoid_margin", 0.0),
        max_slope_degrees=params.get("max_slope_degrees", 60.0),
        spacing=params.get("spacing"),
        row_spacing=params.get("row_spacing"),
        row_direction_degrees=params.get("row_direction_degrees", 0.0),
        jitter=params.get("jitter", 0.0),
        repose_degrees=params.get("repose_degrees", 35.0),
    )
    pose = ScatterPoseParams(
        align=ScatterAlign(params.get("align", ScatterAlign.SURFACE)),
        random_yaw=params.get("random_yaw", True),
        tilt_jitter_degrees=params.get("tilt_jitter_degrees", 0.0),
        scale_range=parse_scale_range(params.get("scale_range")),
        embed=params.get("embed", 0.0),
    )
    output = ScatterOutput(params.get("output", ScatterOutput.INSTANCER))

    prim_path = scatter_prim_path(
        params.get("group", ScatterNamespace.DEFAULT_GROUP), params["name"],
    )
    check_target(stage, prim_path, replace=params.get("replace", False))
    project_dir = project.path
    sources = resolve_asset_sources(
        [ScatterAsset(**asset) for asset in params["assets"]],
        project_dir=project_dir, library_dir=state.library_dir,
    )
    triangles = surface_utils.collect_triangles(
        stage, params["surfaces"], up=up, exclude=[prim_path],
    )
    avoid = None
    if params.get("avoid"):
        avoid = surface_utils.build_vertical_index(
            surface_utils.collect_triangles(
                stage, params["avoid"], up=up, exclude=[prim_path],
                instancer_footprints=True,
            ),
            up, pad=surface.avoid_margin,
        )
    seed = derive_seed(prim_path, params.get("seed"))

    if params.get("validate_only", False):
        estimate, area_m2 = estimate_surface_scatter(
            surface, triangles=triangles, avoid=avoid, up=up,
            mpu=state.meters_per_unit, seed=seed,
        )
        return {
            "valid": True,
            "prim_path": prim_path,
            "estimated_instances": estimate,
            "eligible_area_m2": round(area_m2, 3),
            "seed": seed,
            "message": (
                f"Scatter is valid: about {estimate:,} instance(s) over "
                f"{area_m2:,.2f} m2 of eligible surface. Nothing was written."
            ),
        }

    prototypes = stage_prototypes(
        stage, sources, assets_dir=state.resolve_assets_dir(),
        library_dir=state.library_dir, project_dir=project_dir,
    )
    instances, warnings = generate_surface_scatter(
        surface, pose, triangles=triangles, avoid=avoid, prototypes=prototypes,
        up=up, mpu=state.meters_per_unit, seed=seed,
    )
    if instances.count == 0:
        msg = "The scatter produced no instances. " + " ".join(warnings)
        raise ValueError(msg.strip())

    object_count_snapshot = state.object_count
    try:
        written = write_scatter(
            stage, prim_path=prim_path, output=output,
            prototypes=prototypes, instances=instances,
            first_index=state.object_count + 1,
        )
        state.object_count += written["placements"] or 1
        stage_utils.save_stage(stage)
    except Exception:
        state.object_count = object_count_snapshot
        stage.Reload()
        raise
    warnings += written["warnings"]
    state.touch_project()

    logger.info(
        "scatter_on_surface %s: %d instance(s) as %s", prim_path, instances.count,
        output.value,
    )
    return {
        "prim_path": prim_path,
        "output": output.value,
        "instances": instances.count,
        "by_asset": count_by_prototype(prototypes, instances),
        "seed": seed,
        "warnings": warnings,
        "message": (
            f"Scattered {instances.count:,} instance(s) at {prim_path} "
            f"({output.value}, seed {seed})."
        ),
    }


def scatter_along_path(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Place assets along a polyline, circle or curve, resting each on the surface below."""
    stage = state.require_stage()
    project = state.require_project()
    up = axis_index(state.up_axis.value)
    given = [key for key in ("points", "circle", "curve_prim") if params.get(key) is not None]
    if len(given) != 1:
        msg = (
            "scatter_along_path needs exactly one of 'points', 'circle', "
            f"or 'curve_prim' (got {given or 'none'})."
        )
        raise ValueError(msg)
    if params.get("count") is not None and params.get("spacing") is not None:
        msg = "give 'count' or 'spacing', not both."
        raise ValueError(msg)
    facing = ScatterPathFacing(params.get("facing", ScatterPathFacing.TANGENT))
    if facing is ScatterPathFacing.FIXED and params.get("direction_degrees") is None:
        msg = "facing 'fixed' needs 'direction_degrees'."
        raise ValueError(msg)
    sides = ScatterPathSide(params.get("sides", ScatterPathSide.CENTER))
    offset = params.get("offset", 0.0)
    if sides is not ScatterPathSide.CENTER and offset <= 0:
        msg = f"sides '{sides.value}' needs a positive 'offset'."
        raise ValueError(msg)

    path = ScatterPathParams(
        points=params.get("points"),
        closed=params.get("closed", False),
        circle=parse_path_circle(stage, params.get("circle"), up),
        curve_prim=params.get("curve_prim"),
        count=params.get("count"),
        spacing=params.get("spacing"),
        gap=params.get("gap", 0.0),
        start_offset=params.get("start_offset", 0.0),
        sides=sides,
        offset=offset,
        facing=facing,
        direction_degrees=params.get("direction_degrees"),
        yaw_offset_degrees=params.get("yaw_offset_degrees", 0.0),
        follow_slope=params.get("follow_slope", False),
        asset_order=ScatterAssetOrder(params.get("asset_order", ScatterAssetOrder.RANDOM)),
    )
    pose = ScatterPoseParams(
        align=ScatterAlign(params.get("align", ScatterAlign.UP)),
        scale_range=parse_scale_range(params.get("scale_range")),
        embed=params.get("embed", 0.0),
    )
    output = ScatterOutput(params.get("output", ScatterOutput.PLACEMENTS))

    prim_path = scatter_prim_path(
        params.get("group", ScatterNamespace.DEFAULT_GROUP), params["name"],
    )
    check_target(stage, prim_path, replace=params.get("replace", False))
    project_dir = project.path
    sources = resolve_asset_sources(
        [ScatterAsset(**asset) for asset in params["assets"]],
        project_dir=project_dir, library_dir=state.library_dir,
    )
    seed = derive_seed(prim_path, params.get("seed"))

    if params.get("validate_only", False):
        estimate, length = estimate_path_scatter(stage, path, up)
        count_text = (
            f"{estimate:,} instance(s)" if estimate is not None
            else "a count set by the assets' length (automatic spacing)"
        )
        return {
            "valid": True,
            "prim_path": prim_path,
            "estimated_instances": estimate,
            "path_length": round(length, 4),
            "seed": seed,
            "message": (
                f"Path is valid: {length:,.2f} scene units long, {count_text}. "
                "Nothing was written."
            ),
        }

    index = None
    if params.get("snap", True):
        index = surface_utils.build_vertical_index(
            surface_utils.collect_triangles(
                stage, params.get("surfaces") or [SceneNamespace.ROOT],
                up=up, exclude=[prim_path],
            ),
            up, up_facing_only=True,
        )
    prototypes = stage_prototypes(
        stage, sources, assets_dir=state.resolve_assets_dir(),
        library_dir=state.library_dir, project_dir=project_dir,
    )
    instances, warnings = generate_path_scatter(
        stage, path, pose, prototypes=prototypes, index=index, up=up, seed=seed,
    )

    object_count_snapshot = state.object_count
    try:
        written = write_scatter(
            stage, prim_path=prim_path, output=output,
            prototypes=prototypes, instances=instances,
            first_index=state.object_count + 1,
        )
        state.object_count += written["placements"] or 1
        stage_utils.save_stage(stage)
    except Exception:
        state.object_count = object_count_snapshot
        stage.Reload()
        raise
    warnings += written["warnings"]
    state.touch_project()

    logger.info(
        "scatter_along_path %s: %d instance(s) as %s", prim_path, instances.count,
        output.value,
    )
    return {
        "prim_path": prim_path,
        "output": output.value,
        "instances": instances.count,
        "by_asset": count_by_prototype(prototypes, instances),
        "seed": seed,
        "warnings": warnings,
        "message": (
            f"Placed {instances.count:,} instance(s) along the path at {prim_path} "
            f"({output.value})."
        ),
    }


def drop_to_surface(state: SceneState, params: dict[str, Any]) -> dict[str, Any]:
    """Drop existing placements, and reseat scatters, onto the surface beneath them."""
    stage = state.require_stage()
    up = axis_index(state.up_axis.value)
    align = ScatterDropAlign(params.get("align", ScatterDropAlign.KEEP))
    wrappers, scatters = drop_targets(stage, params["prim_paths"])
    index = surface_utils.build_vertical_index(
        surface_utils.collect_triangles(
            stage, params.get("surfaces") or [SceneNamespace.ROOT],
            up=up, exclude=wrappers,
        ),
        up, up_facing_only=True,
    )

    try:
        results = [
            drop_prim(stage, path, index, align=align)
            for path in wrappers
        ]
        scatter_results = [
            drop_scatter(stage, path, index, align=align) for path in scatters
        ]
        stage_utils.save_stage(stage)
    except Exception:
        stage.Reload()
        raise
    state.touch_project()

    moved = [r for r in results if r["supported"]]
    reseated = [r for r in scatter_results if r["supported"]]
    unsupported = [
        r["prim_path"] for r in results + scatter_results if not r["supported"]
    ]
    logger.info(
        "drop_to_surface moved %d placement(s), reseated %d scatter(s)",
        len(moved), len(reseated),
    )
    parts = []
    if wrappers:
        parts.append(f"Dropped {len(moved)} placement(s) onto the surface below.")
    if reseated:
        parts.append(
            f"Reseated {sum(r['instances'] for r in reseated):,} instance(s) "
            f"in {len(reseated)} scatter(s) on the surface under their bases.",
        )
    parts.extend(
        f"{r['no_surface_under']['count']} instance(s) of {r['prim_path']} have no "
        "surface under their base (e.g. past the terrain's edge) and were left in "
        "place; see no_surface_under."
        for r in reseated if r["no_surface_under"]["count"]
    )
    message = " ".join(parts)
    if unsupported:
        message += f" {len(unsupported)} had no surface under them and were left in place."
    return {
        "moved": moved,
        "scatters": reseated,
        "unsupported": unsupported,
        "message": message,
    }
