# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant attributes — typing and checking the attribute overrides a variant authors."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf, Usd

from bowerbot.utils.core.asset_folder import (
    find_root_file,
)
from bowerbot.utils.texture_utils import stage_asset_value


def stage_asset_typed_overrides(
    overrides: dict[str, dict[str, object]],
    resolved_types: dict[str, dict[str, Sdf.ValueTypeName | None]],
    project_dir: Path | None,
    library_dir: Path | None,
) -> dict[str, dict[str, object]]:
    """Return a new overrides dict with Asset-typed string values staged into the project."""
    if project_dir is None:
        return overrides
    asset_type = Sdf.ValueTypeNames.Asset
    out: dict[str, dict[str, object]] = {}
    for prim_path, attrs in overrides.items():
        types = resolved_types.get(prim_path, {})
        staged: dict[str, object] = {}
        for attr_name, value in attrs.items():
            if types.get(attr_name) == asset_type and isinstance(value, str):
                staged[attr_name] = stage_asset_value(
                    value, project_dir, library_dir,
                )
            else:
                staged[attr_name] = value
        out[prim_path] = staged
    return out


def resolve_scene_attribute_types(
    stage: Usd.Stage,
    overrides: dict[str, dict[str, object]],
) -> dict[str, dict[str, Sdf.ValueTypeName | None]]:
    """Look up each scene attribute's declared type from the composed scene stage."""
    out: dict[str, dict[str, Sdf.ValueTypeName | None]] = {}
    for prim_path, attrs in overrides.items():
        resolved: dict[str, Sdf.ValueTypeName | None] = {}
        prim = stage.GetPrimAtPath(prim_path)
        for attr_name in attrs:
            type_name: Sdf.ValueTypeName | None = None
            if prim and prim.IsValid():
                attr = prim.GetAttribute(attr_name)
                if attr.IsValid():
                    type_name = attr.GetTypeName()
            resolved[attr_name] = type_name
        out[prim_path] = resolved
    return out


def resolve_attribute_types_for_overrides(
    asset_dir: Path,
    overrides: dict[str, dict[str, object]],
) -> dict[str, dict[str, Sdf.ValueTypeName | None]]:
    """Look up each override attribute's declared type from the asset's composed stage."""
    out: dict[str, dict[str, Sdf.ValueTypeName | None]] = {}
    root_file = find_root_file(asset_dir)
    stage = Usd.Stage.Open(str(root_file)) if root_file is not None else None
    for asset_path, attrs in overrides.items():
        resolved: dict[str, Sdf.ValueTypeName | None] = {}
        prim = stage.GetPrimAtPath(asset_path) if stage is not None else None
        for attr_name in attrs:
            type_name: Sdf.ValueTypeName | None = None
            if prim is not None and prim.IsValid():
                attr = prim.GetAttribute(attr_name)
                if attr.IsValid():
                    type_name = attr.GetTypeName()
            resolved[attr_name] = type_name
        out[asset_path] = resolved
    return out


def refuse_unknown_attributes(
    stage: Usd.Stage,
    resolved_types: dict[str, dict[str, Sdf.ValueTypeName | None]],
) -> None:
    """Raise if any attribute in *resolved_types* does not exist on its target prim."""
    missing: list[tuple[str, str]] = []
    for prim_path, types in resolved_types.items():
        for attr_name, type_name in types.items():
            if type_name is None:
                missing.append((prim_path, attr_name))
    if not missing:
        return

    lines = ["Attribute(s) do not exist on the target prim(s):"]
    for prim_path, attr_name in missing:
        prim = stage.GetPrimAtPath(prim_path) if stage is not None else None
        available = sorted(
            a.GetName() for a in prim.GetAttributes()
            if a.GetName().startswith("inputs:")
        ) if prim and prim.IsValid() else []
        leaf = attr_name.split(":")[-1]
        similar = [a for a in available if leaf and leaf in a]
        if similar:
            hint = f" Did you mean: {', '.join(similar[:3])}?"
        elif available:
            hint = f" Available inputs on {prim_path}: {', '.join(available[:8])}"
        else:
            hint = ""
        lines.append(f"  '{attr_name}' on {prim_path}.{hint}")
    raise ValueError("\n".join(lines))


def refuse_unknown_asset_attributes(
    asset_dir: Path,
    resolved_types: dict[str, dict[str, Sdf.ValueTypeName | None]],
) -> None:
    """Refuse override attributes that do not exist on the asset's composed prims."""
    root_file = find_root_file(asset_dir)
    stage = Usd.Stage.Open(str(root_file)) if root_file is not None else None
    refuse_unknown_attributes(stage, resolved_types)
