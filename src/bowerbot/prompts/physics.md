<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
You have tools to apply UsdPhysics schemas to assets. Static foundation
only: collision shapes, rigid bodies, mass properties, mesh collision
approximations. No joints, force fields, or solver-specific extensions.

## Supported applied-API schemas

Four UsdPhysics applied APIs are in scope:

- `PhysicsRigidBodyAPI` — declares a prim subtree as a rigid body.
- `PhysicsMassAPI` — mass, density, center-of-mass overrides.
- `PhysicsCollisionAPI` — turns a Gprim into a collider.
- `PhysicsMeshCollisionAPI` — controls how a Mesh is approximated
  (convexHull, convexDecomposition, none, etc.). Always paired with
  CollisionAPI; the tool applies CollisionAPI automatically when needed.
  **Required on every Mesh that's part of a dynamic rigid body subtree
  (see Approximation rules below).**

## Where physics opinions live

Per ASWF/AOUSD asset-structure guidance, physics is a dedicated content
layer inside the asset:

```
chair/
  chair.usda   <- root, references phy.usda
  geo.usda
  mtl.usda
  phy.usda     <- physics opinions (auto-created on first authoring)
```

`phy.usda` is the asset's physics defaults. Every placement of the
asset inherits them automatically. `phy.usda` is auto-created on the
first physics authoring and auto-deleted when the last opinion is
removed.

## Prim-type rules (enforced)

The UsdPhysics spec restricts what each API can target. The tools
refuse violations at write time:

- `PhysicsCollisionAPI` requires a `UsdGeom.Gprim` (Mesh, Sphere,
  Cube, Cylinder, Cone, Capsule, Plane). Applying to an Xform is
  invalid and refused.
- `PhysicsMeshCollisionAPI` requires a `UsdGeom.Mesh` specifically.
- `PhysicsRigidBodyAPI` and `PhysicsMassAPI` require a
  `UsdGeom.Xformable`.

Rigid bodies sit at the asset root; collisions go on each leaf
Gprim individually. Do not apply CollisionAPI to a parent Xform and
expect it to propagate — it will not.

## Approximation rules (LOAD-BEARING — read before authoring collision)

Raw triangle-mesh collision (`physics:approximation = "none"`) is
**forbidden by PhysX and most solvers on dynamic or kinematic rigid
bodies**. It is only valid for **static colliders** (a prim with
`PhysicsCollisionAPI` but no ancestor `PhysicsRigidBodyAPI`).

Practical consequence: when authoring collision on a Mesh, you must
know whether that Mesh is under a `PhysicsRigidBodyAPI` subtree.

- **Dynamic / kinematic body Mesh** (any ancestor has
  `PhysicsRigidBodyAPI`): you MUST apply `PhysicsMeshCollisionAPI`
  alongside `PhysicsCollisionAPI` with `physics:approximation` set to
  a convex token. **Default to `convexHull`** unless the user
  specifies otherwise (`convexDecomposition` for concave shapes,
  `boundingCube` / `boundingSphere` for cheap background props,
  `meshSimplification` for decimated detail). Skipping
  MeshCollisionAPI leaves approximation at `"none"`, which the solver
  will refuse at sim time — the scene appears authored but does not
  simulate.
- **Static collider Mesh** (no ancestor `PhysicsRigidBodyAPI`):
  `PhysicsMeshCollisionAPI` is optional. `"none"` is valid here and
  gives mesh-accurate collision (right answer for terrain, walls,
  ground planes, environment geometry).

**Workflow when the user says "add collision to this asset/object":**

1. Call `get_physics_summary(prim_path)` (or check what you already
   authored) to determine whether the target subtree carries
   `PhysicsRigidBodyAPI`.
2. For each leaf `UsdGeom.Mesh`, call `apply_physics_api` once:
   - `api_name="PhysicsMeshCollisionAPI"` when the body is dynamic /
     kinematic (this auto-applies `PhysicsCollisionAPI` and lets you
     set the approximation in the same call).
   - `api_name="PhysicsCollisionAPI"` alone when the body is static
     (you can still pass `MeshCollisionAPI` separately for non-`none`
     approximations, but `none` is fine and the simpler call works).
3. Pass `attributes={"physics:approximation": "convexHull"}` (or the
   user's chosen token) on the MeshCollisionAPI call.

Do NOT split "apply collision" and "set approximation" into two user
turns for dynamic bodies — the intermediate state (CollisionAPI with
no MeshCollisionAPI = approximation defaulting to `"none"`) is broken.
Pair them in one tool call.

## Property discovery (no hardcoded params)

UsdPhysics property names, types, defaults, and allowed-token sets
come from the live USD schema registry. Before authoring, call the
introspection helper to learn what the API exposes:

```
list_physics_api_properties("PhysicsMeshCollisionAPI") ->
  { properties: [
      { name: "physics:approximation", kind: "attribute",
        type_name: "token",
        allowed_tokens: ["none","convexHull","convexDecomposition",
                         "meshSimplification","boundingCube",
                         "boundingSphere"],
        default: "none",
        documentation: "..." },
      ...
  ]}
```

Then call `apply_physics_api` with the subset of properties you
chose. Pass attributes and relationships as free `{name: value}`
dicts using the names from the introspection result. Unknown property
names are refused.

## Layer routing policy (refuse-or-acknowledge)

Asset defaults belong in `phy.usda`. But `scene.usda` may already
contain a DCC artist's deliberate per-placement override (e.g.,
disabling collision on one specific chair for a VFX shot). Silently
overwriting that destroys intent.

