<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
# Local Asset Cache

You have tools to search USD assets on disk. Each result is classified
by category so you know which tool to use.

## When to Use
- When the user asks for assets without specifying a source
- When you want to check if an asset was already downloaded
- Before searching cloud providers — local is faster and free
- When the user asks to apply materials or look files

## Supported Formats
USD-family files: .usd, .usda, .usdc, .usdz

## Asset Categories

Every result includes a `category` field:

| Category | What it is | Which tool to use |
|----------|-----------|-------------------|
| `geometry` | 3D meshes, models | `place_asset` |
| `material` | Material definitions (under `/mtl/`) | `bind_material` |
| `look` | Look files (geometry + materials + bindings) | `apply_look` |

Use the `category` filter parameter to narrow results:
- `search_assets("wood", category="material")` — find wood materials
- `search_assets("table", category="look")` — find table look files
- `list_assets(category="material")` — list all materials

## Behavior
- Searches by keyword matching against filenames
- Classifies each file by inspecting its USD contents
- Includes assets downloaded by any cloud provider (Sketchfab, etc.)
- Use the `category` field to pick the right tool — never guess