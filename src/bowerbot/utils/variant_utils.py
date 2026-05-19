# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Universal variant-set primitives.

Opinion-agnostic. Anything USD can author into a variant goes through
``author_in_variant``. Services layer category orchestrators on top.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

from pxr import Sdf, Usd

from bowerbot.schemas import (
    ASWFLayerNames,
    SceneVariantsSummary,
    VariantCarrier,
    VariantSetSummary,
    VariantsSummary,
)
from bowerbot.utils.asset_folder_utils import (
    asset_has_root_payload,
    clear_root_payload,
    find_root_file,
    rebuild_root_references,
    resolve_default_prim_name,
)
from bowerbot.utils.stage_utils import (
    find_asset_placements,
    get_prim_ref_paths,
    prune_empty_overrides,
)
from bowerbot.utils.texture_utils import stage_asset_value

VariantAuthorFn = Callable[[Usd.Stage, str], None]


# ── Layer lifecycle ──


def _variants_layer_path(asset_dir: Path) -> Path:
    """Return the canonical ``variants.usda`` path."""
    return asset_dir / ASWFLayerNames.VARIANTS


def ensure_variants_layer(asset_dir: Path) -> Path:
    """Create ``variants.usda`` if missing."""
    path = _variants_layer_path(asset_dir)
    if path.exists():
        return path

    default_prim_name = resolve_default_prim_name(asset_dir)
    layer = Sdf.Layer.CreateNew(str(path))
    layer.defaultPrim = default_prim_name
    Sdf.CreatePrimInLayer(layer, Sdf.Path(f"/{default_prim_name}"))
    layer.GetPrimAtPath(f"/{default_prim_name}").specifier = Sdf.SpecifierOver
    layer.Save()
    return path


def ensure_variants_referenced(asset_dir: Path) -> None:
    """Ensure the asset root references ``variants.usda``."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return
    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        return

    if f"./{ASWFLayerNames.VARIANTS}" in get_prim_ref_paths(root_prim):
        return

    del stage
    rebuild_root_references(asset_dir)


def _remove_variants_reference(asset_dir: Path) -> None:
    """Remove the ``variants.usda`` reference from the asset root."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return

    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return

    target = f"./{ASWFLayerNames.VARIANTS}"
    ref_list = prim_spec.referenceList
    for items in (
        ref_list.prependedItems,
        ref_list.appendedItems,
        ref_list.addedItems,
        ref_list.explicitItems,
        ref_list.orderedItems,
    ):
        for r in [x for x in items if x.assetPath == target]:
            items.remove(r)
    layer.Save()


# ── Variant set + variant declaration ──


def open_variants_stage(asset_dir: Path) -> Usd.Stage:
    """Open ``variants.usda`` as a stage."""
    path = ensure_variants_layer(asset_dir)
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise RuntimeError(f"Failed to open variants layer: {path}")
    return stage


# ── Universal authoring primitive ──


def author_in_variant(
    stage: Usd.Stage,
    prim_path: str,
    set_name: str,
    variant_name: str,
    author_fn: VariantAuthorFn,
) -> None:
    """Run ``author_fn(stage, prim_path)`` inside the variant's edit context."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {prim_path}")

    vset = prim.GetVariantSets().GetVariantSet(set_name)
    if not vset.IsValid():
        vset = prim.GetVariantSets().AddVariantSet(set_name)
    if variant_name not in vset.GetVariantNames():
        vset.AddVariant(variant_name)

    vset.SetVariantSelection(variant_name)
    with vset.GetVariantEditContext():
        author_fn(stage, prim_path)
    vset.ClearVariantSelection()
    stage.Save()


def setup_geometry_variant_set(
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
    validate_variant_name(variant_set, "variant set")
    for name in variants:
        validate_variant_name(name)
    for payload_ref in variants.values():
        validate_payload_path(asset_dir, payload_ref)
    validate_lod_namespace_stability(asset_dir, variants)

    ensure_variants_layer(asset_dir)
    ensure_variants_referenced(asset_dir)
    stage = open_variants_stage(asset_dir)
    root_prim_path = f"/{resolve_default_prim_name(asset_dir)}"

    for variant_name, payload_ref in variants.items():
        author_in_variant(
            stage, root_prim_path, variant_set, variant_name,
            _payload_setter(payload_ref),
        )

    clear_root_payload(asset_dir)
    set_default_variant(asset_dir, variant_set, default_variant)


def _payload_setter(payload_ref: str) -> VariantAuthorFn:
    """Return an author function that sets the root prim's payload."""
    def author_fn(stage: Usd.Stage, prim_path: str) -> None:
        target = stage.GetPrimAtPath(prim_path)
        target.GetPayloads().ClearPayloads()
        target.GetPayloads().AddPayload(payload_ref)
    return author_fn


