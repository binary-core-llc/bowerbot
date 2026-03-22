<!-- Copyright 2026 Binary Core LLC | SPDX-License-Identifier: Apache-2.0 -->
# Textures Skill

You have tools to search for texture files on disk.

## When to Use
- When the user asks for an HDRI or environment map for a dome light
- When the user asks for material textures (diffuse, normal, roughness maps)
- Before asking the user for a file path — check if the texture is already available locally

## Supported Formats
- **HDRI**: .hdr, .hdri, .exr — for dome lights and environment lighting
- **Material**: .png, .jpg, .jpeg, .tif, .tiff, .tga, .bmp — for surface textures

## Workflow
1. Use `search_textures` to find textures by keyword
2. If search returns no results, use `list_textures` to see everything available
3. Use the `category` filter to narrow results (e.g., `hdri` for dome lights)
4. Pass the returned `path` to the appropriate tool:
   - HDRI files → `create_light` with `light_type: DomeLight` and `texture` parameter
   - Material textures → future material assignment tools

## Notes
- This skill searches LOCAL directories only — textures from remote providers (PolyHaven, DAM) are handled by their own skills
- Textures downloaded by other skills are cached locally and become searchable here
