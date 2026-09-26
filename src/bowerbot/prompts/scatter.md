Scatter places many copies of assets over the surfaces already in the
scene, from a handful to a million, with every piece resting on the
triangles it lands on (uneven, sloped or curved). Three tools:

- `scatter_on_surface`: fill surfaces (ground, floor, terrain, a rock,
  a hull, a shelf top) randomly, in rows, or as a heap.
- `scatter_along_path`: place pieces along a line, loop, circle or
  curve (posts, streetlights, fence sections, shelf products, chairs
  round a table).
- `drop_to_surface`: settle objects that are ALREADY placed onto the
  surface below them (fix floating or sunken placements, or reseat every
  instance of a scatter in place).

Use scatter instead of `place_layout` whenever pieces must sit on real
geometry or the count is large; use `place_layout` for exact, flat,
grid-like layouts you fully specify.

### Workflow

1. `list_scene` (and `list_prim_children` on a placement) to find the
   surface prims to scatter onto and anything to keep clear.
2. For large or density-based requests, call with `validate_only=true`
   first; it reports the estimated count and eligible area without
   writing anything. Tell the user the count before writing more than
   100,000 (each 100,000 instances adds about 12 MB to scene.usda).
3. Scatter. The result reports `instances`, `by_asset`, the `seed`, and
   any `warnings` (e.g. fewer pieces fit than requested). Relay warnings.
4. To adjust, call again with the same `name` and `replace=true`. Keep
   the `seed` to change one thing at a time; change the `seed` for a
   different random layout with the same settings. `replace` rebuilds
   the scatter from scratch: its prototypes get the asset names back and
   lose any renames or variant sets added since, so re-add those after.

### Units and conventions

- Lengths (`min_spacing`, `radius`, `spacing`, `row_spacing`, `offset`,
  `jitter`, `avoid_margin`, `variation_scale`) and all coordinates are
  in SCENE units, like every other tool. `density` is instances per
  square METER regardless of scene units.
- Plan-view angles (`row_direction_degrees`, `direction_degrees`): 0 is
  +X; 90 is +Z in Y-up scenes and +Y in Z-up scenes.
- An asset's "front" is +Z in Y-up scenes and -Y in Z-up scenes (after
  BowerBot's up-axis conform). If pieces face the wrong way, re-run with
  `yaw_offset_degrees` (90, 180 or -90) and `replace=true`.
- Results are deterministic: same inputs + same seed = identical scene.

### Output

Assets are staged into `assets/` and referenced exactly as `place_asset`
does it, so `list_project_assets` and `delete_project_asset` treat
scattered assets like any other.

- `instancer` (default for `scatter_on_surface`, max 1,000,000): one
  PointInstancer prim at `/Scene/<group>/<name>` in scene.usda. Its
  prototypes are placement wrappers referencing the assets; the
  instancer repeats them. The whole scatter moves or is removed as one
  prim (`move_asset`, `remove_prim`); individual pieces cannot be edited.
- `placements` (default for `scatter_along_path`, max 10,000): a group
  `/Scene/<group>/<name>` holding one normal placement per piece, each
  editable with `move_asset`, materials, variants, `remove_prim`.
  Prefer it when the user may tweak individual pieces (chairs, lamps,
  posts, products).

### Plain words to parameters

- "stones spread across the uneven ground, thicker in places" →
  `scatter_on_surface` onto the ground, `density` (e.g. 8 per m²),
  `variation` 0.6-0.8, `align='surface'`, `scale_range` [0.7, 1.3],
  `embed` 0.1-0.3 for half-buried stones.
- "a heap / pile of rocks by the gate" → `arrangement='pile'`, `count`,
  `region` { center_prim: the gate (or center), radius }. The radius is
  the heap's base: pieces fill a cone no steeper than `repose_degrees`
  (steeper heaps: 40-45), so it stands at most radius x tan(repose) plus
  one piece. Few pieces make a low spread; if they don't fit the cone,
  the base widens and the result warns. Pieces lie on their flattest side
  and rest on each other's real shapes; `tilt_jitter_degrees` sets their
  tilt (default 10).