def apply_variant(
    asset_dir: Path,
    variant_set: str,
    variant_name: str,
    author_fn: VariantAuthorFn,
    set_as_default: bool = False,
) -> None:
    """End-to-end variant authoring: layer, reference, opinions, default selection."""
    ensure_variants_layer(asset_dir)
    ensure_variants_referenced(asset_dir)
    stage = open_variants_stage(asset_dir)
    author_in_variant(
        stage, f"/{resolve_default_prim_name(asset_dir)}",
        variant_set, variant_name, author_fn,
    )

    summary = get_variant_summary(asset_dir)
    existing = next(
        (s for s in summary.variant_sets if s.name == variant_set), None,
    )
    needs_default = set_as_default or (existing is not None and not existing.selection)
    if needs_default:
        set_default_variant(asset_dir, variant_set, variant_name)


# ── Default selection on the asset root ──


def set_default_variant(
    asset_dir: Path, set_name: str, variant_name: str,
) -> None:
    """Author the default variant selection on the asset root prim."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        raise ValueError(f"No root file in {asset_dir}")
    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        raise RuntimeError(f"Failed to open {root_file}")
    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        raise ValueError(f"No defaultPrim in {root_file}")

    vset = root_prim.GetVariantSets().GetVariantSet(set_name)
    if not vset.IsValid():
        raise ValueError(f"Variant set '{set_name}' not visible on root prim")
    vset.SetVariantSelection(variant_name)
    stage.Save()


def clear_default_variant(asset_dir: Path, set_name: str) -> None:
    """Clear the default variant selection on the asset root prim."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return
    if set_name in prim_spec.variantSelections:
        del prim_spec.variantSelections[set_name]
        layer.Save()


def _clear_all_default_variants(asset_dir: Path) -> None:
    """Clear every variant selection on the asset root prim."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return
    if prim_spec.variantSelections:
        prim_spec.variantSelections.clear()
        layer.Save()


# ── Scene composition inspection ──


def find_variant_carriers(
    stage: Usd.Stage,
    scene_prim_path: str,
    variant_set: str | None = None,
) -> list[VariantCarrier]:
    """Composed prims under ``scene_prim_path`` that expose variant sets."""
    root = stage.GetPrimAtPath(scene_prim_path)
    if not root or not root.IsValid():
        raise ValueError(f"Prim not found in scene: {scene_prim_path}")

    carriers: list[VariantCarrier] = []
    for prim in Usd.PrimRange(root):
        names = list(prim.GetVariantSets().GetNames())
        if not names:
            continue
        if variant_set is not None and variant_set not in names:
            continue
        carriers.append(VariantCarrier(
            prim_path=str(prim.GetPath()),
            variant_sets=[
                _read_variant_set(prim, name)
                for name in names
                if variant_set is None or name == variant_set
            ],
        ))
    return carriers


def get_scene_variants_summary(
    stage: Usd.Stage, scene_prim_path: str,
) -> SceneVariantsSummary:
    """Scene-composition view of every variant set visible under a placement."""
    return SceneVariantsSummary(
        prim_path=scene_prim_path,
        carriers=find_variant_carriers(stage, scene_prim_path),
    )


def _read_variant_set(prim: Usd.Prim, name: str) -> VariantSetSummary:
    """Read a single variant set's variants and current selection."""
    vset = prim.GetVariantSets().GetVariantSet(name)
    return VariantSetSummary(
        name=name,
        variants=list(vset.GetVariantNames()),
        selection=vset.GetVariantSelection() or None,
    )


# ── Asset folder inspection ──


