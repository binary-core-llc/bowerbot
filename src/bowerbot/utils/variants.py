# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Variant authoring for BowerBot's variant tools and assets' variants.usda.

The universal variant-set operations live in ``usd.variant_sets``
(``usd.variant_sets.author_in_variant`` and friends), and an asset's
variants.usda (reading it, default selections, removal) in
``authoring.asset_variants``. Services layer the category orchestrators on top.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from pxr import Sdf
from pxr import Usd
from pxr import UsdLux

from bowerbot import constants
from bowerbot import schemas
from bowerbot import utils
from bowerbot.utils import authoring
from bowerbot.utils import usd

# ── Universal authoring primitive ──


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
    usd.naming.validate_variant_name(variant_set, "variant set")
    for name in variants:
        usd.naming.validate_variant_name(name)
    for payload_ref in variants.values():
        validate_payload_path(asset_dir, payload_ref)
    validate_lod_namespace_stability(asset_dir, variants)

    authoring.asset_folder.ensure_variants_layer(asset_dir)
    authoring.asset_folder.ensure_variants_referenced(asset_dir)
    stage = authoring.asset_variants.open_variants_stage(asset_dir)
    root_prim_path = f"/{authoring.asset_folder.resolve_default_prim_name(asset_dir)}"

    for variant_name, payload_ref in variants.items():
        usd.variant_sets.author_in_variant(
            stage, root_prim_path, variant_set, variant_name,
            _payload_setter(payload_ref),
        )

    authoring.asset_folder.clear_root_payload(asset_dir)
    authoring.asset_variants.set_default_variant(asset_dir, variant_set, default_variant)


def _payload_setter(payload_ref: str) -> Callable[[Usd.Stage, str], None]:
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
    author_fn: Callable[[Usd.Stage, str], None],
    set_as_default: bool = False,
) -> None:
    """End-to-end variant authoring: layer, reference, opinions, default selection."""
    authoring.asset_folder.ensure_variants_layer(asset_dir)
    authoring.asset_folder.ensure_variants_referenced(asset_dir)
    stage = authoring.asset_variants.open_variants_stage(asset_dir)
    usd.variant_sets.author_in_variant(
        stage, f"/{authoring.asset_folder.resolve_default_prim_name(asset_dir)}",
        variant_set, variant_name, author_fn,
    )

    summary = authoring.asset_variants.get_variant_summary(asset_dir)
    existing = next(
        (s for s in summary.variant_sets if s.name == variant_set), None,
    )
    needs_default = set_as_default or (existing is not None and not existing.selection)
    if needs_default:
        authoring.asset_variants.set_default_variant(asset_dir, variant_set, variant_name)


# ── Removal ──


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


# ── Naming ──


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


def find_masking_scene_opinions(
    stage: Usd.Stage,
    asset_dir: Path,
    default_prim: str,
    target_map: dict[str, Iterable[str]],
    kind: schemas.OpinionKind,
) -> list[tuple[str, str]]:
    """Return (scene_prim_path, key) pairs in scene.usda that would mask a variant body opinion.

    *target_map* maps asset-local prim path -> iterable of keys the variant
    is about to author at that path. *kind* names which spec slot to inspect:
    ``"attribute"`` (key is attribute name), ``"relationship"`` (key is
    relationship name, typically ``"material:binding"``), or ``"active"``
    (key is always ``"active"`` — the prim's active metadata).
    """
    placements = utils.stage.find_asset_placements(stage, asset_dir)
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
    kind: schemas.OpinionKind,
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
    kind: schemas.OpinionKind,
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
        usd.namespace.prune_empty_overrides(layer, prim_path)
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
    spec: Sdf.PrimSpec, key: str, kind: schemas.OpinionKind,
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
    author_fn: Callable[[Usd.Stage, str], None],
    set_as_default: bool = False,
) -> None:
    """Author a scene-level variant on a carrier prim; preserve prior default unless overridden."""
    prior_selection = ""
    prim = stage.GetPrimAtPath(carrier_prim_path)
    if prim and prim.IsValid():
        vset = prim.GetVariantSets().GetVariantSet(variant_set)
        if vset.IsValid():
            prior_selection = vset.GetVariantSelection() or ""

    usd.variant_sets.author_in_variant(
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
    usd.variant_sets.set_scene_variant_default(
        stage, carrier_prim_path, variant_set, target,
    )


def find_masking_scene_opinions_direct(
    stage: Usd.Stage,
    target_map: dict[str, Iterable[str]],
    kind: schemas.OpinionKind,
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
    kind: schemas.OpinionKind,
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


def require_scene_lighting_carrier(stage: Usd.Stage) -> str:
    """Return the lighting carrier path or raise if it does not exist yet."""
    if stage is None:
        raise ValueError("No scene stage is open.")
    carrier = constants.SceneNamespace.LIGHTING
    prim = stage.GetPrimAtPath(carrier)
    if not prim or not prim.IsValid():
        raise ValueError(
            f"No lighting carrier at {carrier}. Create at least one scene "
            "light before authoring a lighting variant.",
        )
    return carrier


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
    """Demote a model-selection set's active variant refs back to a direct ref on its child."""
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
    variants_path = asset_dir / constants.ASWFLayerNames.VARIANTS
    if not variants_path.exists():
        return []
    variants_layer = Sdf.Layer.FindOrOpen(str(variants_path))
    if variants_layer is None:
        return []
    default_prim = authoring.asset_folder.resolve_default_prim_name(asset_dir)
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
    placements = utils.stage.find_asset_placements(stage, asset_dir)
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
        usd.namespace.prune_empty_overrides(layer, placement)
    if scrubbed:
        layer.Save()
    return scrubbed


def resolve_attribute_types_for_overrides(
    asset_dir: Path,
    overrides: dict[str, dict[str, object]],
) -> dict[str, dict[str, Sdf.ValueTypeName | None]]:
    """Look up each override attribute's declared type from the asset's composed stage."""
    out: dict[str, dict[str, Sdf.ValueTypeName | None]] = {}
    root_file = authoring.asset_folder.find_root_file(asset_dir)
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


def refuse_unknown_asset_attributes(
    asset_dir: Path,
    resolved_types: dict[str, dict[str, Sdf.ValueTypeName | None]],
) -> None:
    """Refuse override attributes that do not exist on the asset's composed prims."""
    root_file = authoring.asset_folder.find_root_file(asset_dir)
    stage = Usd.Stage.Open(str(root_file)) if root_file is not None else None
    usd.attributes.refuse_unknown_attributes(stage, resolved_types)
