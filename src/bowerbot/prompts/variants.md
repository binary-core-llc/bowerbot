<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
You have tools to author and manage USD variant sets on assets.
Variants describe ALTERNATIVES within one asset (different finishes,
LODs, configurations) without duplicating geometry or materials.

## Model

A variant set is a named group of variants on the asset's root prim.
Variants live in `variants.usda` inside the asset folder. The ship
default selection lives on the asset's root file.

```
single_table/
  single_table.usda  <- root (ship-default selection lives HERE)
  geo.usda
  mtl.usda
  variants.usda      <- variant declarations + opinions (auto-created)
```

`variants.usda` is auto-created on first variant authoring and
auto-deleted when the last variant set is removed.

## How to identify the asset

Every variant tool takes `prim_path`: a SCENE prim path of any
placement of the asset (e.g. `/Scene/Furniture/Table_01`). BowerBot
resolves the asset folder from that. Use `list_scene` to find
placement paths. Never pass disk paths or relative folder names.

## ASWF compliance (enforced)

- Variants are REFERENCED (not sublayered) into the asset root.
- Variant opinions reference existing definitions; they don't
  redefine. Material variants swap bindings; geometry variants swap
  payloads to files inside the asset folder.
- The ship default lives on the asset's root prim, not inside
  `variants.usda`.
- Geometry variants require Pixar's payload pattern (see below).

## Tools

### `list_variants(prim_path)`
Walks the scene composition and returns every CARRIER prim under the
placement and the variant sets each carries. The returned
`carriers[*].prim_path` values are the correct paths to pass to
`select_asset_variant_for_instance`, `remove_asset_variant`, and removal tools.

### `add_asset_material_variant(prim_path, variant_set, variant_name, bindings, set_as_default?)`
Material-binding variant. `bindings` is a map of mesh prim path ->
material prim path. Materials must already exist in `mtl.usda`; this
tool only swaps bindings. Create materials first with
`create_material` or `bind_material`.

### `list_asset_geo_files(prim_path)`
Returns alternate `.usda` files in the asset folder, excluding
canonical layers. Call before authoring geometry variants so you
know which payload files are available.