def get_variant_summary(asset_dir: Path) -> VariantsSummary:
    """Return all variant sets, variants, and selections."""
    root_file = find_root_file(asset_dir)
    has_layer = _variants_layer_path(asset_dir).exists()

    if root_file is None:
        return VariantsSummary(
            asset_path=str(asset_dir), has_variants_layer=has_layer,
        )

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return VariantsSummary(
            asset_path=str(asset_dir), has_variants_layer=has_layer,
        )
    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        return VariantsSummary(
            asset_path=str(asset_dir), has_variants_layer=has_layer,
        )

    sets = [
        _read_variant_set(root_prim, name)
        for name in root_prim.GetVariantSets().GetNames()
    ]
    return VariantsSummary(
        asset_path=str(asset_dir),
        has_variants_layer=has_layer,
        variant_sets=sets,
    )


# ── Removal ──


def remove_variant(
    asset_dir: Path, set_name: str, variant_name: str,
) -> bool:
    """Remove one variant from a variant set."""
    variants_path = _variants_layer_path(asset_dir)
    if not variants_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return False
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return False

    vset_spec = prim_spec.variantSets.get(set_name)
    if vset_spec is None:
        return False
    existing = list(vset_spec.variants.keys())
    if variant_name not in existing:
        return False

    if len(existing) == 1:
        del prim_spec.variantSets[set_name]
        _scrub_variant_set_metadata(prim_spec, set_name)
        layer.Save()
        return True

    surviving = [v for v in existing if v != variant_name]

    temp_layer = Sdf.Layer.CreateAnonymous()
    for v in surviving:
        Sdf.CreateVariantInLayer(temp_layer, prim_spec.path, set_name, v)
        var_path = prim_spec.path.AppendVariantSelection(set_name, v)
        if layer.GetObjectAtPath(var_path) is not None:
            Sdf.CopySpec(layer, var_path, temp_layer, var_path)

    del prim_spec.variantSets[set_name]
    _scrub_variant_set_metadata(prim_spec, set_name)

    for v in surviving:
        Sdf.CreateVariantInLayer(layer, prim_spec.path, set_name, v)
        var_path = prim_spec.path.AppendVariantSelection(set_name, v)
        if temp_layer.GetObjectAtPath(var_path) is not None:
            Sdf.CopySpec(temp_layer, var_path, layer, var_path)

    layer.Save()
    return True


def remove_variant_set(asset_dir: Path, set_name: str) -> bool:
    """Remove an entire variant set."""
    variants_path = _variants_layer_path(asset_dir)
    if not variants_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return False
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return False

    if set_name not in prim_spec.variantSets:
        return False

    del prim_spec.variantSets[set_name]
    _scrub_variant_set_metadata(prim_spec, set_name)
    layer.Save()
    return True


def _has_variant_sets(asset_dir: Path) -> bool:
    """Return whether ``variants.usda`` declares any variant sets."""
    variants_path = _variants_layer_path(asset_dir)
    if not variants_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return False
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return False
    return bool(prim_spec.variantSets) or bool(
        _all_variant_set_names_in_metadata(prim_spec),
    )


def _variants_have_any_payload(asset_dir: Path) -> bool:
    """Whether any variant body in ``variants.usda`` authors a payload."""
    variants_path = _variants_layer_path(asset_dir)
    if not variants_path.exists():
        return False
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return False

    found = False

    def visit(path: Sdf.Path) -> None:
        nonlocal found
        if found:
            return
        spec = layer.GetPrimAtPath(path)
        if spec is None:
            return
        plist = spec.payloadList
        if (
            plist.prependedItems
            or plist.appendedItems
            or plist.addedItems
            or plist.explicitItems
        ):
            found = True

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return found


def restore_canonical_geo_if_needed(asset_dir: Path) -> bool:
    """Restore ``./geo.usda`` on the asset root when no other geometry source remains."""
    if asset_has_root_payload(asset_dir):
        return False
    if _variants_have_any_payload(asset_dir):
        return False
    if not (asset_dir / ASWFLayerNames.GEO).exists():
        return False

    root_file = find_root_file(asset_dir)
    if root_file is None:
        return False
    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return False
    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        return False
    root_prim.GetPayloads().AddPayload(f"./{ASWFLayerNames.GEO}")
    stage.Save()
    return True