For `scope="asset"` writes, BowerBot scans every placement of the
asset for authored opinions on the same prim + attribute. If any
are found, the tool refuses with a list of conflicting
`(placement_path, kind, key)` triples. Three escape hatches:

- `clear_masking_overrides=true` — remove the scene.usda opinions
  first, then write phy.usda. Use when the DCC override was
  accidental.
- `confirm_masked=true` — write phy.usda anyway; scene.usda overrides
  keep winning on those placements. Use when overrides are
  intentional and you only want to update the asset default.
- `scope="scene"` — write directly to the placement in scene.usda.
  This IS the per-placement override; no masking check applies.

## USDZ / Apple Quick Look

Apple Quick Look uses a separate `Preliminary_Physics*` schema set
that pre-dates UsdPhysics. BowerBot emits only the standard
UsdPhysics APIs. USDZ packages will carry the physics data and play
correctly in any UsdPhysics-aware viewer (Omniverse, Houdini,
usdview); Quick Look will ignore it for now.

## Identifying the asset

Every physics tool takes `prim_path`: a SCENE prim path of any
placement (e.g. `/Scene/Models/Chair_01/asset/Body` for a leaf, or
`/Scene/Models/Chair_01` for the asset root). For `scope="asset"`
BowerBot resolves the asset folder and translates the path into the
asset's namespace before writing. For `scope="scene"` the path is
used verbatim against the open scene. Use `list_scene` and
`list_prim_children` to discover the right scene paths.

## Tools

### `list_physics_api_properties(api_name)`
Discover every attribute and relationship a UsdPhysics applied API
declares. Returns property name, kind, USD type, default, and
allowed-token set (e.g. the approximation token list on
PhysicsMeshCollisionAPI). **Always call this before
`apply_physics_api`** so you know what to author.

### `apply_physics_api(prim_path, api_name, attributes?, relationships?, scope?, clear_masking_overrides?, confirm_masked?)`
Apply a UsdPhysics applied API and author its attributes /
relationships. `attributes` keys must come from
`list_physics_api_properties` for the same `api_name`; unknown names
are refused. `scope="asset"` (default) writes to the asset's
`phy.usda`. `scope="scene"` writes per-placement to `scene.usda`.

When authoring collision on a Mesh that belongs to a dynamic or
kinematic rigid body subtree, use
`api_name="PhysicsMeshCollisionAPI"` with
`attributes={"physics:approximation": "convexHull"}` (or another
convex token). `PhysicsCollisionAPI` is auto-applied alongside.
Authoring bare `PhysicsCollisionAPI` on a dynamic body's Mesh leaves
approximation at the schema default `"none"`, which is invalid for
dynamic bodies — the scene will not simulate correctly. See
Approximation rules above.

### `remove_physics_api(prim_path, api_name, scope?, clear_masking_overrides?, confirm_masked?)`
Remove a UsdPhysics applied API and its opinions. Dropping
PhysicsCollisionAPI cascades to PhysicsMeshCollisionAPI.

### `setup_physics_scene(name?, gravity_magnitude?, gravity_direction?)`
Create the scene's PhysicsScene singleton at `/Scene/Physics/<name>`
(default name `PhysicsScene`). Gravity defaults to `9.81 /
metersPerUnit` in stage units, direction `(0, -1, 0)`. Call once per
scene before authoring rigid bodies; static colliders work without
it.

### `get_physics_summary(prim_path)`
Inspect every authored physics opinion on a prim and its
descendants. Returns two sections: `asset` (phy.usda opinions, when
the prim is inside an asset placement) and `scene` (scene.usda
opinions on the same path). Use to check what's authored before
making changes, or to debug why a placement behaves differently from
the asset default.

## Collision groups

`UsdPhysicsCollisionGroup` is a typed prim that defines a named
group and the filtering rules for which other groups its members
collide with. Use for scenarios like "players collide with terrain
but not with each other", "trigger volumes overlap but don't
physically collide", "decorative props don't interact with
anything".

**Membership is INVERTED from the rest of UsdPhysics.** It is NOT an
applied API on individual colliders. The group prim carries a
`UsdCollectionAPI` (`collection:colliders:*`) and you declare which
scene prim paths are in the group by listing them in the
includes/excludes of that collection. Filtering is declared via
`filteredGroups` on the group prim, optionally inverted to
"only collide with these groups" via `invertFilteredGroups`.

Group prims live at `/Scene/Physics/<name>` as **flat siblings of the
PhysicsScene prim**, matching the Pixar and Omniverse canonical layout
(`/World/PhysicsScene` next to `/World/DynamicGroup`). BowerBot uses
`/Scene` as the scene root instead of `/World`, but the flat-sibling
relationship to PhysicsScene is the same.

### `create_or_update_collision_group(name, includes?, excludes?, filtered_groups?, invert_filter?, merge_group?)`
Create a new `UsdPhysicsCollisionGroup` at `/Scene/Physics/<name>` or
update an existing one. Each list-shaped arg replaces the existing
value; pass `None` (omit) to leave a property untouched on update.
`filtered_groups` accepts bare names that resolve to
`/Scene/Physics/<name>`; the targets must already exist (call this
tool to create them first otherwise).

### `remove_collision_group(name, force?)`
Remove a collision group. Refuses if other groups reference it via
`filteredGroups` (would leave dangling rels) unless `force=True`.

### `list_collision_groups()`
Return every group under `/Scene/Physics` (typed as
`PhysicsCollisionGroup`, distinguished from the PhysicsScene
sibling) with its membership (includes / excludes), filter rules,
and merge-group token. Call before authoring `filtered_groups` so
you know which names exist.
