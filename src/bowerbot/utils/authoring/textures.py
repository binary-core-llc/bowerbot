# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The project's textures: copying texture files in, staging file-path values, finding users.

Texture files are copied into the project's ``textures/`` or an asset folder's
``maps/``; file-path (Asset) attribute values are resolved and copied the same way.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pxr import Sdf
from pxr import Usd

from bowerbot import constants

# ── Copying texture files ──


def copy_texture_to_project(source: Path, project_dir: Path) -> str:
    """Copy *source* into the project's ``textures/`` dir; return the rel path.

    Skips the copy if the destination already exists.
    """
    tex_dir = project_dir / constants.ASWFLayerNames.TEXTURES
    tex_dir.mkdir(parents=True, exist_ok=True)

    dest = tex_dir / source.name
    if not dest.exists():
        shutil.copy2(source, dest)

    return f"./{constants.ASWFLayerNames.TEXTURES}/{source.name}"


def stage_scene_texture(
    project_dir: Path | None, texture: str | None,
) -> str | None:
    """Copy a scene-level texture into ``<project>/textures/`` if it exists on disk."""
    if texture is None:
        return None
    source = Path(texture)
    if not source.exists():
        return texture
    if project_dir is None:
        msg = "No project set; cannot copy scene-level texture."
        raise RuntimeError(msg)
    return copy_texture_to_project(source, project_dir)


def stage_asset_texture(asset_dir: Path, texture: str | None) -> str | None:
    """Copy an HDRI into the asset's ``maps/`` dir; return the ref path."""
    if not texture:
        return texture

    maps_dir = asset_dir / constants.ASWFLayerNames.MAPS
    maps_dir.mkdir(exist_ok=True)
    tex_path = Path(texture)
    if tex_path.exists():
        dest = maps_dir / tex_path.name
        if not dest.exists():
            shutil.copy2(tex_path, dest)
        return f"./{constants.ASWFLayerNames.MAPS}/{tex_path.name}"
    return texture


# ── File-path attribute values ──


def stage_asset_value(
    value: str,
    project_dir: Path,
    library_dir: Path | None = None,
) -> str:
    """Resolve and stage an Asset-attr value into the project; raise if unresolvable."""
    if not value:
        return value
    src = Path(value)
    filename = src.name
    if not filename:
        return value

    project_rel = f"./{constants.ASWFLayerNames.TEXTURES}/{filename}"
    if (project_dir / constants.ASWFLayerNames.TEXTURES / filename).exists():
        return project_rel

    candidates: list[Path] = []
    if src.is_absolute() and src.exists():
        candidates.append(src)
    if library_dir is not None and library_dir.exists():
        candidates.extend(sorted(library_dir.rglob(filename)))
    for candidate in candidates:
        if candidate.is_file():
            return copy_texture_to_project(candidate, project_dir)

    raise ValueError(
        f"Cannot stage texture {value!r}: file not found in project's textures/, "
        "in the library, or as an absolute path. Provide an absolute path to the "
        "source file, or copy it into the library first.",
    )


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


# ── Which files use a texture ──


def find_texture_references(
    project_dir: Path,
    file_name: str,
) -> list[str]:
    """Scan *project_dir* for USD files that reference *file_name*."""
    referencing: list[str] = []
    for usd_file in sorted(project_dir.rglob("*")):
        if usd_file.suffix not in (".usd", ".usda", ".usdc"):
            continue
        try:
            stage = Usd.Stage.Open(str(usd_file))
        except Exception:
            continue
        if stage is None:
            continue
        for prim in stage.Traverse():
            tex_attr = prim.GetAttribute("inputs:texture:file")
            if not tex_attr or not tex_attr.Get():
                continue
            tex_val = tex_attr.Get()
            tex_path = (
                tex_val.path if hasattr(tex_val, "path") else str(tex_val)
            )
            if file_name in tex_path:
                referencing.append(
                    str(usd_file.relative_to(project_dir)),
                )
                break
    return referencing
