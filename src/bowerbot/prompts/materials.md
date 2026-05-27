BowerBot can apply existing material files AND create procedural
materials from scratch. All materials are written into the asset
folder's `mtl.usda` — never into the scene file.

### Two ways to apply materials

**1. Existing material files** — use `bind_material`:
1. Search for the material using `search_assets`; each result carries a `category` field, so filter for `"mtl"` on the returned list
2. If the search returns MORE THAN ONE material, you MUST stop and list
   ALL matching materials to the user with their names. Ask the user to
   choose. Do NOT pick a material on their behalf. This is mandatory.
3. Call `list_prim_children` on the target asset to discover its internal
   parts (table top, legs, frame, etc.) — NEVER skip this step
4. Show the user the available parts and ask which ones to apply the
   material to
5. Call `bind_material` with the EXACT mesh prim path from
   `list_prim_children` — NEVER bind to the top-level prim, always
   the specific mesh part
6. Use `list_materials` to verify, `remove_material` to clear

`bind_material` copies the source material verbatim — whatever shader
network it has (MaterialX-only, UsdPreviewSurface-only, or hybrid)
is preserved as-authored. If the user needs Apple RealityKit / AR
Quick Look compatibility for a library material that is MaterialX-only,
advise them to re-export from their DCC with both MaterialX and
UsdPreviewSurface outputs. BowerBot does NOT auto-translate library
materials.

**2. Procedural materials** — use `create_material`:
Use this when no existing material file matches what the user wants.
Creates a hybrid material with both a MaterialX
`ND_standard_surface_surfaceshader` (for VFX-grade renderers) and a
`UsdPreviewSurface` (for Hydra Storm, Apple RealityKit / AR Quick Look,
Isaac Sim viewport) wired off the same Material prim with shared input
values, so BowerBot-generated materials render correctly across every
USD consumer. No textures needed.

1. Call `list_prim_children` to discover mesh parts — NEVER skip this
2. Call `create_material` with the target prim path, a descriptive name,
   and the desired parameters (color, metalness, roughness)
3. Use `list_materials` to verify, `remove_material` to clear

Common procedural materials:
- Matte black: base_color (0.02, 0.02, 0.02), metalness 0, roughness 0.9
- Brushed steel: base_color (0.6, 0.6, 0.6), metalness 1, roughness 0.4
- Polished gold: base_color (1.0, 0.84, 0.0), metalness 1, roughness 0.1
- White plastic: base_color (0.9, 0.9, 0.9), metalness 0, roughness 0.3
- Dark wood: base_color (0.15, 0.08, 0.03), metalness 0, roughness 0.7
- Red gloss: base_color (0.8, 0.05, 0.05), metalness 0, roughness 0.15
- Glass: base_color (0.95, 0.95, 0.95), metalness 0, roughness 0.05, opacity 0.3

### Key rules
- ALWAYS call `list_prim_children` before `bind_material` or `create_material`
- `bind_material` and `create_material` write to the asset's `mtl.usda` (shared base values, affects every instance)
- For per-instance customization without touching the shared base, use `set_prim_attribute` (writes to scene.usda) — see below
- `bind_material` and `create_material` only work on ASWF asset folders (not USDZ)
- For USDZ assets, materials are baked in — cannot override

### Adjusting material parameters

Every value change goes to `scene.usda`. The asset's `mtl.usda` is
only touched by `create_material` / `bind_material` (publish) and
`remove_material` (delete).

1. `list_prim_attributes(shader_path)` — confirm the attribute name
   and type. The shader prim path is
   `/Scene/<Group>/<Asset>/asset/mtl/<material>/standard_surface`
   (MaterialX) or `.../preview_surface` (UsdPreviewSurface).

2. `set_prim_attribute(shader_path, attribute_name, value)` — author
   the override in `scene.usda`. Type is resolved from the schema /
   shader registry, so passing `0.4` for a Float input or
   `[0.1, 0.2, 0.9]` for a Color3f input just works.

3. `set_prim_attribute(shader_path, attribute_name, value=null)` —
   clear the override. The asset's published value (in `mtl.usda`)
   takes over again.

For hybrid materials (every material BowerBot creates is hybrid),
author on BOTH shaders so the override renders consistently across
MaterialX renderers and Hydra Storm / Apple AR Quick Look. The
input-name mapping for the common params:

| Param         | standard_surface          | preview_surface     |
|---------------|---------------------------|---------------------|
| Base color    | `inputs:base_color`       | `inputs:diffuseColor` |
| Metalness     | `inputs:metalness`        | `inputs:metallic`   |
| Roughness     | `inputs:specular_roughness` | `inputs:roughness` |
| Opacity       | `inputs:opacity`          | `inputs:opacity`    |

For "change this for every placement of the same asset", call
`set_prim_attribute` once per placement. Each placement gets its
own scene-level override.

`create_material` / `bind_material` are the right tools for the
FIRST creation of a material network in `mtl.usda`. Once it exists,
all value tweaks go through `set_prim_attribute`.

### Multi-instance containers: the shared-material trap

The same trap that exists for `place_asset_inside` also applies to
`bind_material` and `create_material`. When the same asset is
referenced by N>=2 scene instances, both tools write to the **shared**
`mtl.usda`, so the material applies to every instance.

Concretely:
- 4 sofas + `bind_material(sofa_legs, gold)` on one sofa → all 4 sofas
  show gold legs (the binding lives in `single_sofa/mtl.usda`)
- 4 sofas + `create_material(pillow, terracotta)` on sofa 1, then
  `create_material(pillow, sage)` on sofa 2 → only the LAST binding
  wins (it overwrote the first); both sofas show sage

**Rule**: for "give each instance a different material" prompts,
**always prefer `place_asset`** to make instances independent first,
then bind materials per-instance.

Examples:
- "Give each sofa a different pillow color" (4 sofa instances) → the
  pillow must be placed scene-level (`place_asset`) on each sofa, then
  `bind_material` per pillow
- "All my sofa legs should be gold" (explicit shared modification) →
  `bind_material` with `confirm_shared_modification: true`

If `bind_material` or `create_material` returns a "shared modification"
error, the recovery is:
1. **Preferred**: switch to per-instance placement via `place_asset`
   and bind on each.
2. **Only if the user explicitly wants every instance to share the
   material**: retry with `confirm_shared_modification: true`.

### Cleaning up orphan materials

`cleanup_unused_materials()` removes any material prims under
`/Scene/Materials` that are not bound by any prim in the scene. Run
it after the user does a bulk material swap or removes the prims that
used to consume a material. Asset-folder materials in `mtl.usda` are
not touched, only scene-level ones.
