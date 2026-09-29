# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Geometry (LOD) variant sets: payloads inside variants, and their checks."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pxr import Sdf
from pxr import Usd

from bowerbot import constants
from bowerbot.utils import authoring
from bowerbot.utils import usd


def setup(
    asset_dir: Path,
    variant_set: str,
    variants: dict[str, str],
    default_variant: str,
) -> None:
    """Author a Pixar-pattern LOD variant set: clear root payload, payloads inside variants."""
    if not variants:
        raise ValueError("setup_geometry_variant_set requires at least one variant")
    if default_variant not in variants:
        raise ValueError(
            f"default_variant {default_variant!r} not present in variants "
            f"{list(variants)!r}",
        )
    usd.naming.validate_variant_name(variant_set, "variant set")
    for name in variants:
        usd.naming.validate_variant_name(name)
    for payload_ref in variants.values():
        validate_payload_path(asset_dir, payload_ref)
    validate_lod_namespace_stability(asset_dir, variants)

    authoring.asset_variants.ensure_variants_layer(asset_dir)
    authoring.asset_folder.ensure_root_reference(asset_dir, constants.ASWFLayerNames.VARIANTS)
    stage = authoring.asset_variants.open_variants_stage(asset_dir)
    root_prim_path = f"/{authoring.asset_folder.resolve_default_prim_name(asset_dir)}"

    for variant_name, payload_ref in variants.items():
        usd.variant_sets.author_in_variant(
            stage, root_prim_path, variant_set, variant_name,
            _payload_setter(payload_ref),
        )

    authoring.asset_folder.clear_root_payload(asset_dir)
    authoring.asset_variants.set_default_variant(asset_dir, variant_set, default_variant)


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


def restore_canonical_geo_if_needed(asset_dir: Path) -> bool:
    """Restore ``./geo.usda`` on the asset root when no other geometry source remains."""
    if authoring.asset_folder.asset_has_root_payload(asset_dir):
        return False
    if authoring.asset_variants.variants_have_any_payload(asset_dir):
        return False
    if not (asset_dir / constants.ASWFLayerNames.GEO).exists():
        return False

    root_file = authoring.asset_folder.find_root_file(asset_dir)
    if root_file is None:
        return False
    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return False
    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        return False
    root_prim.GetPayloads().AddPayload(f"./{constants.ASWFLayerNames.GEO}")
    stage.Save()
    return True


# ── Helpers ──


def _payload_setter(payload_ref: str) -> Callable[[Usd.Stage, str], None]:
    """Return an author function that sets the root prim's payload."""
    def author_fn(stage: Usd.Stage, prim_path: str) -> None:
        target = stage.GetPrimAtPath(prim_path)
        target.GetPayloads().ClearPayloads()
        target.GetPayloads().AddPayload(payload_ref)
    return author_fn


def _resolve_payload_path(asset_dir: Path, payload_ref: str) -> Path:
    """Resolve a payload reference (relative to ``variants.usda``) to a path."""
    candidate = Path(payload_ref)
    if candidate.is_absolute():
        return candidate
    return (asset_dir / payload_ref).resolve()


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
        if str(spec.typeName) in constants.MaterialRules.SHADING_PRIM_TYPES:
            return
        rel = str(path)[len(root_prefix):]
        paths.add(rel)

    layer.Traverse(root_path, visit)
    return paths
