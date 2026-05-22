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

Before any phy.usda write, BowerBot scans every placement of the
asset in the open scene for authored opinions on the same prim +
attribute. If any are found, the tool refuses with a list of
conflicting `(placement_path, kind, key)` triples. Resolve with one
of three flags:

- `clear_masking_overrides=true` — remove the scene.usda opinions
  first, then write phy.usda. Use when the DCC override was
  accidental.
- `confirm_masked=true` — write phy.usda anyway; scene.usda overrides
  keep winning on those placements. Use when overrides are
  intentional and you only want to update the asset default.
- *(PR #2)* per-placement scene-level overrides will land in a
  follow-up release; until then, scene.usda overrides must be
  authored via your DCC.

## USDZ / Apple Quick Look

Apple Quick Look uses a separate `Preliminary_Physics*` schema set
that pre-dates UsdPhysics. BowerBot emits only the standard
UsdPhysics APIs. USDZ packages will carry the physics data and play
correctly in any UsdPhysics-aware viewer (Omniverse, Houdini,
usdview); Quick Look will ignore it for now.

## Identifying the asset

Every physics tool takes `prim_path`: a SCENE prim path of any
placement (e.g. `/Scene/Models/Chair_01/asset/Body` for a leaf, or
`/Scene/Models/Chair_01` for the asset root). BowerBot resolves the
asset folder and translates the path into the asset's namespace
before writing. Use `list_scene` and `list_prim_children` to discover
the right scene paths.
