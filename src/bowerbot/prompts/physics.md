<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
You have tools to apply UsdPhysics schemas to assets: collision shapes,
rigid bodies, mass properties, mesh-collision approximations, collision
groups, typed joints (revolute/prismatic/spherical/fixed/distance),
articulation roots, and joint drives/limits. Out of scope: force fields
and solver-specific extensions.

## Supported applied-API schemas

Eight UsdPhysics applied APIs are in scope: the four below, plus
`PhysicsArticulationRootAPI`, `PhysicsDriveAPI` and `PhysicsLimitAPI`
(see Joints + articulations) and `PhysicsFilteredPairsAPI` (see Pair
filtering):

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

`apply_physics_api` auto-resolves the right typed prim within a
placement subtree. Naming the placement (e.g. `/Scene/Props/Box_01`) is
fine when the schema needs the Mesh underneath. The response reports
both the resolved `prim_path` and the `requested_prim_path`.
Scene-scope writes, scene joints and collision groups create a
PhysicsScene when the scene has none; asset-scope writes (the default
for placements) do not, so call `setup_physics_scene` before authoring
rigid bodies.

Rigid bodies sit at the asset root; collisions go on each leaf
Gprim individually. Do not apply CollisionAPI to a parent Xform and
expect it to propagate — it will not.

## Approximation rules (LOAD-BEARING — read before authoring collision)

Raw triangle-mesh collision (`physics:approximation = "none"`) is
**not supported on dynamic or kinematic rigid bodies by most physics
engines**. It is only valid for **static colliders** (a prim with
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
   authored) to see whether the target subtree carries
   `PhysicsRigidBodyAPI`. It reports only what BowerBot authored
   (phy.usda and scene.usda); for physics shipped in the asset's own
   files, call `list_prim_attributes` on `<placement>/asset` — a
   `physics:rigidBodyEnabled` attribute means RigidBodyAPI is applied.
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
placement (e.g. `/Scene/Furniture/Chair_01/asset/Body` for a leaf, or
`/Scene/Furniture/Chair_01` for the asset root). For `scope="asset"`
BowerBot resolves the asset folder and translates the path into the
asset's namespace before writing. For `scope="scene"` the path is
used verbatim against the open scene. Use `list_scene` and
`list_prim_children` to discover the right scene paths.

Relationship targets (`relationships`, collision-group `includes` /
`excludes`) must name prims that exist. At `scope="asset"` they are
translated into the asset too, so they must be inside it: what an asset
holds is shared by every placement. A target outside the asset, such as
`physics:simulationOwner` pointing at `/Scene/Physics/PhysicsScene`,
needs `scope="scene"`. Token attributes (e.g. `physics:axis`,
`physics:approximation`) take one of their allowed tokens.

## Tools

### `list_physics_api_properties(api_name)`
Discover every attribute and relationship a UsdPhysics applied API
declares. Returns property name, kind, USD type, default, and
allowed-token set (e.g. the approximation token list on
PhysicsMeshCollisionAPI). It also returns `target_requirement` (the prim
type the API targets) and `requires_companion_api` (the API auto-applied
with it, e.g. `PhysicsCollisionAPI` for `PhysicsMeshCollisionAPI`, else
null). **Always call this before `apply_physics_api`** so you know what
to author.

### `apply_physics_api(prim_path, api_name, instance_name?, attributes?, relationships?, scope?, clear_masking_overrides?, confirm_masked?)`
`instance_name` is required for PhysicsDriveAPI and PhysicsLimitAPI.

Apply a UsdPhysics applied API and author its attributes /
relationships. `attributes` keys must come from
`list_physics_api_properties` for the same `api_name`; unknown names
are refused. **Omit `scope` to let BowerBot auto-detect** — asset
placements write to the asset's `phy.usda`, scene-only prims write
to `scene.usda`. Pass `scope="scene"` explicitly only for a
per-placement override on an asset. The response reports `api_name`,
`instance_name`, `companion_api`, `attributes_set`, `relationships_set`,
and `scope`; asset-scope writes also return `asset_folder`,
`scene_prim_path`, `asset_prim_path`, and `cleared_masking_opinions`
(scene overrides deleted when `clear_masking_overrides=true`).

When authoring collision on a Mesh that belongs to a dynamic or
kinematic rigid body subtree, use
`api_name="PhysicsMeshCollisionAPI"` with
`attributes={"physics:approximation": "convexHull"}` (or another
convex token). `PhysicsCollisionAPI` is auto-applied alongside.
Authoring bare `PhysicsCollisionAPI` on a dynamic body's Mesh leaves
approximation at the schema default `"none"`, which is invalid for
dynamic bodies — the scene will not simulate correctly. See
Approximation rules above.

### `remove_physics_api(prim_path, api_name, instance_name?, scope?, clear_masking_overrides?, confirm_masked?)`
`instance_name` is required for PhysicsDriveAPI and PhysicsLimitAPI.

