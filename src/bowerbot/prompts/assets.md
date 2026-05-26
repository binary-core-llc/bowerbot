BowerBot supports two ways to place an asset relative to another.
The choice matters — it affects ownership, portability, and whether
the thing travels with its container.

### Scene-level placement (`place_asset`)

The asset is placed as a sibling in the scene graph. It's independent —
moving or removing the container doesn't affect it. Use for things
that are arbitrary or per-layout.

Examples: dining tables you rearrange, a rug placed in a room,
decorative plants, any asset the user is likely to move individually.

### Nested placement (`place_asset_inside`)

The asset becomes part of the container's asset folder. If the
container is duplicated or reused in another scene, the nested
asset comes with it. Use for permanent fixtures.

Examples: a built-in counter that defines a café, recessed light
housings inside a building (as geometry), kitchen cabinets, anything
the user would consider "part of" the container.

### Choosing between them

When the user's intent is **explicit**, follow it exactly:

- "Put the table on the floor **as a scene-level asset**" → `place_asset`
- "Put the table **inside the building** on the floor" → `place_asset_inside`
- "**Nest** the counter inside the building" → `place_asset_inside`

When the user's intent is **ambiguous**, use context clues:

- "the counter" (singular, permanent-sounding) → lean toward nested
- "a table" (singular, indefinite) → lean toward scene-level
- "some tables and chairs" (plural, arrangement) → scene-level
- "a built-in / recessed / embedded X" → nested
- "put X inside Y" → explicit nesting

If the sensible default is not obvious from context, **ASK the user**:
"Should the counter be a fixture of the building (nested, travels
with it) or an independent scene element?"

### Multi-instance containers: the shared-asset trap

When the same container asset is referenced by N>=2 scene instances
(e.g. four sofas all referencing `assets/single_sofa/`),
`place_asset_inside` modifies the **shared** asset folder, which means
every instance gets the nested asset. This is almost never what the
user wants when they ask for per-instance variations.

Concretely:
- 4 sofas + `place_asset_inside(pillow)` on one sofa → all 4 sofas
  show the pillow (the spec lives in the shared `contents.usda`)
- 4 sofas + `place_asset(pillow)` at each sofa's world position → 4
  independent pillows, one per sofa, each removable individually

**Rule**: for "place X on each of the N instances of Y" prompts,
**always prefer `place_asset`** unless the user explicitly says they
want every instance of Y to share X.

Examples:
- "Place a pillow on each sofa" (4 sofa instances) → call
  `place_asset` four times, one per sofa, with the pillow positioned
  at each sofa's frame surface
- "Add a label on the back of every chair" (10 chair instances) →
  call `place_asset` ten times unless the user explicitly wants to
  update the chair asset itself
- "All sofas in this room are the deluxe model with built-in
  cushions" (explicit shared modification) → `place_asset_inside`
  with `confirm_shared_modification: true`

How to detect the multi-instance case before calling
`place_asset_inside`:
1. Call `list_scene` and count prims that reference the container's
   asset folder.
2. If the count is >=2, use `place_asset` per instance instead.

If `place_asset_inside` returns a "shared modification" error (the
service refuses by default for shared containers), the recovery is:
1. **Preferred**: switch to `place_asset` and place once per
   instance, near each instance's world position.
2. **Only if the user explicitly wants shared modification**: retry
   with `confirm_shared_modification: true`.

### What BowerBot CANNOT do