- "grass covering the lawn but not the path" → onto the lawn,
  `avoid` [the path prim], `align='up'`, `density`, small
  `tilt_jitter_degrees` (5-10) for a natural look.
- "crops / vines in rows on the hillside" → `arrangement='rows'`,
  `spacing` (along a row), `row_spacing`, `row_direction_degrees`,
  `align='up'`, small `jitter`; rows drape over the terrain.
- "trees across the park, never too close" → `count`, `min_spacing`,
  `align='up'`, `scale_range` for size variety.
- "leaves and twigs under the tree" → `region` { center_prim: the tree,
  radius: about the canopy radius, falloff: 'smooth' }, `align='surface'`.
  Do NOT put the tree in `avoid` (that clears its whole canopy footprint).
- "debris and boxes on the warehouse floor, avoiding the shelving" →
  several `assets` with `weight`s, `avoid` [the shelving group],
  `avoid_margin` for an aisle gap.
- "pebbles on the tracks between the crop blocks" → onto the ground,
  `avoid` [the crop scatters], `avoid_margin` a little over half the gap
  between rows, so the whole block stays clear.
- "barnacles / moss over the rock / hull" → surfaces = the rock or hull,
  `max_slope_degrees=180` (every face, including undersides),
  `align='surface'`, `density`.
- "products lined up along the shelf" → `scatter_along_path` with
  `points` along the shelf top at shelf height, no `count`/`spacing`
  (pieces butt together) or a `gap`, `facing='fixed'` toward the aisle,
  `surfaces` [the shelf].
- "streetlights / fence posts along the winding road" →
  `scatter_along_path`, `points` tracing the road (or `curve_prim`),
  `spacing`, `sides` 'left'/'right'/'both' with `offset` (distance from
  the road centre line), `facing='path'` so lights face the road.
- "a fence built from sections following the boundary" →
  `scatter_along_path`, `points` around the boundary (`closed=true` for
  an enclosure), no `count`/`spacing` so sections butt end to end,
  `facing='tangent'`, `follow_slope=true` on hills.
- "chairs round the table" → `scatter_along_path`, `circle`
  { center_prim: the table, radius: table half-size + chair depth },
  `count`, `facing='center'`.
- "drop the crates onto the ground" / "they are floating" →
  `drop_to_surface` with the placements or their group; `align='surface'`
  to also tilt them onto a slope.
- "the scattered trees / bales are sunk into the ground" →
  `drop_to_surface` with the scatter (or its group). It reseats every
  instance in place and keeps the prototypes and their variant sets;
  prefer it over re-scattering with `replace=true`, which rebuilds them.
  For lying pieces (branches, logs) with one end buried or in the air,
  add `align='surface'` to re-tilt them onto the ground under them.

### Things to know

- With `align='up'`, each piece sits on the ground under its base (the
  bottom of the model: a tree's trunk, a bale's underside) and sinks only
  as far as the ground dips under that base, so wide crowns don't matter.
- With `align='surface'`, each piece tilts to the average ground under
  its base, so a long branch across tilled ridges lies along them instead
  of following one ridge face. Steep faces and undersides (moss on a
  rock) follow the face itself.
- `surfaces` must contain geometry (Mesh, Cube, Sphere, Plane).
  Referenced assets work: pass the placement or its mesh parts. A
  scatter can't be a surface.
- Faces steeper than `max_slope_degrees` (default 60) get nothing. If
  the tool says faces point downward, the mesh normals are flipped or you
  targeted an underside; use `max_slope_degrees=180` for all-around cover.
- `avoid` clears everything under a prim's plan-view footprint (all of
  its geometry, projected straight down), plus `avoid_margin`. For a
  scatter, each instance clears its own bounding-box footprint and the
  gaps between instances stay open unless `avoid_margin` closes them.
- `scatter_along_path` snaps each piece to the surface nearest the path
  point's own height, so give shelf paths at shelf height and ground paths
  near ground height. With no `surfaces`, all scene geometry is used.
- Removing a scatter with `remove_prim` leaves its assets in `assets/`,
  like any removed placement; `delete_project_asset` removes them once
  nothing references them.
