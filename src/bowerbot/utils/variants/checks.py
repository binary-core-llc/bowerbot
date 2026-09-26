# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant checks — payload paths, LOD namespace stability, lighting targets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pxr import Sdf, Usd, UsdLux

from bowerbot.schemas import (
    VariantRules,
)


def require_dict_param(
    params: dict[str, Any], name: str, hint: str,
) -> dict[str, Any]:
    """Read a required non-empty dict tool param; raise with a hint on miss."""
    value = params.get(name)
    if not isinstance(value, dict) or not value:
        raise ValueError(
            f"'{name}' is required and must be a non-empty object. {hint}",
        )
    return value


def validate_payload_path(asset_dir: Path, payload_ref: str) -> None:
    """Raise ``ValueError`` if a payload reference is missing or outside the asset."""
    resolved = _resolve_payload_path(asset_dir, payload_ref)
    if not resolved.exists():
        raise ValueError(
            f"Payload file does not exist: {payload_ref!r} "
            f"(resolved to {resolved}). Drop the file in the asset folder "
            "or re-export from your DCC before authoring the variant.",
        )
    try:
        resolved.relative_to(asset_dir.resolve())
    except ValueError as exc:
        raise ValueError(
            f"Payload {payload_ref!r} resolves to {resolved}, which is "
            f"outside the asset folder {asset_dir}. ASWF assets must be "
            "self-contained: copy the file into the asset folder and "
            "reference it as './<name>.usda'.",
        ) from exc


def _resolve_payload_path(asset_dir: Path, payload_ref: str) -> Path:
    """Resolve a payload reference (relative to ``variants.usda``) to a path."""
    candidate = Path(payload_ref)
    if candidate.is_absolute():
        return candidate
    return (asset_dir / payload_ref).resolve()


def validate_lod_namespace_stability(
    asset_dir: Path, payload_refs: dict[str, str],
) -> None:
    """Refuse if LOD payloads diverge in their geometry prim hierarchy."""
    if len(payload_refs) < 2:
        return

    namespaces: dict[str, set[str]] = {}
    for variant_name, ref in payload_refs.items():
        resolved = _resolve_payload_path(asset_dir, ref)
        namespaces[variant_name] = _collect_geometry_prim_paths(resolved)

    items = sorted(namespaces.items())
    canonical_name, canonical_set = items[0]
    divergences: list[tuple[str, set[str], set[str]]] = []
    for name, paths in items[1:]:
        only_canonical = canonical_set - paths
        only_other = paths - canonical_set
        if only_canonical or only_other:
            divergences.append((name, only_canonical, only_other))

    if not divergences:
        return

    lines = [
        "LOD payloads have divergent prim hierarchies. Production LODs "
        "must preserve the same prim names so material bindings, "
        "light-linking, collections, and per-instance overrides compose "
        "uniformly across every LOD. Differences vs "
        f"'{canonical_name}' ({sorted(canonical_set)[:5]}"
        f"{'...' if len(canonical_set) > 5 else ''}):",
    ]
    for name, only_canonical, only_other in divergences:
        if only_canonical:
            sample = sorted(only_canonical)[:5]
            suffix = "..." if len(only_canonical) > 5 else ""
            lines.append(f"  '{name}' is missing: {sample}{suffix}")
        if only_other:
            sample = sorted(only_other)[:5]
            suffix = "..." if len(only_other) > 5 else ""
            lines.append(f"  '{name}' has extra: {sample}{suffix}")
    lines.append(
        "Fix the LOD export to share the same prim hierarchy, or use "
        "separate asset folders if these are genuinely different assets.",
    )
    raise ValueError("\n".join(lines))


def _collect_geometry_prim_paths(payload_path: Path) -> set[str]:
    """Return prim paths under a payload's default prim, relative to it."""
    layer = Sdf.Layer.FindOrOpen(str(payload_path))
    if layer is None:
        raise ValueError(f"Cannot open payload file: {payload_path}")
    default = layer.defaultPrim
    if not default:
        raise ValueError(
            f"Payload {payload_path.name} has no defaultPrim; cannot "
            "validate LOD prim hierarchy.",
        )

    root_path = Sdf.Path(f"/{default}")
    root_prefix = f"/{default}"
    paths: set[str] = set()

    def visit(path: Sdf.Path) -> None:
        if path == root_path or path == Sdf.Path.absoluteRootPath:
            return
        spec = layer.GetObjectAtPath(path)
        if not isinstance(spec, Sdf.PrimSpec):
            return
        if str(spec.typeName) in VariantRules.NON_GEOMETRY_TYPES:
            return
        rel = str(path)[len(root_prefix):]
        paths.add(rel)

    layer.Traverse(root_path, visit)
    return paths


def validate_scene_lighting_targets(
    stage: Usd.Stage, carrier: str, paths,
) -> None:
    """Refuse target paths outside the carrier or not UsdLux lights."""
    for path in paths:
        if not path.startswith(carrier + "/"):
            raise ValueError(
                f"Lighting variant targets must be under {carrier}. Got: {path}",
            )
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.IsValid():
            raise ValueError(f"Prim not found: {path}")
        if not prim.HasAPI(UsdLux.LightAPI):
            raise ValueError(
                f"{path} is not a UsdLux light. Lighting variants target "
                "UsdLux prims only.",
            )
