<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
You have tools for finding USD assets in the user's library. Each
result is classified by category so you know which tool to use next.

## CRITICAL RULE
NEVER tell the user an asset does not exist without calling
`search_assets` or `list_assets` first. You MUST always search before
answering questions about asset availability. If the first search
returns no results, try broader keywords or `list_assets` to show
everything available.

The library is the only place BowerBot takes source files from, and
tools take names, never paths. If the user has a file somewhere else,
ask them to copy it into the library first, then search for it and use
its name.

## When to Use
- When the user asks "what do I have", "do I have a table", etc.
- When the user asks for assets without specifying a source
- When you want to check whether an asset was already downloaded
- Before searching cloud providers — local is faster and free
- When the user asks to apply materials

## Supported Formats
USD-family files: `.usd`, `.usda`, `.usdc`, `.usdz`

## Asset Categories

Every result is `{name, location, format, category}`. Use `category` to
pick the next tool, and pass the result's `name`: `name` ->
`place_asset`'s `asset` (and every placing tool: `place_layout`,
scatter, model-selection variants) for `package`/`geo`, or `name` ->
`bind_material`'s `material_asset` for `mtl`. `location` is where the
asset sits inside the library; pass it instead of the name only when
two results share a name. Never pass a file path: tools refuse them.
After a skill downloads a model into the library (e.g. Sketchfab), place
it by its name: the file name without its extension.

| Category | What it is | Which tool to use |
|----------|-----------|-------------------|
| `package` | ASWF asset folder (geo + mtl + textures) | `place_asset` |
| `geo` | Geometry (3D meshes, models) | `place_asset` |
| `mtl` | Material definitions (under `/mtl/`) | `bind_material` |

### ASWF Asset Folders
A typical asset folder follows the ASWF USD Working Group standard:
```
single_table/
  single_table.usda   <- root file
  geo.usda            <- geometry
  mtl.usda            <- materials + bindings
  maps/               <- textures
```

Detection is composition-aware: a folder still counts as a `package`
when the root filename does not match the folder name (e.g.
`wall/root.usd` next to `wall/geo.usd`). Internal layer files (geo,
mtl, lgt, contents, phy, variants) are NOT listed separately. When
placing a package, `place_asset` copies its root and every file the
root depends on (files it never references are left out) and makes the
copy self-contained inside the project.

Loose files at the library root (e.g. `library/table.usda`) are
classified individually and wrapped into a fresh ASWF folder when
placed.

- `search_assets("table")` searches everywhere by name; filter the returned list by the result's `category` field if needed
- `list_assets(category="package")` browses every asset folder in the library

## Behavior
- Detects ASWF asset folders at the top level of the library, then
  scans loose files recursively
- Search matches both the folder name and the root file stem
- Classifies each loose file by inspecting its USD contents
- Includes assets downloaded by any cloud provider (Sketchfab, etc.)
- Use the `category` field to pick the right tool — never guess