def cleanup_if_empty(asset_dir: Path) -> bool:
    """Delete ``variants.usda`` and scrub references when no variant sets remain."""
    if _has_variant_sets(asset_dir):
        return False

    _remove_variants_reference(asset_dir)
    _clear_all_default_variants(asset_dir)

    variants_path = _variants_layer_path(asset_dir)
    if variants_path.exists():
        layer = Sdf.Layer.FindOrOpen(str(variants_path))
        if layer is not None:
            layer.Clear()
        variants_path.unlink()

    return True


# ── Naming ──


_FORBIDDEN_NAME_CHARS = frozenset(" \t\n\r/\\")


def is_valid_variant_set_name(name: str) -> bool:
    """Reject empty names or names with whitespace / path separators."""
    return bool(name) and not any(c in _FORBIDDEN_NAME_CHARS for c in name)


def validate_variant_name(name: str, label: str = "variant") -> None:
    """Raise ``ValueError`` if ``name`` is not a valid variant identifier."""
    if not is_valid_variant_set_name(name):
        raise ValueError(f"Invalid {label} name: {name!r}")


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


def _resolve_payload_path(asset_dir: Path, payload_ref: str) -> Path:
    """Resolve a payload reference (relative to ``variants.usda``) to a path."""
    candidate = Path(payload_ref)
    if candidate.is_absolute():
        return candidate
    return (asset_dir / payload_ref).resolve()


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


_NON_GEOMETRY_TYPES = frozenset({"Material", "Shader", "NodeGraph"})


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
        if str(spec.typeName) in _NON_GEOMETRY_TYPES:
            return
        rel = str(path)[len(root_prefix):]
        paths.add(rel)

    layer.Traverse(root_path, visit)
    return paths


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
        f"'{canonical_name}' ({sorted(canonical_set)[:5]}{'...' if len(canonical_set) > 5 else ''}):",
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


OpinionKind = Literal["attribute", "relationship", "active"]


def find_masking_scene_opinions(
    stage: Usd.Stage,
    asset_dir: Path,
    default_prim: str,
    target_map: dict[str, Iterable[str]],
    kind: OpinionKind,
) -> list[tuple[str, str]]:
    """Return (scene_prim_path, key) pairs in scene.usda that would mask a variant body opinion.

    *target_map* maps asset-local prim path -> iterable of keys the variant
    is about to author at that path. *kind* names which spec slot to inspect:
    ``"attribute"`` (key is attribute name), ``"relationship"`` (key is
    relationship name, typically ``"material:binding"``), or ``"active"``
    (key is always ``"active"`` — the prim's active metadata).
    """
    placements = find_asset_placements(stage, asset_dir)
    if not placements:
        return []
    layer = stage.GetRootLayer()
    asset_prefix = f"/{default_prim}"
    masking: list[tuple[str, str]] = []
    for asset_path, keys in target_map.items():
        tail = (
            asset_path[len(asset_prefix):]
            if asset_path.startswith(asset_prefix)
            else asset_path
        )
        for placement in placements:
            scene_path = f"{placement}{tail}" if tail else placement
            spec = layer.GetPrimAtPath(scene_path)
            if spec is None:
                continue
            for key in keys:
                if _has_authored_opinion(spec, key, kind):
                    masking.append((scene_path, key))
    return masking


def enforce_no_masking_overrides(
    stage: Usd.Stage,
    asset_dir: Path,
    default_prim: str,
    target_map: dict[str, Iterable[str]],
    kind: OpinionKind,
    variant_kind: str,
    *,
    clear: bool,
    confirm: bool,
) -> bool:
    """Detect/clear/refuse masking scene opinions; return True if stage needs reload."""
    masking = find_masking_scene_opinions(
        stage, asset_dir, default_prim, target_map, kind,
    )
    if not masking:
        return False
    if clear:
        clear_masking_scene_opinions(stage, masking, kind)
        return True
    if not confirm:
        raise ValueError(format_masking_override_error(variant_kind, masking))
    return False