Remove a UsdPhysics applied API and its opinions. Dropping
PhysicsCollisionAPI cascades to PhysicsMeshCollisionAPI.

### `setup_physics_scene(name?, gravity_magnitude?, gravity_direction?)`
Create the scene's PhysicsScene singleton at `/Scene/Physics/<name>`
(default name `PhysicsScene`), or change an existing one. A new scene's
gravity defaults to `9.81 / metersPerUnit` in stage units, pointing
down the stage's up axis: `(0, 0, -1)` on a Z-up stage, `(0, -1, 0)`
on a Y-up stage. Calling it again changes only the values you pass;
the others keep what the scene has. Other physics tools never change
gravity. Call once per scene before authoring rigid bodies; static
colliders work without it. Returns the `gravity_magnitude` and
`gravity_direction` the scene now has, so you can report the actual
gravity back to the user.

### `list_physics_scenes()`
List every `UsdPhysics.Scene` prim under `/Scene/Physics` with name,
gravity magnitude, and gravity direction. Use to check what exists
before creating or removing a physics scene.

### `remove_physics_scene(name)`
Remove a `UsdPhysics.Scene` prim by name from `/Scene/Physics`. Use
when the user wants to clean up stale or duplicate physics scenes.

### `get_physics_summary(prim_path)`
Inspect every authored physics opinion on a prim and its
descendants. Returns two sections: `asset` (every opinion in the
asset's phy.usda — the whole asset, not only this prim's subtree; null
when the prim is not in an asset placement) and `scene` (scene.usda
physics opinions on this prim and its descendants). Use to check what's authored before
making changes, or to debug why a placement behaves differently from
the asset default.

## Pair filtering (PhysicsFilteredPairsAPI)

Turns off collisions between specific pairs: "the body and its front
wheels must not collide", "this door and its frame pass through each
other". Apply `PhysicsFilteredPairsAPI` to one side and list the other
side(s) in `physics:filteredPairs`:

`apply_physics_api(prim_path=<body>, api_name="PhysicsFilteredPairsAPI",
relationships={"physics:filteredPairs": [<wheel_L>, <wheel_R>]})`

- Both the prim and every target must be a rigid body, a collider or an
  articulation root (`PhysicsRigidBodyAPI`, `PhysicsCollisionAPI` or
  `PhysicsArticulationRootAPI` on the prim itself); anything else is
  refused, since filtering it would do nothing. Author those first.
- Scope works as for the other APIs: parts of one asset go in its
  `phy.usda` (shared by every placement; the targets must be in the same
  asset); prims in different placements go in `scene.usda`
  (`scope="scene"`).
- Pair filtering takes precedence over collision-group filtering.
  Prefer it when only a few pairs should pass through each other; use
  a collision group when a whole set should ignore another set (or
  itself).
- `remove_physics_api(..., api_name="PhysicsFilteredPairsAPI")` removes
  the filter; removing a target prim drops it from the list.

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
PhysicsScene prim**, so every scene-level physics prim (scene, joints,
groups) sits in one place.

### `create_or_update_collision_group(name, includes?, excludes?, filtered_groups?, invert_filter?, merge_group?)`
Create a new `UsdPhysicsCollisionGroup` at `/Scene/Physics/<name>` or
update an existing one. Each list-shaped arg replaces the existing
value; pass `None` (omit) to leave a property untouched on update.
`filtered_groups` accepts bare names that resolve to
`/Scene/Physics/<name>`; the targets must already exist (call this
tool to create them first otherwise).

### `remove_collision_group(name, force?)`
Remove a collision group. Refuses if other groups reference it via
`filteredGroups` unless `force=true`. Every removal drops the
relationship targets that named the group and reports them in
`scrubbed_dangling_refs`; `remove_physics_scene` and `remove_joint`
report the same field.

### `list_collision_groups()`
Return every group under `/Scene/Physics` (typed as
`PhysicsCollisionGroup`, distinguished from the PhysicsScene
sibling) with its membership (includes / excludes), filter rules,
and merge-group token. Call before authoring `filtered_groups` so
you know which names exist.

## Joints + articulations

Five typed joint prims are supported:

- `PhysicsRevoluteJoint` — hinge, one angular DOF (door pivot,
  robot elbow).
- `PhysicsPrismaticJoint` — slider, one linear DOF (piston, drawer).
- `PhysicsSphericalJoint` — ball-and-socket, three angular DOFs
  with cone limit (shoulder, hip).
- `PhysicsFixedJoint` — rigid weld, zero DOFs (bolt two parts
  together).
- `PhysicsDistanceJoint` — constrains distance between two points
  (rope, spring).

`PhysicsArticulationRootAPI` is an **applied API** (not a joint)
that marks a subtree as one articulation. Apply via the existing
`apply_physics_api` tool with `api_name="PhysicsArticulationRootAPI"`.
The UsdPhysics spec **forbids nesting** two ArticulationRootAPIs
in the same subtree; the tool refuses.

