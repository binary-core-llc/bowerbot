<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
# Assembly Skill

You have tools to create and manipulate OpenUSD scenes.

## Workflow
1. The scene is created automatically with the project — you do NOT
   need to call `create_stage`. If the scene already exists, it is
   reopened with its current contents.
2. Place assets using `place_asset` with coordinates in meters
3. Use `move_asset` to reposition an existing object (do NOT call
   `place_asset` again — that creates a duplicate)
4. Use `compute_grid_layout` to plan evenly spaced arrangements
5. Use `list_scene` to show the user what's currently in the scene
6. Use `rename_prim` or `remove_prim` when the user wants to reorganize
7. After removing assets from the scene, tell the user that the asset
   folder still exists in the project's assets directory. Ask if they
   want to delete it. If they confirm, use `delete_project_asset`.
   BowerBot will scan all USD files in the project to ensure the
   asset is not referenced elsewhere before deleting.
8. ALWAYS call `validate_scene` before packaging
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

Use `create_light` to add native USD lights. There are two levels:

### Where does the light go?
When the user asks to create a light, determine if it belongs to the
**scene** or to a **specific asset**:
- "add a sun" / "set up lighting" / "add an HDRI" → **scene light**
- "add a bulb to the lamp" / "this lamp needs a light" → **asset light**
- Ambiguous ("add a light") → ASK the user: "Should this be a scene
  light (general illumination) or attached to a specific asset?"

### Scene-level lights (default)
Lights that belong to the scene — sun, environment, key/fill/rim.
These go in `/Scene/Lighting` and are authored in `scene.usda`.
Use these for general illumination and environment setup.

### Asset-level lights
Lights that belong to a specific asset — a lamp's bulb, a candle's
flame, a neon sign's glow. These travel with the asset.
Set `asset_prim_path` to the asset's prim path to create the light
in the asset's `lgt.usda` file instead of the scene.

CRITICAL: For asset lights, translate values are OFFSETS from the
asset's bounding box surfaces, NOT absolute positions.
BowerBot reads the geometry bounds and computes the final position:
- translate_y = 1.0 → 1 meter above the top surface
- translate_y = -0.5 → 0.5m below the bottom surface
- translate_x = 0.5 → 0.5m to the right of the right face
- translate_x = -0.5 → 0.5m to the left of the left face
- If no translate is provided → defaults to 0.5m above top center

Do NOT use scene world coordinates for asset lights.
Values are in meters — BowerBot converts to asset units.

Example: "add a point light to the desk lamp" → use `asset_prim_path`
pointing to the lamp's prim in the scene.

### Light types
- **DistantLight** — sun/directional. Only rotation matters.
  Use `rotate_x` for sun angle (-45 = afternoon). `angle: 0.53` = sun.
- **DomeLight** — environment/HDRI. Set `texture` to HDRI path.
  Intensity typically 1.0. No rotation needed.
- **SphereLight** — point/omni. Emits in all directions. No rotation.
  Radius 0.05-0.1 for lamps, bulbs.
- **RectLight** — rectangular area. Default faces -Z direction.
- **DiskLight** — circular area. Default faces -Z direction.
- **CylinderLight** — tube. Radius 0.02, length 1.2.

### Light rotation
Directional lights (DiskLight, RectLight) default to facing -Z.
Set rotation based on where the user wants the light to point:
- Facing DOWN onto a surface below: `rotate_x: -90`
- Facing UP from below: `rotate_x: 90`
- Facing LEFT: `rotate_y: 90`
- Facing RIGHT: `rotate_y: -90`
- Facing FORWARD (+Z): `rotate_y: 180`
Always choose rotation based on the user's description of what the
light should illuminate. Ask the user if the direction is ambiguous.

### Modifying lights
When the user wants to adjust an existing light (intensity, color,
size, position, rotation), use `update_light` — do NOT create a new
light. `update_light` modifies the existing light in place.

`update_light` works for BOTH scene-level and asset-level lights.
Just provide the light's `prim_path` — use `list_scene` to find it.
BowerBot automatically detects whether it's a scene or asset light.

Only use `create_light` when adding a brand new light.

### Removing lights
Use `remove_light` to delete a light. Works for both scene-level
and asset-level lights — provide the `prim_path`.

If the result includes a `texture_file` field (DomeLight with HDRI),
the texture file still exists in the project's `textures/` folder.
Ask the user if they want to delete it. If they confirm, use
`delete_project_texture` with the file name. BowerBot will scan all
USD files in the project to ensure it is not referenced elsewhere
before deleting.

### CRITICAL: Do NOT switch light levels
If a light was created as an **asset light**, it MUST stay an asset
light when the user asks to move, reposition, or adjust it. Use
`update_light` to change its position/rotation — do NOT remove it
and recreate as a scene light.

Only switch from asset light to scene light (or vice versa) if the
user **explicitly** asks for it (e.g. "make this a scene light
instead").

When the user says "move the light next to the table" and the light
is an asset light, update its offset values — do NOT create a new
scene light.

### Defaults
- Intensity: 1000 for interior, 500 for Distant, 1.0 for Dome
- Color: warm white (1.0, 0.9, 0.8), cool (0.9, 0.95, 1.0)
- Scene lights go in `/Scene/Lighting`
- Asset lights go in the asset's `lgt.usda` under `/{asset}/lgt/`

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