def clear_masking_scene_opinions(
    stage: Usd.Stage,
    opinions: list[tuple[str, str]],
    kind: OpinionKind,
) -> None:
    """Remove the listed masking opinions from the stage's root layer."""
    layer = stage.GetRootLayer()
    touched_paths: set[str] = set()
    for prim_path, key in opinions:
        spec = layer.GetPrimAtPath(prim_path)
        if spec is None:
            continue
        if kind == "attribute":
            attr_spec = spec.attributes.get(key)
            if attr_spec is not None:
                spec.RemoveProperty(attr_spec)
        elif kind == "relationship":
            rel_spec = spec.relationships.get(key)
            if rel_spec is not None:
                spec.RemoveProperty(rel_spec)
        elif kind == "active":
            spec.ClearInfo("active")
        touched_paths.add(prim_path)
    for prim_path in touched_paths:
        prune_empty_overrides(layer, prim_path)
    layer.Save()


def format_masking_override_error(
    variant_kind: str, masking: list[tuple[str, str]],
) -> str:
    """Render a masking-override conflict into a user-facing error message."""
    lines = [
        f"Cannot author this {variant_kind} variant: {len(masking)} "
        "per-instance scene opinion(s) would mask it. Per LIVRPS the "
        "variant body would be silently overridden at composition time. "
        "Conflicting (placement, opinion):",
    ]
    for prim_path, key in masking:
        lines.append(f"  {prim_path}.{key}")
    lines.append(
        "Retry with clear_masking_overrides=true to remove these scene "
        "opinions, OR with confirm_masked=true to author anyway (variant "
        "will only take effect on placements without prior overrides).",
    )
    return "\n".join(lines)


def _has_authored_opinion(
    spec: Sdf.PrimSpec, key: str, kind: OpinionKind,
) -> bool:
    """Whether *spec* has an authored opinion at *key* for the given *kind*."""
    if kind == "attribute":
        return key in spec.attributes
    if kind == "relationship":
        return key in spec.relationships
    if kind == "active":
        return spec.HasInfo("active")
    return False


# ── Scene-level variant authoring ──


def apply_scene_variant(
    stage: Usd.Stage,
    carrier_prim_path: str,
    variant_set: str,
    variant_name: str,
    author_fn: VariantAuthorFn,
    set_as_default: bool = False,
) -> None:
    """Author a scene-level variant on a carrier prim; preserve prior default unless overridden."""
    prior_selection = ""
    prim = stage.GetPrimAtPath(carrier_prim_path)
    if prim and prim.IsValid():
        vset = prim.GetVariantSets().GetVariantSet(variant_set)
        if vset.IsValid():
            prior_selection = vset.GetVariantSelection() or ""

    author_in_variant(
        stage, carrier_prim_path, variant_set, variant_name, author_fn,
    )

    prim = stage.GetPrimAtPath(carrier_prim_path)
    if not prim or not prim.IsValid():
        return
    if not prim.GetVariantSets().GetVariantSet(variant_set).IsValid():
        return

    if set_as_default:
        target = variant_name
    elif prior_selection:
        target = prior_selection
    else:
        target = variant_name
    set_scene_variant_default(
        stage, carrier_prim_path, variant_set, target,
    )