### Where joints live (verified canonical)

- **Asset-internal articulations** (robots, doors, characters): use
  `scope="asset"`. The joint lands inside the asset's `phy.usda` at
  `/<defaultPrim>/joints/<name>` (in the scene:
  `<placement>/asset/joints/<name>`) as a sibling of the body Xforms.
  The articulation ships with the asset, so every placement of the
  asset inherits it automatically.
- **Scene-spanning joints** (welding asset A to asset B, attaching
  a hook to a chain): use `scope="scene"` (default). The joint
  lands in `scene.usda` at `/Scene/Physics/<name>` as a flat
  sibling of `PhysicsScene` and collision groups.

### body0 / body1 semantics

- Both targets must be `UsdGeom.Xformable`.
- At least one of body0 / body1 must reach `PhysicsRigidBodyAPI`
  (self or ancestor). Empty / omitted target means "attach to
  world" — legal per spec but only when there's a real body on the
  other side.
- Convention is **body0 = parent, body1 = child** for articulated
  chains. UsdPhysics does not require it, but a joint's position is
  measured as body1 relative to body0, so swapping them inverts the
  sign of drive targets.

### Joint drives (PhysicsDriveAPI)

DriveAPI is a multi-apply API that adds motor/spring behavior to a
joint. It models a damped spring:
`force = stiffness * (targetPos - pos) + damping * (targetVel - vel)`.

To add a drive:
1. Call `list_physics_api_properties(api_name="PhysicsDriveAPI",
   instance_name="angular")` to discover the attribute names.
2. Call `apply_physics_api(prim_path=<joint>, api_name="PhysicsDriveAPI",
   instance_name="angular", attributes={...})`. Omit `scope`: a joint
   under `/Scene/Physics` is written to scene.usda, an asset joint
   (`<placement>/asset/joints/<name>`) to the asset's phy.usda;
   `scope="scene"` on an asset joint makes a per-placement override
   instead.

Valid instance names per joint type:
- **RevoluteJoint**: `angular`
- **PrismaticJoint**: `linear`
- **SphericalJoint**: drives not supported. For per-axis angular limits,
  apply PhysicsLimitAPI with instance_name `rotX` / `rotY` / `rotZ`
  directly to the SphericalJoint (see Joint limits below).
- **FixedJoint**: not supported
- **DistanceJoint**: not supported

Drive modes (`drive:<instance>:physics:type`):
- `force`: mass-dependent (default)
- `acceleration`: mass-independent (preferred for robotics)

### Joint limits (PhysicsLimitAPI)

LimitAPI is a multi-apply API that constrains a joint's range of
motion beyond its built-in limits.

RevoluteJoint and PrismaticJoint have built-in `lowerLimit` /
`upperLimit` attributes directly on the joint schema. Use those for
simple range clamping. LimitAPI is for additional axis constraints
on SphericalJoint (rotX/rotY/rotZ) and DistanceJoint (distance).

Valid instance names per joint type:
- **RevoluteJoint**: `angular`
- **PrismaticJoint**: `linear`
- **SphericalJoint**: `rotX`, `rotY`, `rotZ`
- **FixedJoint**: not supported
- **DistanceJoint**: `distance`

### Joint tools

#### `list_joint_properties(joint_type)`
Schema-registry introspection. Returns attribute names, types,
defaults, allowed-token sets for the joint type. ALWAYS call this
before `create_joint` so you know what attributes the joint
accepts (axis, lower/upper limits, break force/torque, etc.). Do
NOT include `physics:body0` / `physics:body1` in your attribute
list; those are set via the dedicated `body0` / `body1` params on
`create_joint`.

#### `create_joint(joint_type, name, body0?, body1?, scope?, asset_anchor_prim_path?, attributes?)`
Create a typed joint connecting two bodies. `scope="scene"`
(default) writes to `/Scene/Physics/<name>`; `scope="asset"` writes
to `/<defaultPrim>/joints/<name>` inside the asset's `phy.usda` (and
translates body paths to asset-local namespace). For asset scope, give
at least one body; every body you give must be inside one placement of
the same asset, and BowerBot finds the asset folder from them.

#### `remove_joint(scope?, prim_path?, name?, asset_anchor_prim_path?)`
Remove a joint. scope="scene" + prim_path = drop a scene-level
joint. scope="asset" + name + asset_anchor_prim_path = drop a
joint from the asset's `phy.usda`. Joints are leaves; no cascade.

#### `list_joints(scope?, under_prim_path?, asset_anchor_prim_path?)`
List every typed joint prim. scope="scene" walks the scene (or a
subtree via under_prim_path); scope="asset" walks `phy.usda`. Each
entry includes joint_type, body0, body1, authored attributes, and
applied APIs.
