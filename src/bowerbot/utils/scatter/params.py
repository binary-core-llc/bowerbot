# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Validating scatter inputs: the target path, seed, scale range, region and path circle."""

from __future__ import annotations

import hashlib
from typing import Any

from pxr import Usd

from bowerbot import schemas
from bowerbot.utils import authoring
from bowerbot.utils import usd


def target_path(group: str, name: str) -> str:
    """``/Scene/<group>/<name>`` for a scatter, validating both parts."""
    group_path = authoring.placement.scene_group_path(group)
    prim_name = usd.naming.safe_prim_name(name)
    if not usd.naming.is_valid_prim_name(prim_name):
        msg = (
            f"name '{name}' is not a valid USD prim name (letters, digits, "
            "underscores; must start with a letter or underscore)."
        )
        raise ValueError(msg)
    return f"{group_path}/{prim_name}"


def check_target(stage: Usd.Stage, prim_path: str, *, replace: bool) -> bool:
    """Return whether *prim_path* exists; refuse when it does and *replace* is off."""
    exists = bool(stage.GetPrimAtPath(prim_path).IsValid())
    if exists and not replace:
        msg = (
            f"{prim_path} already exists. Pass replace=true to regenerate it "
            "(same seed gives the same result), or choose another name."
        )
        raise ValueError(msg)
    return exists


def derive_seed(prim_path: str, seed: int | None) -> int:
    """The explicit *seed*, or a stable one derived from the scatter's path."""
    if seed is not None:
        return seed
    digest = hashlib.blake2b(prim_path.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "little")


def parse_scale_range(raw: list[float] | None) -> tuple[float, float]:
    """Validate a ``[min, max]`` scale range (default no scaling)."""
    if raw is None:
        return 1.0, 1.0
    low, high = float(raw[0]), float(raw[1])
    if low > high:
        msg = "'scale_range' must be [min, max] with min <= max."
        raise ValueError(msg)
    return low, high


def parse_region(
    stage: Usd.Stage, raw: dict[str, Any] | None, up: int,
) -> schemas.ScatterRegion | None:
    """Validate a raw ``region`` and resolve its ``center_prim`` to a centre point."""
    if raw is None:
        return None
    falloff = schemas.ScatterRegionFalloff(raw.get("falloff", schemas.ScatterRegionFalloff.NONE))
    polygon = raw.get("polygon")
    if polygon is not None:
        if any(raw.get(key) is not None for key in ("center", "center_prim", "radius")):
            msg = (
                "region is either a polygon or a circle "
                "(center/center_prim + radius), not both."
            )
            raise ValueError(msg)
        return schemas.ScatterRegion(polygon=[tuple(point) for point in polygon], falloff=falloff)
    if raw.get("radius") is None:
        msg = "a circular region needs 'radius'."
        raise ValueError(msg)
    center = _circle_center(stage, raw, up, "a circular region")
    return schemas.ScatterRegion(center=center, radius=float(raw["radius"]), falloff=falloff)


def parse_path_circle(
    stage: Usd.Stage, raw: dict[str, Any] | None, up: int,
) -> schemas.ScatterPathCircle | None:
    """Validate a raw path ``circle`` and resolve its ``center_prim`` to a centre point."""
    if raw is None:
        return None
    return schemas.ScatterPathCircle(
        center=_circle_center(stage, raw, up, "'circle'"),
        radius=float(raw["radius"]),
        start_angle_degrees=float(raw.get("start_angle_degrees", 0.0)),
    )


# ── Helpers ──


def _circle_center(
    stage: Usd.Stage, raw: dict[str, Any], up: int, label: str,
) -> tuple[float, float, float]:
    """A circle's centre from ``center`` or from ``center_prim``."""
    if (raw.get("center") is None) == (raw.get("center_prim") is None):
        msg = f"{label} needs exactly one of 'center' or 'center_prim'."
        raise ValueError(msg)
    if raw.get("center") is not None:
        return usd.values.vec3(raw["center"])
    bmin, bmax = usd.bounds.prim_world_box(stage, raw["center_prim"])
    return tuple(usd.bounds.base_center(bmin, bmax, up).tolist())