def set_scene_variant_default(
    stage: Usd.Stage,
    carrier_prim_path: str,
    set_name: str,
    variant_name: str,
) -> None:
    """Author a variant selection on a scene carrier prim."""
    prim = stage.GetPrimAtPath(carrier_prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Carrier prim not found: {carrier_prim_path}")
    vset = prim.GetVariantSets().GetVariantSet(set_name)
    if not vset.IsValid():
        raise ValueError(
            f"Variant set '{set_name}' not on {carrier_prim_path}",
        )
    vset.SetVariantSelection(variant_name)
    stage.Save()


def clear_scene_variant_default(
    stage: Usd.Stage, carrier_prim_path: str, set_name: str,
) -> None:
    """Clear the variant selection on a scene carrier prim."""
    layer = stage.GetRootLayer()
    prim_spec = layer.GetPrimAtPath(carrier_prim_path)
    if prim_spec is None:
        return
    if set_name in prim_spec.variantSelections:
        del prim_spec.variantSelections[set_name]
        layer.Save()


def find_masking_scene_opinions_direct(
    stage: Usd.Stage,
    target_map: dict[str, Iterable[str]],
    kind: OpinionKind,
) -> list[tuple[str, str]]:
    """Return direct scene opinions that would mask a scene-level variant body."""
    layer = stage.GetRootLayer()
    masking: list[tuple[str, str]] = []
    for scene_path, keys in target_map.items():
        spec = layer.GetPrimAtPath(scene_path)
        if spec is None:
            continue
        for key in keys:
            if _has_authored_opinion(spec, key, kind):
                masking.append((scene_path, key))
    return masking


def enforce_no_scene_masking_overrides(
    stage: Usd.Stage,
    target_map: dict[str, Iterable[str]],
    kind: OpinionKind,
    variant_kind: str,
    *,
    clear: bool,
    confirm: bool,
) -> bool:
    """Refuse / clear direct scene opinions that mask a scene-level variant body."""
    masking = find_masking_scene_opinions_direct(stage, target_map, kind)
    if not masking:
        return False
    if clear:
        clear_masking_scene_opinions(stage, masking, kind)
        return True
    if not confirm:
        raise ValueError(format_masking_override_error(variant_kind, masking))
    return False


def remove_scene_variant(
    stage: Usd.Stage,
    carrier_prim_path: str,
    set_name: str,
    variant_name: str,
) -> bool:
    """Remove one variant from a scene-level variant set on a carrier prim."""
    layer = stage.GetRootLayer()
    prim_spec = layer.GetPrimAtPath(carrier_prim_path)
    if prim_spec is None:
        return False
    vset_spec = prim_spec.variantSets.get(set_name)
    if vset_spec is None:
        return False
    existing = list(vset_spec.variants.keys())
    if variant_name not in existing:
        return False

    if len(existing) == 1:
        del prim_spec.variantSets[set_name]
        _scrub_variant_set_metadata(prim_spec, set_name)
        if set_name in prim_spec.variantSelections:
            del prim_spec.variantSelections[set_name]
        layer.Save()
        prune_empty_overrides(layer, carrier_prim_path)
        return True

    surviving = [v for v in existing if v != variant_name]
    temp_layer = Sdf.Layer.CreateAnonymous()
    for v in surviving:
        Sdf.CreateVariantInLayer(temp_layer, prim_spec.path, set_name, v)
        var_path = prim_spec.path.AppendVariantSelection(set_name, v)
        if layer.GetObjectAtPath(var_path) is not None:
            Sdf.CopySpec(layer, var_path, temp_layer, var_path)

    del prim_spec.variantSets[set_name]
    _scrub_variant_set_metadata(prim_spec, set_name)

    for v in surviving:
        Sdf.CreateVariantInLayer(layer, prim_spec.path, set_name, v)
        var_path = prim_spec.path.AppendVariantSelection(set_name, v)
        if temp_layer.GetObjectAtPath(var_path) is not None:
            Sdf.CopySpec(temp_layer, var_path, layer, var_path)

    if prim_spec.variantSelections.get(set_name) == variant_name:
        del prim_spec.variantSelections[set_name]

    layer.Save()
    return True


def remove_scene_variant_set(
    stage: Usd.Stage, carrier_prim_path: str, set_name: str,
) -> bool:
    """Remove an entire variant set from a scene carrier prim."""
    layer = stage.GetRootLayer()
    prim_spec = layer.GetPrimAtPath(carrier_prim_path)
    if prim_spec is None:
        return False
    if set_name not in prim_spec.variantSets:
        return False
    del prim_spec.variantSets[set_name]
    _scrub_variant_set_metadata(prim_spec, set_name)
    if set_name in prim_spec.variantSelections:
        del prim_spec.variantSelections[set_name]
    layer.Save()
    prune_empty_overrides(layer, carrier_prim_path)
    return True


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


# ── Suspect-set detection (selection variants that lost their multi-prim purpose) ──


def find_suspect_variant_sets(
    layer: Sdf.Layer, base_prim_path: str,
) -> list[tuple[str, str]]:
    """Walk ancestors of *base*; return (carrier, set) pairs for collapsed selection variants."""
    base = Sdf.Path(base_prim_path)
    if not base.IsAbsolutePath():
        return []

    suspect: list[tuple[str, str]] = []
    cursor = base
    while cursor != Sdf.Path.absoluteRootPath and cursor != Sdf.Path.emptyPath:
        spec = layer.GetPrimAtPath(cursor)
        if spec is not None:
            for vset_name in list(spec.variantSets.keys()):
                if _is_collapsed_selection_set(spec.variantSets[vset_name]):
                    suspect.append((str(cursor), vset_name))
        cursor = cursor.GetParentPath()
    return suspect


def _is_collapsed_selection_set(vset_spec: Sdf.VariantSetSpec) -> bool:
    """Whether a variant set has lost its purpose (single model left, or selection on one prim)."""
    if len(vset_spec.variants) == 0:
        return False
    if len(vset_spec.variants) == 1:
        only = next(iter(vset_spec.variants.values()))
        return _variant_body_authors_references(only)
    leaf_paths: set[str] = set()
    active_only = True
    for variant_name in list(vset_spec.variants.keys()):
        inner = vset_spec.variants[variant_name].primSpec
        if inner is None:
            continue
        for leaf_spec, rel_path in _walk_leaf_authorings(inner, ""):
            leaf_paths.add(rel_path)
            if not _is_active_only_spec(leaf_spec):
                active_only = False
    return active_only and len(leaf_paths) == 1


def restore_active_scene_variant_references_to_direct_ref(
    stage: Usd.Stage, carrier_prim_path: str, set_name: str,
) -> str | None:
    """If a scene model-selection set's variants author refs on one child, demote the active variant's refs back to a direct ref on that child."""
    layer = stage.GetRootLayer()
    carrier_spec = layer.GetPrimAtPath(carrier_prim_path)
    if carrier_spec is None or set_name not in carrier_spec.variantSets:
        return None
    vset_spec = carrier_spec.variantSets[set_name]
    if not vset_spec.variants:
        return None

    selection = carrier_spec.variantSelections.get(set_name)
    target_variant = (
        vset_spec.variants[selection]
        if selection and selection in vset_spec.variants
        else next(iter(vset_spec.variants.values()))
    )
    inner = target_variant.primSpec
    if inner is None or len(inner.nameChildren) != 1:
        return None
    child_name = next(iter(inner.nameChildren)).name
    child_spec = inner.nameChildren[child_name]
    if not child_spec.HasInfo("references"):
        return None

    refs: list[str] = []
    for items in (
        child_spec.referenceList.prependedItems,
        child_spec.referenceList.appendedItems,
        child_spec.referenceList.explicitItems,
    ):
        for r in items:
            if r.assetPath:
                refs.append(r.assetPath)
    if not refs:
        return None

    target_path = f"{carrier_prim_path}/{child_name}"
    target_prim = stage.GetPrimAtPath(target_path)
    if not target_prim or not target_prim.IsValid():
        return None
    for ref in refs:
        target_prim.GetReferences().AddReference(ref)
    stage.Save()
    return target_variant.name


def has_direct_references(stage: Usd.Stage, prim_path: str) -> bool:
    """Whether *prim_path* has any directly-authored reference arc in scene.usda."""
    layer = stage.GetRootLayer()
    spec = layer.GetPrimAtPath(prim_path)
    if spec is None:
        return False
    return spec.HasInfo("references")


def clear_direct_references(stage: Usd.Stage, prim_path: str) -> None:
    """Remove all directly-authored reference arcs at *prim_path* in scene.usda."""
    layer = stage.GetRootLayer()
    spec = layer.GetPrimAtPath(prim_path)
    if spec is None:
        return
    if spec.HasInfo("references"):
        spec.ClearInfo("references")
        layer.Save()


def _variant_body_authors_references(variant_spec: Sdf.VariantSpec) -> bool:
    """Whether a variant body authors any reference arcs (model_selection style)."""
    inner = variant_spec.primSpec
    if inner is None:
        return False
    stack = [inner]
    while stack:
        spec = stack.pop()
        if spec.HasInfo("references"):
            return True
        stack.extend(spec.nameChildren)
    return False


def _walk_leaf_authorings(spec: Sdf.PrimSpec, accum: str):
    """Yield (leaf_spec, rel_path) for descendants that author direct opinions."""
    has_opinions = (
        len(spec.attributes) > 0
        or len(spec.relationships) > 0
        or "active" in set(spec.ListInfoKeys())
    )
    if has_opinions and not len(spec.nameChildren):
        yield spec, accum
        return
    for child in spec.nameChildren:
        child_rel = f"{accum}/{child.name}" if accum else child.name
        yield from _walk_leaf_authorings(child, child_rel)


def _is_active_only_spec(spec: Sdf.PrimSpec) -> bool:
    """Whether *spec* authors ONLY the ``active`` metadata (no attrs, rels, or children)."""
    if len(spec.attributes) or len(spec.relationships) or len(spec.nameChildren):
        return False
    info = set(spec.ListInfoKeys()) - {"specifier", "typeName"}
    return info == {"active"}


def suspect_variant_sets_on_scene_carrier(
    stage: Usd.Stage, base_prim_path: str,
) -> list[dict]:
    """Return suspect scene-level variant sets walking ancestors of *base_prim_path*."""
    if stage is None or not base_prim_path or base_prim_path == "/":
        return []
    pairs = find_suspect_variant_sets(stage.GetRootLayer(), base_prim_path)
    return [
        {"carrier_prim_path": c, "variant_set": v, "scope": "scene"}
        for c, v in pairs
    ]


def suspect_variant_sets_in_asset(
    asset_dir: Path, base_prim_path: str | None = None,
) -> list[dict]:
    """Return suspect asset-level variant sets walking ancestors of *base_prim_path*."""
    variants_path = asset_dir / ASWFLayerNames.VARIANTS
    if not variants_path.exists():
        return []
    variants_layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if variants_layer is None:
        return []
    default_prim = resolve_default_prim_name(asset_dir)
    base = base_prim_path or f"/{default_prim}"
    pairs = find_suspect_variant_sets(variants_layer, base)
    return [
        {
            "asset_path": str(asset_dir), "variant_set": v,
            "scope": "asset", "carrier_prim_path": c,
        }
        for c, v in pairs
    ]


# ── Per-asset placement scrub ──


def clear_scene_variant_selections(
    stage: Usd.Stage,
    asset_dir: Path,
    set_name: str,
    variant_name: str | None = None,
) -> int:
    """Drop ``variantSelections[set_name]`` from every placement of the asset.

    When *variant_name* is given, only drop selections whose current value
    matches it. Prunes empty over ancestors left behind on each touched
    placement. Returns the number of placements scrubbed.
    """
    placements = find_asset_placements(stage, asset_dir)
    if not placements:
        return 0
    layer = stage.GetRootLayer()
    scrubbed = 0
    for placement in placements:
        spec = layer.GetPrimAtPath(placement)
        if spec is None:
            continue
        sels = spec.variantSelections
        if set_name not in sels:
            continue
        if variant_name is not None and sels[set_name] != variant_name:
            continue
        del sels[set_name]
        scrubbed += 1
        prune_empty_overrides(layer, placement)
    if scrubbed:
        layer.Save()
    return scrubbed


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


def get_variant_payload_refs(asset_dir: Path, set_name: str) -> dict[str, str]:
    """Read each variant's authored payload asset path from variants.usda."""
    variants_path = _variants_layer_path(asset_dir)
    if not variants_path.exists():
        return {}
    layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if layer is None:
        return {}
    default = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default}")
    if prim_spec is None:
        return {}
    vset_spec = prim_spec.variantSets.get(set_name)
    if vset_spec is None:
        return {}

    refs: dict[str, str] = {}
    for variant_name, variant_spec in vset_spec.variants.items():
        inner = variant_spec.primSpec
        if inner is None:
            continue
        plist = inner.payloadList
        for op in (plist.prependedItems, plist.appendedItems, plist.explicitItems):
            if op:
                refs[variant_name] = op[0].assetPath
                break
    return refs


# ── Internal helpers ──


def _scrub_variant_set_metadata(prim_spec: Sdf.PrimSpec, set_name: str) -> None:
    """Remove ``set_name`` from every variantSetNameList slot."""
    name_list = prim_spec.variantSetNameList
    for items in (
        name_list.prependedItems,
        name_list.appendedItems,
        name_list.addedItems,
        name_list.explicitItems,
        name_list.orderedItems,
    ):
        if set_name in items:
            items.remove(set_name)
    if set_name in name_list.deletedItems:
        name_list.deletedItems.remove(set_name)


def _all_variant_set_names_in_metadata(prim_spec: Sdf.PrimSpec) -> set[str]:
    """Union of every variantSetNames list-op slot."""
    name_list = prim_spec.variantSetNameList
    return (
        set(name_list.prependedItems)
        | set(name_list.appendedItems)
        | set(name_list.addedItems)
        | set(name_list.explicitItems)
        | set(name_list.orderedItems)
    )
