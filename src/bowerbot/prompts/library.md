<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
You have tools for finding USD assets in the user's library. Each
result is classified by category so you know which tool to use next.

## CRITICAL RULE
NEVER tell the user an asset does not exist without calling
`search_assets` or `list_assets` first. You MUST always search before
answering questions about asset availability. If the first search
returns no results, try broader keywords or `list_assets` to show
everything available.

## When to Use
- When the user asks "what do I have", "do I have a table", etc.
- When the user asks for assets without specifying a source
- When you want to check whether an asset was already downloaded
- Before searching cloud providers — local is faster and free
- When the user asks to apply materials

## Supported Formats
USD-family files: `.usd`, `.usda`, `.usdc`, `.usdz`

## Asset Categories

Every result is `{name, path, format, category}`, plus `cannot_be_used`
(the reason) when BowerBot would refuse to place it. Use `category` to pick
the next tool, and forward the result's `path` verbatim as that tool's
file argument: `path` -> `place_asset`'s `asset_file_path` for
`package`/`geo`, or `path` -> `bind_material`'s `material_file` for `mtl`.

| Category | What it is | Which tool to use |
|----------|-----------|-------------------|
| `package` | ASWF asset folder (geo + mtl + textures) | `place_asset` |
| `geo` | Geometry (3D meshes, models) | `place_asset` |
| `mtl` | Material definitions (under `/mtl/`) | `bind_material` |

### The shapes BowerBot accepts

An asset can be placed only when it has one of these shapes:

- **Geometry file** (`geo`): a single `.usd`/`.usda`/`.usdc` with one root
  prim and nothing but geometry: no materials, no lights, no links to other
  files, no texture paths. It is wrapped into a fresh asset folder when placed.
- **Asset folder** (`package`): a folder with a root file named like the
  folder, `geo.usda` (geometry only), and optionally `mtl.usda`, `lgt.usda`,
  `phy.usda`, `variants.usda` and extra geometry files for LODs:
  ```
  single_table/
    single_table.usda   <- root file, named like the folder
    geo.usda            <- geometry
    mtl.usda            <- materials + bindings
    maps/               <- textures, inside the folder
  ```
  Nothing in it points outside the folder. Its layer files are not listed
  separately; `place_asset` copies the whole folder.
- **`.usdz`**: placed as it is. BowerBot reads its units and up axis and fits the placement to the project. If the `.usdz` does not declare them, it is taken to match the project; if it doesn't, export it again with the right values.

Anything else is refused, and nothing is copied. A result that would be
refused carries `cannot_be_used` with the reason: do not pass it to
`place_asset`; tell the user what the asset needs instead.

- `search_assets("table")` searches everywhere by name; filter the returned list by the result's `category` field if needed
- `list_assets(category="package")` browses every asset folder in the library

## Behavior
- An asset folder is a top-level folder with a root file named like it;
  every other USD file is listed as a single file, found recursively
- Search matches both the folder name and the root file stem
- Classifies each single file by inspecting its USD contents
- Includes assets downloaded by any cloud provider (Sketchfab, etc.)
- Use the `category` field to pick the right tool — never guess
