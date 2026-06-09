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
the asset. Set `asset_prim_path` to the asset's prim path to create
the light in the asset's `lgt.usda` file instead of the scene.

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
Translate values are OFFSETS from the asset's bounding box surfaces.
Use this for "above/below/next to" placements relative to the whole
asset — e.g. a bulb above a desk lamp.

- translate_y = 1.0 → 1 meter above the top surface
- translate_y = -0.5 → 0.5m below the bottom surface
- translate_x = 0.5 → 0.5m to the right of the right face
- If no translate is provided → defaults to 0.5m above top center

Example: "add a point light to the desk lamp" → `asset_prim_path`
pointing to the lamp, `position_mode: "bounds_offset"` (or omit,
it's the default), translate_y = 0.5, and
`attributes: {"inputs:intensity": 1000, "inputs:radius": 0.05}`.

#### `position_mode: "absolute"`
Translate values are **world-space** coordinates — the same
coordinates returned by `list_scene` and `list_prim_children`.
BowerBot handles the conversion from world-space to the asset's
internal coordinate frame automatically.

Workflow for interior fixtures:
1. Call `list_prim_children` on the container asset
2. For each fixture prim, read its `bounds` (world-space meters)
3. Compute the center: `((min.x + max.x)/2, ...)`
4. Call `create_light` with `position_mode: "absolute"` and those
   center coordinates as `translate_x/y/z`

Values are always in meters. Spatial inputs (radius, width, height,
length) inside `attributes` are also in meters; BowerBot scales them
to the asset's native units for asset lights.

`create_light` returns the **resolved** `position` (in bounds_offset /
absolute modes the final asset-local coordinates differ from what you
passed) and, for asset lights, the composed scene `prim_path` (also
restated in the `message`). Pass that `prim_path` to `update_light` or
`set_prim_attribute` for later per-placement tweaks.

### Light types
- **DistantLight** — sun/directional. Only rotation matters.
  Use `rotate_x` for sun angle (-45 = afternoon).
  Per-type input: `inputs:angle` (0.53 = realistic sun).
- **DomeLight** — environment/HDRI. Pass an absolute HDRI path as
  `texture` and BowerBot stages it.
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
Directional lights (DiskLight, RectLight) default to facing -Z.
Set rotation based on where the user wants the light to point:
- Facing DOWN onto a surface below: `rotate_x: -90`
- Facing UP from below: `rotate_x: 90`
- Facing LEFT: `rotate_y: 90`
- Facing RIGHT: `rotate_y: -90`
- Facing FORWARD (+Z): `rotate_y: 180`
Ask the user if the direction is ambiguous.

### Light linking
By default, a USD light affects every prim in the scene. To restrict
a light to specific targets (e.g. "this rim light only on the hero
prop"), pass `light_link_includes` as a list of prim paths when
calling `create_light`. BowerBot authors a UsdLux `light:link`
collection on the light with those targets.

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
   `update_light` or `set_prim_attribute` ONCE PER PLACEMENT,
   targeting each placement's composed light path
   (`/Scene/.../<Placement_N>/asset/lgt/<light_name>`). Each call
   writes a per-instance override to `scene.usda`.
3. **If the user wants each placement to have a DIFFERENT light**
   → those are not asset lights anymore. Ask whether to switch to
   scene-level lights.

### Modifying lights
`update_light` edits the light where it lives — an asset light's
`lgt.usda` (so the change applies to every instance) or `scene.usda`
for a scene light. `set_prim_attribute` instead authors a per-instance
override in `scene.usda` on one placement's composed light prim.

- **Position / rotation / texture** → `update_light`. Handles
  xform-op management, `position_mode: bounds_offset` math for
  asset lights, and texture staging (asset `maps/` for an asset
  RectLight, `<project>/textures/` for a scene DomeLight).
- **Any UsdLux input** (intensity, exposure, color, radius, angle,
  width, height, length, colorTemperature, diffuse, specular,
  normalize, etc.) → `set_prim_attribute` on the light prim with
  the full `inputs:*` name. Use `list_prim_attributes` if unsure.
- **Undo a previous tweak** → `set_prim_attribute(..., value=null)`.

### Removing lights
Use `remove_light` to delete a light. Works for both scene-level
and asset-level lights — provide the `prim_path`.

If the result includes a `texture_file` field (DomeLight with HDRI),
the texture file still exists in the project's `textures/` folder.
Ask the user if they want to delete it. If they confirm, use
`delete_project_texture` with the file name.

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
- Asset lights go in the asset's `lgt.usda` under `/{asset}/lgt/`.
