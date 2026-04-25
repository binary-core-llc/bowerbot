<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
You have tools for finding texture files in the user's asset library.

## When to Use
- When the user asks for an HDRI or environment map for a `DomeLight`
- When the user asks for material maps (diffuse, normal, roughness, etc.)
- Before asking the user for a file path — check whether the texture
  already exists locally

## Supported Formats
- **HDRI**: `.hdr`, `.hdri`, `.exr` — for dome lights and environment lighting
- **Material**: `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.tga`, `.bmp`
  — for surface textures

## Workflow
1. Use `search_textures` to find a texture by keyword
2. If the search returns nothing, use `list_textures` to see what's available
3. Use the `category` filter to narrow results (`hdri` for dome lights,
   `material` for surfaces, `all` to see both)
4. Pass the returned `path` to the appropriate tool:
   - HDRI files → `create_light` with `light_type: DomeLight` and the
     `texture` parameter
   - Material maps (diffuse / normal / roughness / etc.) are inputs to
     materials. To apply a look, use `bind_material` for an existing
     material `.usd` / `.usda` / `.usdc` file from the library, or
     `create_material` for a procedural MaterialX material.

## Notes
- Textures live in the user's asset library (`assets_dir` from
  `~/.bowerbot/config.json`). Anything an external skill (e.g.
  Sketchfab) downloads also lands there and becomes searchable.
