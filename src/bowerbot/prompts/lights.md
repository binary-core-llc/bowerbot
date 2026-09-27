Use `create_light` to add native USD lights. There are two levels.

### Light workflow

1. Call `list_light_type_properties` with the chosen `light_type` to learn
   which `inputs:*` attributes the type declares (names, types, defaults,
   docs, and `allowed_tokens` for enum-typed inputs like
   `inputs:texture:format`). This is the source of truth, not a memorized
   list. The schema is read live from UsdLux.
2. Call `create_light` and pass the inputs you want to set in the
   `attributes` dict, keyed by full attribute name
   (`inputs:intensity`, `inputs:color`, `inputs:radius`, ...). Anything
   you don't pass keeps the UsdLux default.
3. Anything not covered by `attributes` and the structured params
   (translate, rotate, texture, light_link_includes) is changed later
   with `set_prim_attribute` on the light prim.

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
flame, recessed ceiling lights inside a building. These travel with
the asset. Set `asset_prim_path` to the placement's path
(`/Scene/<Group>/<Name>`, as `list_scene` reports it) to create the
light in the asset's `lgt.usda` file instead of the scene.

`DomeLight` (sky/HDRI environment) and `DistantLight` (the sun /
infinite directional) are scene-level environment lights and **cannot**
be asset-level — create them without `asset_prim_path`. Only local
fixtures (`SphereLight`, `RectLight`, `DiskLight`, `CylinderLight`) can
be asset-level. The texturable asset-level light is the `RectLight` (a
textured area light, e.g. a glowing screen or panel); its texture is
staged into the asset's `maps/`.

Asset lights support two coordinate modes via the `position_mode`
parameter. Choose the one that matches what the user is asking for.

#### `position_mode: "bounds_offset"` (default)
Translate values are meters from the asset's bounding box, along the
scene's axes as the asset stands unrotated; the light is shared by
every placement, so on a turned placement it turns with the asset. Use
this for "above/below" placements relative to the whole asset — e.g. a
bulb above a desk lamp.

- The up-axis value (`translate_y` in a Y-up scene, `translate_z` in a
  Z-up scene) is measured from the top surface: 1.0 → 1 m above the
  top; a negative value is measured from the bottom (-0.5 → 0.5 m below
  the bottom).
- The other two values are measured from the bounding-box center:
  `translate_x: 0.3` → 0.3 m from the center toward +X.
- If `create_light` gets no up-axis value → 0.5 m above the top.