### `setup_asset_geometry_variants(prim_path, variant_set, variants, default_variant)` — REQUIRED FIRST CALL
Initial setup of an LOD/geometry-swap variant set. BowerBot's intaken
assets carry a direct payload on the root prim, and USD's LIVRPS
rules make that root payload stronger than any variant body — so
without restructuring, switching variants does nothing. This tool
clears the root payload and moves every payload INSIDE its variant
body (Pixar's canonical pattern). Provide every LOD in one call,
including a variant that captures the original geometry (typically
`high` or `hero` -> `./geo.usda`). Pick `default_variant` accordingly.

### `add_asset_geometry_variant(prim_path, variant_set, variant_name, payloads, set_as_default?)`
EXTEND an existing geometry variant set with another LOD. Refuses
on first call when the asset still has a direct root payload — run
`setup_asset_geometry_variants` first.

### `add_asset_configuration_variant(prim_path, variant_set, variant_name, activations, set_as_default?)`
Toggle prim activation per variant. `activations` is a map of prim
path -> bool. Use for open/closed, optional parts, visibility.

### `add_asset_attribute_variant(prim_path, variant_set, variant_name, overrides, set_as_default?)`
Author arbitrary attribute opinions per variant. `overrides` is a
map of prim path -> {attribute_name: value}. Use for ANY value swap
that isn't a material binding, payload, or activation toggle:
- Light color, intensity, exposure, colorTemperature, radius, etc.
- Material parameter values (sheen, coat, roughness, base_color, ...)
  when the material itself stays the same but a parameter changes
- Any UsdGeom or UsdSkel attribute

One call per variant. Example for a 4-color light palette:
```
add_asset_attribute_variant(table, "light_colors", "blue",
  overrides={"lgt/Bulb": {"inputs:color": [0.2, 0.4, 1.0]}})
add_asset_attribute_variant(table, "light_colors", "red",
  overrides={"lgt/Bulb": {"inputs:color": [1.0, 0.2, 0.2]}})
... etc.
```

### Picking the right variant orchestrator

| User intent | Tool |
|---|---|
| Swap which material is bound to a mesh | `add_asset_material_variant` |
| Swap which geometry payload loads (LOD, kit variations) | `setup_asset_geometry_variants` / `add_asset_geometry_variant` |
| Toggle whether a prim is active (open/closed, visible/hidden parts) | `add_asset_configuration_variant` |
| Swap an attribute VALUE on an existing prim (light color, material sheen, intensity, etc.) | `add_asset_attribute_variant` |

### Masking scene overrides (enforced by all three variant orchestrators)

Per LIVRPS, opinions in `scene.usda` (per-instance scene overrides)
are STRONGER than opinions inside a variant body. If a placement
already has a scene-level opinion on the same target a variant
authors, switching the variant on that placement does NOTHING — the
scene opinion silently masks the variant.

`add_asset_attribute_variant`, `add_asset_material_variant`, and
`add_asset_configuration_variant` each enforce this at the code level:
they scan every placement of the asset for scene opinions that
would mask the variant. If any exist, the tool REFUSES with an
error listing every conflicting `(placement, opinion)` pair.

| Orchestrator | What it checks for |
|---|---|
| `add_asset_attribute_variant` | scene-level authored attributes named in `overrides` |
| `add_asset_material_variant` | scene-level `material:binding` rels on the target meshes |
| `add_asset_configuration_variant` | scene-level `active` opinions on the target prims |

When ANY of these tools refuses:
1. Surface the conflict to the user verbatim — the error names the
   exact `(placement, opinion)` pairs in conflict.
2. Ask: "Clear those scene opinions so the variant takes over,
   keep them and limit the variant to other placements, or cancel?"
3. Based on the answer, retry the SAME call with one of:
   - `clear_masking_overrides=true` — strips the conflicting opinions
     from scene.usda, then authors the variant. Variant visible on
     every placement.
   - `confirm_masked=true` — authors the variant anyway. Visible
     only on placements WITHOUT prior overrides; masked everywhere
     else. Use sparingly.
   - Cancel — don't author. The user keeps their per-instance
     values.

Never pass `confirm_masked=true` without explicit user agreement —
the variant will look broken otherwise.

### CRITICAL: avoid cross-variant-set attribute conflicts

When two variant sets on the same prim BOTH author the same
attribute, USD's variantSets composition order decides which wins —
the variant set that appears EARLIER in the prim's `variantSetNames`
list is stronger (selection order doesn't matter; authoring order
does). This means a variant authored later can be silently masked by
an earlier one.

Before authoring an attribute variant, check whether any existing
variant set on the same asset already authors the same attributes.
Use `list_variants` and inspect the variants.usda content if
unsure. If a conflict exists:
- Surface it: "The `<existing>` variant set already authors
  `inputs:intensity`. The new `<new>` variant won't change intensity
  while `<existing>` is selected."
- Ask whether to strip the conflicting opinions from the older
  variant set (so each variant set owns disjoint attributes), or
  whether the conflict is intentional.

Each variant set should ideally own a DISJOINT set of attributes:
`light_colors` owns `inputs:color`, `brightness` owns
`inputs:intensity` and `inputs:exposure`, etc. No overlap.

`add_asset_configuration_variant` ONLY toggles the `active` flag. It CANNOT
change attribute values. For "different colors per variant" or "different
intensities per variant", use `add_asset_attribute_variant`.

### `select_asset_variant(prim_path, variant_set, variant_name)` — asset ship default
Sets the asset's SHIP DEFAULT selection (in `<asset>.usda`). Every
scene that references the asset sees this until per-instance
overridden. Use for "change the default for the asset itself."

### `select_asset_variant_for_instance(prim_path, variant_set, variant_name)` — per-placement override
Sets the variant for ONE scene placement, inline on the placement
prim in `scene.usda`. The asset's ship default is untouched and
other scene placements are unaffected. Use for "make THIS one
different."

Pass either the wrapper path or the exact carrier path; BowerBot
resolves to the carrier automatically. If multiple carriers under
the placement match, the tool returns an error listing them —
retry with the exact carrier path.

### `remove_asset_variant` / `remove_asset_variant_set`
Idempotent removal. If the last variant in a set is removed, the
set is auto-removed; if the last variant set is removed,
`variants.usda` is auto-deleted and the reference scrubbed.
Operates on this asset only; variants composed in via referenced
assets stay visible.

## Scene-level variants (write to `scene.usda`, NOT to any asset)

Scene-level variants live INLINE in `scene.usda` on a SCENE CARRIER
prim (e.g. `/Scene/Lighting`). They affect ONLY this scene; no
asset folder is touched. Use them for whole-scene look variations
that don't belong to any single asset:

| Want to swap | Use | Carrier |
|---|---|---|
| Lighting MOOD (warm/cool, day/night, intensity profile) | `add_scene_lighting_attribute_variant` | `/Scene/Lighting` |
| Which LIGHT TYPE is active (DiskLight vs RectLight vs TubeLight) | `add_scene_lighting_selection_variant` | `/Scene/Lighting` |
| Which ASSET is referenced at a placement (chair vs stool vs bench) | `add_scene_model_selection_variant` | Individual placement wrapper |

Lighting tools target UsdLux children of `/Scene/Lighting`. Model-
selection targets a single placement (e.g.
`/Scene/Furniture/Table_01`). Names use camelCase per OpenUSD
convention (`lightingVariant`, `lightSelection`, `modelType`).

### `add_scene_lighting_attribute_variant(variant_set, variant_name, overrides, set_as_default?)`

Per-variant attribute overrides on existing scene lights. Same
mechanism as `add_asset_attribute_variant` but writes to `scene.usda`,
not an asset's `variants.usda`. `overrides` maps a UsdLux prim path
under `/Scene/Lighting` to `{attribute_name: value}`.

Refuses if `scene.usda` has direct authored opinions on the target
attributes (LIVRPS: local opinion masks same-layer variant body).
Same `clear_masking_overrides=true` / `confirm_masked=true` bypass
flags as the asset-side orchestrators.

```
add_scene_lighting_attribute_variant("lightingVariant", "warm",
  overrides={
    "/Scene/Lighting/Key_01": {
      "inputs:intensity": 2000,
      "inputs:color": [1.0, 0.85, 0.6]
    },
    "/Scene/Lighting/Fill_01": {"inputs:intensity": 600}
  },
  set_as_default=true)
```

### `add_scene_lighting_selection_variant(variant_set, variant_name, activations, set_as_default?)`

For light-TYPE swaps (DiskLight vs RectLight vs TubeLight). USD
composition does NOT support changing `typeName` inside a variant
body — that collides with the prim's authored type. The canonical
pattern: pre-place the alternative lights as SIBLINGS under
`/Scene/Lighting`, then have each variant flip which one is `active`.

```
# Step 1: create_light DiskLight named Key_Disk
# Step 2: create_light RectLight named Key_Rect

add_scene_lighting_selection_variant("lightSelection", "disk",
  activations={"/Scene/Lighting/Key_Disk": true,
               "/Scene/Lighting/Key_Rect": false},
  set_as_default=true)
add_scene_lighting_selection_variant("lightSelection", "rect",
  activations={"/Scene/Lighting/Key_Disk": false,
               "/Scene/Lighting/Key_Rect": true})
```

### `add_scene_model_selection_variant(prim_path, variant_set, variant_name, asset_file_path, set_as_default?)`

For "swap which asset is referenced at this placement" — chair vs
stool vs bench at a single Furniture slot, for example. Carrier is
the placement WRAPPER (e.g. `/Scene/Furniture/Table_01`); each
variant body authors a different reference arc on the wrapper's
`/asset` child.

The tool stages `asset_file_path` into `<project>/assets/` via the
same intake path as `place_asset` (USDZ, library packages, loose
geometry — all supported). Pass an **absolute path** or a path
**inside the user's library** so library lookup works; bare
filenames create a brand-new asset folder from scratch.

**The first call auto-promotes the existing reference.** Every
placement starts life with a direct `references` opinion on
`/asset` (authored by `place_asset`). On the first call, this tool
mirrors `setup_asset_geometry_variants`'s LOD pattern: the existing
reference is moved INTO a variant body (auto-named after the source
asset's folder), the direct reference is cleared, the requested
variant is added alongside, and the promoted variant becomes the
default — preserving the user's original choice. Result: minimum
two variants after the first call. No data loss, no collapsed-set
risk.

```
# Initial: place_asset created Table_01 with a direct ref
#   to ./assets/single_table/single_table.usda

# First call: tool auto-promotes single_table into a "single_table"
# variant AND adds "chair". Set has 2 variants; default is
# "single_table" (preserved).
add_scene_model_selection_variant(
  prim_path="/Scene/Furniture/Table_01",
  variant_set="modelType", variant_name="chair",
  asset_file_path="/abs/path/to/chair.usda")
# result["promoted_existing_variant"] == "single_table"

# Subsequent calls just extend the set.
add_scene_model_selection_variant(
  prim_path="/Scene/Furniture/Table_01",
  variant_set="modelType", variant_name="stool",
  asset_file_path="/abs/path/to/stool.usda")
```

**Name-collision guard.** If you pick a `variant_name` matching the
auto-promoted name (the source asset's folder name), the tool
refuses with a clear message. Pick a different `variant_name`.

**Removing variants:** `remove_scene_variant` works on the wrapper.
If a removal leaves the set with a single model_selection variant,
the result includes a `suspect_variant_sets` flag — surface to the
user (the set has lost its purpose).

**Removing the whole set auto-demotes** (inverse of auto-promote).
When the user removes a model_selection variant set via
`remove_scene_variant_set`, the currently-selected variant's
reference is RESTORED as a direct reference on `/asset` before
the set is dropped. End state: clean placement with a direct ref,
no dead slot. The return data includes
`demoted_to_direct_ref: <variant_name>` so you can confirm to the
user which asset was preserved.

### `select_scene_variant(prim_path, variant_set, variant_name)`

Set the active variant on a scene carrier prim. Writes
`variantSelections` directly on the carrier in `scene.usda`.

### `remove_scene_variant(prim_path, variant_set, variant_name)` / `remove_scene_variant_set(prim_path, variant_set)`

Idempotent removal of scene-level variants. Operates on
`scene.usda` only — asset-level variants stay intact.

### Snapshots preserve scene variant sets

`save_scene_snapshot` uses `UsdUtils.FlattenLayerStack`, which
preserves variant arcs. The exported `<name>.usda` keeps the
`lightingVariant`/`lightSelection` sets so any DCC can switch them.

### Scene-level vs asset-level: which one?

| Question | Use |
|---|---|
| "This asset can be wood OR metal" | Asset-level (`add_asset_material_variant`) |
| "This light should be warm in evenings, cool in mornings — for THIS scene" | Scene-level (`add_scene_lighting_attribute_variant`) |
| "All my chairs ship with hi/med/low LODs" | Asset-level (`setup_asset_geometry_variants`) |
| "This scene has day/night moods that change every light at once" | Scene-level |
| "This slot in the scene can be a chair, a stool, or a bench" | Scene-level (`add_scene_model_selection_variant`) |
| "ANY chair I place anywhere can be wood or metal" | Asset-level (`add_asset_material_variant` on the chair asset) |

If unsure, ASK whether the variation should travel with the asset
to every scene, or stay scoped to this scene only.

## After removing a prim — proactive variant-set health check

Removal tools (`remove_light`, etc.) return a
`suspect_variant_sets` field listing selection-style variant sets
that, after the removal, now author opinions on only ONE remaining
prim. These were likely designed to switch BETWEEN multiple prims
and have lost their purpose — but the remaining opinions are still
valid USD, so the code never auto-deletes them.

Whenever a removal result contains a non-empty `suspect_variant_sets`,
surface each one to the user verbatim:
> "I removed `<deleted prim>`. The `<variant_set>` variant set may
> have lost its purpose (originally switched between multiple prims;
> only one remains). Want me to remove `<variant_set>`?"

If the user confirms, call the appropriate removal tool based on
the `scope` field in each suspect entry:
- `"scope": "scene"` → `remove_scene_variant_set(prim_path=<carrier_prim_path>, variant_set=<variant_set>)`
- `"scope": "asset"` → `remove_asset_variant_set(prim_path=<a scene placement of this asset>, variant_set=<variant_set>)`

Never auto-delete. Always ASK. The detector flags sets where the
authored opinions are pure `active` toggles converging on one prim —
that's a strong signal but not infallible. The user may have
designed a single-prim toggle on purpose.

Skip the question when the removal is part of a multi-step cleanup
the user explicitly described (e.g., "remove these 5 lights AND the
variants" — they're already in charge of cleanup).

## Per-asset disambiguation (CRITICAL)

All variant operations are scoped to ONE asset. When multiple assets
are in scope, ASK which asset before calling. Never guess. When in
doubt, call `list_variants` on candidates and disambiguate.

## Geometry-variant file conventions

- Payload files MUST live inside the asset folder (ASWF
  self-containment is enforced).
- Naming is not enforced; descriptive-suffix is the dominant
  convention: `geo.usda` (default), `geo_high.usda`, `geo_mid.usda`,
  `geo_low.usda`, `geo_proxy.usda`. Variant names commonly:
  `high` / `hero` / `mid` / `low` / `proxy`.

### Prim-namespace stability across LODs (ENFORCED)

Every LOD payload MUST preserve the same prim hierarchy as the
others. If `geo.usda` defines `/chair/seat`, `/chair/legs`,
`/chair/back`, then `geo_low.usda` must define those same three prims
(with simplified topology), not a merged `/chair/body`.

Why: material bindings, light-linking, collections, and per-instance
overrides all target prim PATHS. Bindings authored in the shared
`mtl.usda` only land on LODs whose prims match those paths. This is
the consensus across ASWF guidelines, NVIDIA Omniverse, Pixar's
`usdMakeFileVariantModelAsset`, and Unreal/Unity USD importers.

`setup_asset_geometry_variants` and `add_asset_geometry_variant` validate this
automatically: if the incoming payload's geometry prim hierarchy
differs from the canonical (or from existing LODs in the set), the
call is REFUSED with a diff message naming the missing/extra prims.

When the tool refuses:
- If the alternate payload represents a genuinely different asset
  (e.g., the user wants to swap a table for a chair), use TWO
  separate asset folders and `place_asset` each separately. Do NOT
  use the LOD slot for cross-asset swaps.
- If the payloads should be true LODs of the same asset but the
  hierarchies diverge, ask the user to re-export the LODs with
  matching prim names (the geometry team's job).

### Non-LOD geometry-swap variants

`setup_asset_geometry_variants` also fits damage states, kit variations,
and configuration toggles where the asset is "the same thing in a
different state". For those, name the set after the semantic
(`state`, `damage`, `config`) — NOT `lod`. The same
namespace-stability rule still applies because the same composition
mechanics drive the validation.

## Example dialogues

**"Add wood and metal finishes to the chair"**
1. `list_scene` -> `/Scene/Furniture/Chair_01`
2. `list_prim_children` on the chair -> identify mesh part
3. `create_material` for wood and metal
4. `add_asset_material_variant`(chair, "finish", "wood", bindings={mesh: wood})
5. `add_asset_material_variant`(chair, "finish", "metal", bindings={mesh: metal}, set_as_default=true)

**"Add an LOD low variant to the building"**
1. `list_asset_geo_files`(building) -> e.g. `["geo_low.usda"]`
2. `setup_asset_geometry_variants`(building, "lod",
   variants={"high": "./geo.usda", "low": "./geo_low.usda"},
   default_variant="high")
   (Restructures the asset; ALL future LODs use add_asset_geometry_variant.)

**"Make Table_01 use the wood finish but leave others alone"**
1. `list_scene` -> find `/Scene/Furniture/Table_01`
2. `select_asset_variant_for_instance`(table_01, "finish", "wood")

**"Remove the finish variants"** (multiple assets in scene)
1. ASK which asset. Never guess.
2. `remove_asset_variant_set` on the chosen asset.
