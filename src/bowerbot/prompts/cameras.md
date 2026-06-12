<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
Use `create_camera` to add USD cameras to the scene. Cameras live in
`/Scene/Cameras` and are authored in `scene.usda`. They survive
`save_scene_snapshot` and show up automatically in usdview's and
Omniverse Kit's camera lists.

### Camera workflow

1. Call `list_camera_properties` to learn the Camera attributes
   (names, types, defaults, docs, and `allowed_tokens` for
   `projection`). The schema is read live from UsdGeom; this is the
   source of truth, not a memorized list.
2. Call `create_camera` with a position and an aim, and pass any
   attributes you want to set in the `attributes` dict keyed by exact
   name (`focalLength`, `fStop`, `projection`, ...). Anything you
   don't pass keeps the UsdGeom default.
3. Reposition or re-aim later with `update_camera`. Change any other
   attribute with `set_prim_attribute` on the camera prim. Delete with
   `remove_camera`.

`list_scene` lists cameras with `kind: "camera"`, their projection,
focal length, and position.

### Aiming

USD cameras face their local **-Z** axis. Pass EXACTLY ONE of:

- `look_at`: a `[x, y, z]` point in scene units. BowerBot computes the
  rotation for the scene's up axis (Y-up and Z-up both work). Prefer
  this for "camera looking at the racks" requests — aim it at the
  target's bounds center from `list_scene`.
- `rotate_x/y/z`: explicit degrees, for matching an exact rotation
  (e.g. a camera exported from a DCC).

`update_camera` with `look_at` re-aims from the camera's current
position unless you also pass new translate values.

### Units (critical)

- `focalLength`, `horizontalAperture`, `verticalAperture`: treat as
  millimeter-style values and author the SAME numbers in every scene
  regardless of `meters_per_unit`. Never unit-scale them — field of
  view depends only on their ratio. Default 50 with the Academy 35mm
  film back ≈ 23.7° horizontal FOV; 35 is wider coverage, 85 is a
  portrait/long lens.
- `clippingRange` (a `[near, far]` pair) and `focusDistance`: in scene
  units. `create_camera` authors a clippingRange sized for the scene's
  units automatically; override via `attributes` when needed.

### Recipes

- **Orthographic plan/elevation view**: `attributes: {"projection":
  "orthographic", "horizontalAperture": <width * 10>}`. The visible
  width is `horizontalAperture * 0.1` scene units, so framing a 20 m
  wide area top-down needs aperture 200. `focalLength` has no effect
  in ortho.
- **Depth of field**: set `fStop` > 0 AND `focusDistance` (scene
  units, typically the distance from the camera to the subject).
  `focusDistance` alone does nothing while `fStop` is 0.
- **Top-down camera**: position above the area and `look_at` its
  center — the straight-down case is handled.

### Modifying and removing

- Position / aim → `update_camera`.
- Any Camera attribute (`focalLength`, `fStop`, `projection`, ...) →
  `set_prim_attribute` on the camera prim with the exact name; use
  `list_prim_attributes` if unsure. Undo a tweak with
  `set_prim_attribute(..., value=null)`.
- `remove_camera` deletes the camera. If the result includes a
  non-empty `suspect_variant_sets`, surface it to the user verbatim
  and ask before removing the named variant set.

Multiple cameras are normal (one per shot or view); give each a
descriptive name (`Hero_Cam`, `TopDown`, `Aisle_Walkthrough`).