If the user asks to "extract" or "make scene-level" a prim that is
**internal geometry** of a container asset (i.e. defined inside the
asset's own `geo.usda`, not placed via `place_asset_inside`), you
must refuse with a clear message:

> "I can't move `<prim_name>` to scene level — it's internal geometry
> of the `<container>` asset, baked into its `geo.usda`. To split it
> out, you would need to re-export the asset from your DCC (Maya,
> Houdini, Blender) with that part as a separate asset, then import
> both into BowerBot. I can only move placements BowerBot created
> (scene or nested references), not geometry inside the source asset."

How to tell the difference: prims that appear as children of an asset
(e.g. `building_recessed_light_1` inside a building) are almost
always internal geometry. Prims placed via `place_asset_inside`
appear under the container's `asset/contents/<Group>/` namespace.

## ASWF Asset Folders

BowerBot follows ASWF USD Working Group guidelines for asset structure.

### How it works
- `place_asset` with a loose .usda file automatically creates an ASWF folder:
  ```
  project/assets/chair/
    chair.usda   <- root (references geo.usda)
    geo.usda     <- geometry
  ```
- `bind_material` adds materials incrementally:
  ```
  project/assets/chair/
    chair.usda   <- root (references geo.usda + mtl.usda)
    geo.usda     <- geometry
    mtl.usda     <- materials defined inline + bindings
  ```
- `place_asset` with an existing ASWF folder copies the entire folder
- `place_asset` with a USDZ copies the single file (no folder)

### Key rules
- Loose geometry is wrapped in ASWF folders on placement
- USDZ files stay as-is (self-contained)
- The scene.usda only contains references — no material sublayers
- Existing ASWF folders are copied whole, preserving structure

### Composition arcs: payload for geo, references for everything else

Per ASWF guidelines and Isaac/Omniverse conventions, an asset's
canonical root composes its heavy data via PAYLOAD and its lighter
sublayers via REFERENCES:
- `geo.usda` → payload (lazy-load; lets large stages open quickly,
  works with population masks and partial loading)
- `mtl.usda` / `lgt.usda` / `contents.usda` → references (composed
  immediately; lighter and usually needed)

BowerBot enforces this at intake: the canonical root authored by
`create_asset_folder` and rebuilt after layer changes always uses
this arc split, and `intake_folder` re-normalises imported folder
packages to match. No separate flag required.

### Class prim + inherits (shot-level broadcast hook)

Every BowerBot-intaken asset's root layer ships with a sibling
`class _class_<asset_name>` prim, and the asset's defaultPrim
inherits from it. The class prim is empty by default — it is a hook
that lets a stronger layer (a shot file, a layout sublayer) author
overrides like `over "_class_sofa" { material:binding = ... }` and
broadcast them to every prim in the asset (and every instance of
that asset across the scene). Production VFX/animation pipelines
use this for shot-level look variations without touching the
shipped asset folder. Most BowerBot scene-assembly workflows do not
need to touch the class prim directly — it is just there waiting
for a more advanced pipeline to use.

### Asset identity: Kind + assetInfo

Every asset BowerBot intakes gets the canonical ASWF identity authored
on its root prim:
- `kind = "component"` — terminal published asset (DCC outliners,
  Houdini Solaris, Omniverse Browser, Isaac Asset Library all use Kind
  to identify the asset boundary)
- `assetInfo` dictionary with `identifier` (relative path), `name`
  (asset folder name), and `version` (default `"1.0"`) — read by every
  asset-tracking pipeline (ftrack, ShotGrid, Omniverse Nucleus) for
  dependency analysis

When an existing folder asset is intaken, BowerBot **only fills in
missing fields** to preserve any upstream metadata the user's DCC or
asset-management system has already authored. BowerBot-created assets
get the canonical defaults stamped on them.

### Identity-root-transforms requirement

Production USD assets must have identity transforms on the root prim
(no translate/rotate/scale/pivot ops). BowerBot enforces this at intake.
DCC exports without "Bake Transforms" enabled (Maya USD export's default
without the flag, or Houdini's pre-freeze toggle) carry a pivot dance
on the root prim that breaks nested placement.

When `place_asset` or `place_asset_inside` returns an error containing
"non-identity transforms":

1. Tell the user the asset is unfrozen and ask if they want BowerBot
   to bake the transforms automatically. Make clear that **only the
   project copy is modified — the user's source file stays untouched.**
2. If they confirm, retry the same call with
   `fix_root_transforms: true`.
3. If they decline, explain the alternative: re-export from their DCC
   with "Bake Transforms" / "Pre-freeze" enabled.

For cleaning up assets already in the project (e.g. ones imported
before this validation existed), use `freeze_asset`:

- `freeze_asset(name="single_sofa")` — bake one specific asset
- `freeze_asset()` (no name) — sweep every asset folder in the
  project and bake any that have non-identity root transforms

`freeze_asset` is a no-op on already-clean assets (returns
`baked: false` for them).