Example: "add a point light to the desk lamp" in a Y-up scene →
`asset_prim_path` pointing to the lamp, `position_mode:
"bounds_offset"` (or omit, it's the default), `translate_y: 0.5`, and
`attributes: {"inputs:intensity": 1000, "inputs:radius": 0.05}`. In a
Z-up scene the same bulb is `translate_z: 0.5`.

#### `position_mode: "absolute"`
Translate values are **world-space** coordinates in scene units — the
same coordinates returned by `list_scene` and `list_prim_children`.
BowerBot converts them into the asset's own frame through the placement
you pass as `asset_prim_path` (the placement itself, never a part inside
it); other placements get the light at the same spot on their copy.

Workflow for interior fixtures:
1. Call `list_prim_children` on the container asset
2. For each fixture prim, read its `bounds` (world coordinates in scene units)
3. Compute the center: `((min.x + max.x)/2, ...)`
4. Call `create_light` with `position_mode: "absolute"` and those
   center coordinates as `translate_x/y/z`

`bounds_offset` values are meters; `absolute` values are world
coordinates in scene units, like everything `list_scene` reports.
Spatial inputs (radius, width, height, length) inside `attributes` are
meters for an asset light (BowerBot scales them to the asset's native
units) and scene units for a scene light (a 5 cm bulb in a centimeter
scene is `inputs:radius: 5`).

`create_light` returns the light's world `position` and, for asset
lights, the composed scene `prim_path` (also restated in the
`message`). Pass that `prim_path` to `update_light`
(moves, rotates or re-textures the shared light, on every placement) or
to `set_prim_attribute` (a tweak on that one placement).

### Light types
- **DistantLight** — sun/directional. Only rotation matters.
  Use `rotate_x` for sun angle (-45 = afternoon).
  Per-type input: `inputs:angle` (0.53 = realistic sun).
- **DomeLight** — environment/HDRI. Pass the HDRI's `location` from
  `search_textures` / `list_textures` as `texture` and BowerBot stages
  it; file paths are refused.
  Per-type inputs: `inputs:texture:file`, `inputs:texture:format`.
- **SphereLight** — point/omni. Emits in all directions.
  Per-type input: `inputs:radius` (0.05–0.1 for lamps, bulbs).
- **RectLight** — rectangular area. Default faces -Z direction.
  Per-type inputs: `inputs:width`, `inputs:height`, `inputs:texture:file`.
- **DiskLight** — circular area. Default faces -Z direction.
  Per-type input: `inputs:radius`.
- **CylinderLight** — tube.
  Per-type inputs: `inputs:radius`, `inputs:length`.

Common UsdLux inputs across every type: `inputs:intensity`,
`inputs:exposure`, `inputs:color`, `inputs:colorTemperature`,
`inputs:enableColorTemperature`, `inputs:diffuse`, `inputs:specular`,
`inputs:normalize`. Always call `list_light_type_properties` when you
need exact names and defaults.

### Light rotation
Directional lights (DiskLight, RectLight) emit along their local -Z.
Rotations are about the scene's axes. An asset light's rotation applies
as the asset stands unrotated, so it turns with each placement.
Set rotation based on where the user wants the light to point:

| Point the light | Y-up scene | Z-up scene |
|---|---|---|
| DOWN onto a surface below | `rotate_x: -90` | no rotation |
| UP from below | `rotate_x: 90` | `rotate_x: 180` |
| toward -X | `rotate_y: 90` | `rotate_y: 90` |
| toward +X | `rotate_y: -90` | `rotate_y: -90` |
| toward +Z / +Y (forward) | `rotate_y: 180` (+Z) | `rotate_x: 90` (+Y) |

Ask the user if the direction is ambiguous.

### Light linking
By default, a USD light affects every prim in the scene. To restrict
a light to specific targets (e.g. "this rim light only on the hero
prop"), pass `light_link_includes` as a list of prim paths when
calling `create_light`. BowerBot authors a UsdLux `light:link`
collection on the light with those targets. Every path must exist
(`list_scene` / `list_prim_children`). An asset light can only link
prims inside its own asset (e.g. its lamp's shade), because it is
shared by every placement of the asset; to light other prims only,
use a scene light.

Leave `light_link_includes` empty (or omit it) for general
illumination — the USD default.

### CRITICAL: Asset-level lights are SHARED across every instance

When an asset light is created via `create_light(asset_prim_path=...)`,
it lives in the asset's `lgt.usda` once and is automatically composed
onto EVERY placement of that asset.

**Never call `create_light` more than once for the same logical light
on the same asset.** When the user says any of:
- "add the same light to the other tables"
- "apply this light setup to every instance"
- "do the same on the other ones"

…and the light is asset-level, the answer is:

1. **If the user just wants the same light to appear on every
   placement** → already done. The asset light is shared. Tell the
   user it's already on all placements.
2. **If the user wants to TWEAK the same param across every
   placement** (e.g., "make each table's light brighter") → call
   `set_prim_attribute` ONCE PER PLACEMENT, targeting each placement's
   composed light path
   (`/Scene/.../<Placement_N>/asset/lgt/<light_name>`). Each call
   writes a per-instance override to `scene.usda`. Position, rotation
   and texture are different: ONE `update_light` call changes the
   shared light in `lgt.usda`, so every placement follows.
3. **If the user wants each placement to have a DIFFERENT light**
   → those are not asset lights anymore. Ask whether to switch to
   scene-level lights.

### Modifying lights
`update_light` edits the light where it lives — an asset light's
`lgt.usda` (so the change applies to every instance) or `scene.usda`
for a scene light. `set_prim_attribute` instead authors a per-instance
override in `scene.usda` on one placement's composed light prim.

- **Position / rotation / texture** → `update_light`. Pass only
  what changes: omitted translate / rotate axes keep their current
  values. Moving an asset light requires `position_mode` (`absolute`
  for world coordinates, `bounds_offset` for meters from the asset's
  bounds); the call is refused without it.
  Handles xform-op management and texture staging (asset `maps/` for an
  asset RectLight, `<project>/textures/` for a scene DomeLight).
- **Any UsdLux input** (intensity, exposure, color, radius, angle,
  width, height, length, colorTemperature, diffuse, specular,
  normalize, etc.) → `set_prim_attribute` on the light prim with
  the full `inputs:*` name. Use `list_prim_attributes` if unsure.
- **Undo a previous tweak** → `set_prim_attribute(..., value=null)`.

### Removing lights
Use `remove_light` to delete a light: a scene light, or an asset light
BowerBot added (a light that comes from the asset's own files is
refused) — provide the `prim_path`. It accepts lights only; to remove
the whole `/Scene/Lighting` group or any other prim, use `remove_prim`.

A texture the light used stays in the project; the result lists it
in `unused_files` (e.g. `textures/studio.exr` for a DomeLight's HDRI,
`assets/lamp/maps/screen.png` for an asset RectLight's). Ask the user
if they want to delete it. If they confirm, call
`delete_project_file(file_name=<that entry>)`; it deletes only the
project's copy, never the user's library, and refuses while another
file (e.g. a snapshot) still uses it. `update_light` lists a texture it
replaced the same way.

### CRITICAL: Do NOT switch light levels
If a light was created as an **asset light**, it MUST stay an asset
light when the user asks to move, reposition, or adjust it. Use
`update_light` to change its position/rotation — do NOT remove it
and recreate as a scene light.

Only switch from asset light to scene light (or vice versa) if the
user **explicitly** asks for it.

### Sensible starting points
Use these as a sanity-check, not a substitute for the schema:
- Interior `inputs:intensity` ≈ 1000; Distant ≈ 500; Dome ≈ 1.0.
- `inputs:exposure` is a power-of-2 multiplier on intensity (camera
  stops). +1 doubles, -1 halves. Default 0.
- Warm white `inputs:color` ≈ (1.0, 0.9, 0.8); cool ≈ (0.9, 0.95, 1.0).
- Scene lights go in `/Scene/Lighting`.
- Asset lights go in the asset's `lgt.usda` under `/<defaultPrim>/lgt/`
  (in the scene: `<placement>/asset/lgt/<name>`).
