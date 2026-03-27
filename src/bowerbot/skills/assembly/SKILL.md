<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
# Assembly Skill

You have tools to create and manipulate OpenUSD scenes.

## Workflow
1. ALWAYS call `create_stage` first before placing any assets
2. Place assets using `place_asset` with coordinates in meters
3. Use `move_asset` to reposition an existing object (do NOT call
   `place_asset` again — that creates a duplicate)
4. Use `compute_grid_layout` to plan evenly spaced arrangements
5. Use `list_scene` to show the user what's currently in the scene
6. Use `rename_prim` or `remove_prim` when the user wants to reorganize
7. ALWAYS call `validate_scene` before packaging
8. Call `package_scene` to produce the final .usdz

## USD Rules
- metersPerUnit = 1.0 (always, no exceptions)
- upAxis = "Y"
- Assets are added as USD references (not copies)
- Every stage has a defaultPrim set automatically

## Scene Hierarchy
Default groups: /Scene/Architecture, /Scene/Furniture, /Scene/Products, /Scene/Lighting, /Scene/Props
The user may request a custom hierarchy — use `rename_prim` to reorganize after placement.

## Spatial Reasoning
- Tables, chairs, shelves → floor (Y = 0)
- Ceiling lights, pendants → ceiling (Y = room height, typically 2.7)
- Wall-mounted items → against walls with 0.01m offset
- Maintain minimum 1.2m walkways between furniture groups

### Placing objects on surfaces
Do NOT guess surface heights or positions. ALWAYS call `list_scene`
first and use the `bounds` of the support object:
- `translate_y` = support `bounds.max.y` (surface height)
- `translate_x` must be between support `bounds.min.x` and
  `bounds.max.x` (stay within the surface)
- `translate_z` must be between support `bounds.min.z` and
  `bounds.max.z` (stay within the surface)

When arranging multiple objects on the same surface, also check
each object's own bounds to ensure they do not overlap or hang
off the edge.

## Lighting

Use `create_light` to add native USD lights when the user asks for lighting.
These are real lights that renderers understand (shadows, exposure, color).
Only add lights when explicitly requested.

### Light types
- **DistantLight** — sun/directional. Position doesn't matter, only rotation.
  Use `rotate_x` to control sun angle (e.g., -45 for afternoon). Set `angle: 0.53` for realistic sun disk.
- **DomeLight** — environment/HDRI. Set `texture` to an HDRI file path. Intensity typically 1.0.
- **SphereLight** — point/omni. Good for lamps, bulbs. Radius 0.05-0.1.
- **RectLight** — rectangular area. Good for ceiling panels, windows. Width/height 0.5-2.0.
- **DiskLight** — circular area. Good for recessed downlights. Radius 0.1-0.3.
- **CylinderLight** — tube. Good for fluorescent fixtures. Radius 0.02, length 1.2.

### Defaults
- Intensity: 1000 for interior lights, 500 for DistantLight, 1.0 for DomeLight
- Color: warm white = (1.0, 0.9, 0.8), cool white = (0.9, 0.95, 1.0), daylight = (1.0, 1.0, 1.0)
- Lights always go in `/Scene/Lighting`

## Materials

BowerBot applies existing material files — it does NOT create materials.
Material files are `.usda` files with material definitions under `/mtl/`.

Materials are written into the asset folder's `mtl.usd`, NOT the scene file.
The scene stays clean — only references to asset folders.

### Material binding workflow (CRITICAL)
1. Search for the material using `search_assets` with category "mtl"
2. If the search returns MORE THAN ONE material, you MUST stop and list
   ALL matching materials to the user with their names. Ask the user to
   choose. Do NOT pick a material on their behalf. This is mandatory.
3. Call `list_prim_children` on the target asset to discover its internal parts
   (table top, legs, frame, etc.) — NEVER skip this step
4. Show the user the available parts and ask which ones to apply the material to
5. Call `bind_material` with the EXACT mesh prim path from `list_prim_children`
   — NEVER bind to the top-level prim, always the specific mesh part
6. Use `list_materials` to verify, `remove_material` to clear

### Key rules
- ALWAYS call `list_prim_children` before `bind_material`
- Materials go into the asset folder's mtl.usd — never into scene.usda
- BowerBot does NOT create materials — only applies existing ones
- `bind_material` only works on ASWF asset folders (not USDZ)
- For USDZ assets, materials are baked in — cannot override

## ASWF Asset Folders

BowerBot follows ASWF USD Working Group guidelines for asset structure.

### How it works
- `place_asset` with a loose .usda file automatically creates an ASWF folder:
  ```
  project/assets/chair/
    chair.usd    <- root (sublayers geo.usd)
    geo.usd      <- geometry
  ```
- `bind_material` adds materials incrementally:
  ```
  project/assets/chair/
    chair.usd    <- root (now sublayers geo.usd + mtl.usd)
    geo.usd      <- geometry
    mtl.usd      <- materials defined inline + bindings
  ```
- `place_asset` with an existing ASWF folder copies the entire folder
- `place_asset` with a USDZ copies the single file (no folder)

### Key rules
- Loose geometry is wrapped in ASWF folders on placement
- USDZ files stay as-is (self-contained)
- The scene.usda only contains references — no material sublayers
- Existing ASWF folders are copied whole, preserving structure

## Room Defaults
- Width: 10m (X axis)
- Height: 3m (Y axis)
- Depth: 8m (Z axis)
- Origin (0,0,0) is back-left corner at floor level
- Center of room: (5.0, 0.0, 4.0)