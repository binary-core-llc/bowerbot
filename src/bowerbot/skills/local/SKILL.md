<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
# Local Asset Cache

You have tools to search USD assets on disk. Each result is classified
by category so you know which tool to use.

## CRITICAL RULE
NEVER tell the user an asset does not exist without calling
`search_assets` or `list_assets` first. You MUST always search
before answering questions about asset availability. If the first
search returns no results, try broader keywords or `list_assets`
to show everything available.

## When to Use
- When the user asks "what do I have", "do I have a table", etc.
- When the user asks for assets without specifying a source
- When you want to check if an asset was already downloaded
- Before searching cloud providers — local is faster and free
- When the user asks to apply materials

## Supported Formats
USD-family files: .usd, .usda, .usdc, .usdz

## Asset Categories

Every result includes a `category` field:

| Category | What it is | Which tool to use |
|----------|-----------|-------------------|
| `package` | ASWF asset folder (geo + mtl + textures) | `place_asset` |
| `geo` | Geometry (3D meshes, models) | `place_asset` |
| `mtl` | Material definitions (under `/mtl/`) | `bind_material` |

### ASWF Asset Folders
An asset folder follows the ASWF USD Working Group standard:
```
single_table/
  single_table.usd   <- root file (same name as folder)
  geo.usd            <- geometry
  mtl.usd            <- materials + bindings
  maps/              <- textures
```

These are detected automatically and returned as a single `package` entry.
Internal files (geo.usd, mtl.usd) are NOT listed separately.
When placing a package, `place_asset` copies the entire folder.

Use the `category` filter parameter to narrow results:
- `search_assets("table", category="package")` — find asset packages
- `search_assets("wood", category="mtl")` — find material files
- `list_assets(category="package")` — list all asset packages

## Behavior
- Detects ASWF asset folders first, then scans loose files
- Classifies each loose file by inspecting its USD contents
- Includes assets downloaded by any cloud provider (Sketchfab, etc.)
- Use the `category` field to pick the right tool — never guess
