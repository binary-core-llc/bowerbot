Use `create_light` to add native USD lights. There are two levels.

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
it's the default), translate_y = 0.5.

#### `position_mode: "absolute"`
Translate values are **world-space** coordinates — the same
coordinates returned by `list_scene` and `list_prim_children`.
BowerBot handles the conversion from world-space to the asset's
internal coordinate frame automatically.

Use this when you know the exact world-space position — typically
from reading `list_prim_children` bounds. Works for placements
that are inside, outside, above, below, or anywhere else relative
to the container — the coordinate math is the same.

Workflow for interior fixtures:
1. Call `list_prim_children` on the container asset
2. For each fixture prim, read its `bounds` (world-space meters)
3. Compute the center: `((min.x + max.x)/2, ...)`
4. Call `create_light` with `position_mode: "absolute"` and those
   center coordinates as `translate_x/y/z`

Example: "add lights at the recessed fixtures inside the building":
- `list_prim_children` returns `building_recessed_light_1` with
  bounds center at world-space coordinates, e.g.
  `(10.96, 4.27, 1.42)` (after the building's scene placement)
- Call `create_light(asset_prim_path=building, position_mode="absolute",
  translate_x=10.96, translate_y=4.27, translate_z=1.42, ...)`
- BowerBot writes the light to the building's `lgt.usda` at the
  correct asset-internal position; when the scene is composed,
  the light lands exactly where the fixture geometry is.

The same workflow works for a lamp attached to the building but
positioned outside (e.g. a porch light) — pass the desired
world-space position and BowerBot places it correctly inside
the building's asset folder.

Values are always in meters.

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

### Light linking

By default, a USD light affects every prim in the scene. To restrict
a light to specific targets (e.g. "this rim light only on the hero
prop", a product-shot kicker, a key light that should not bleed onto
the dome), pass `light_link_includes` as a list of prim paths when
calling `create_light`. BowerBot authors a UsdLux `light:link`
collection on the light with those targets; the light then only
illuminates the listed prims and their descendants.

Leave `light_link_includes` empty (or omit it) for general
illumination — that is the standard USD default and what most scene
lights want.

### CRITICAL: Asset-level lights are SHARED across every instance

When an asset light is created via `create_light(asset_prim_path=...)`,
it lives in the asset's `lgt.usda` once and is automatically composed
onto EVERY placement of that asset. Four tables referencing the same
`single_table` asset = one shared light visible on all four tables,
because they all reference the same `lgt.usda`.

**Never call `create_light` more than once for the same logical light
on the same asset.** When the user says any of:
- "add the same light to the other tables"
- "apply this light setup to every instance"
- "do the same on the other ones"

…and the light is asset-level, the answer is:

1. **If the user just wants the same light to appear on every
   placement** → already done, do nothing. The asset light is
   shared. Tell the user it's already on all placements.
2. **If the user wants to TWEAK the same param across every
   placement** (e.g., "make each table's light brighter") → call
   `update_light` or `set_prim_attribute` ONCE PER PLACEMENT,
   targeting each placement's composed light path
   (`/Scene/.../<Placement_N>/asset/lgt/<light_name>`). Each call
   writes a per-instance override to `scene.usda`. Never call
   `create_light` again — that creates a duplicate light in
   `lgt.usda` which then appears on every placement, exploding the
   light count.
3. **If the user wants each placement to have a DIFFERENT light**
   (different size, position, color) → those are not asset lights
   anymore. Ask whether to switch to scene-level lights (one
   `create_light` per placement under `/Scene/Lighting/...`).

### Modifying lights

Every value change goes to `scene.usda`. The asset's `lgt.usda` is
only touched by `create_light` (publish) and `remove_light` (delete).

- **Position / rotation / HDRI texture** → `update_light`. Handles
  xform-op management, `position_mode: bounds_offset` math for
  asset lights, and texture file staging into `<project>/textures/`.
  Writes the override to `scene.usda`.

- **Any other attribute** (intensity, exposure, color, radius,
  angle, width, height, length, colorTemperature, treatAsLine,
  shadow:enable, normalize, focus, etc.) → `set_prim_attribute` on
  the light prim. Call `list_prim_attributes` first if you are
  unsure of the attribute name. Writes the override to `scene.usda`.

- **Undo a previous tweak** → `set_prim_attribute(..., value=null)`.
  Removes the override from `scene.usda` so the asset's published
  value (in `lgt.usda`) takes over again.

For "change this for every placement of the same asset", call
`set_prim_attribute` once per placement. Each placement gets its
own scene-level override.

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
- Exposure: power-of-2 multiplier on intensity (camera stops).
  Final brightness = intensity × 2^exposure. +1 doubles, -1 halves.
  Use when a user asks to make a light "brighter" or "dimmer" by
  a relative amount. Default: 0.
- Color: warm white (1.0, 0.9, 0.8), cool (0.9, 0.95, 1.0)
- Scene lights go in `/Scene/Lighting`
- Asset lights go in the asset's `lgt.usda` under `/{asset}/lgt/`
