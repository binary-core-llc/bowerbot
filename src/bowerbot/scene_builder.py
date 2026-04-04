# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""SceneBuilder — adapter between the LLM tool-calling layer and the engine.

This is BowerBot's core product: it holds the state of the scene
being built (the current USD stage) and provides tools to create,
populate, validate, and package it.

SceneBuilder is NOT a skill and NOT an engine module. Skills are
extensions (asset providers, integrations). The engine is pure USD
manipulation. SceneBuilder is the adapter that translates LLM tool
calls into engine operations and wraps results for the agent.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bowerbot.project import Project

from bowerbot.config import SceneDefaults
from bowerbot.engine.asset_assembler import AssetAssembler
from bowerbot.engine.packager import Packager
from bowerbot.engine.scene_graph import SceneGraphBuilder
from bowerbot.engine.stage_writer import StageWriter
from bowerbot.engine.validator import SceneValidator
from bowerbot.schemas import ASWFLayerNames, AssetMetadata, LightParams, LightType, SceneObject
from bowerbot.skills.base import Tool, ToolResult
from bowerbot.utils.file_utils import copy_texture_to_project
from bowerbot.utils.naming import safe_file_name, safe_prim_name
from bowerbot.utils.usd_utils import (
    find_asset_references,
    find_texture_references,
    iter_prim_ref_paths,
    resolve_asset_dir_for_prim,
)

logger = logging.getLogger(__name__)

# Scene building instructions — merged into the agent's system prompt.
SCENE_BUILDER_PROMPT = """\
You have tools to create and manipulate OpenUSD scenes.

## Workflow
1. The scene is created automatically with the project — you do NOT
   need to call `create_stage`. If the scene already exists, it is
   reopened with its current contents.
2. Place assets using `place_asset` with coordinates in meters
3. Use `move_asset` to reposition an existing object (do NOT call
   `place_asset` again — that creates a duplicate)
4. Use `compute_grid_layout` to plan evenly spaced arrangements
5. Use `list_scene` to show the user what's currently in the scene
6. Use `rename_prim` or `remove_prim` when the user wants to reorganize
7. After removing assets from the scene, tell the user that the asset
   folder still exists in the project's assets directory. Ask if they
   want to delete it. If they confirm, use `delete_project_asset`.
   BowerBot will scan all USD files in the project to ensure the
   asset is not referenced elsewhere before deleting.
8. ALWAYS call `validate_scene` before packaging
8. Call `package_scene` to produce the final .usdz

## USD Rules
- metersPerUnit = 1.0 (always, no exceptions)
- upAxis = "Y"
- Assets are added as USD references (not copies)
- Every stage has a defaultPrim set automatically

## Scene Hierarchy
Groups are created on demand when assets are placed — the scene
starts empty with only the /Scene root prim. Use these standard
group names when placing assets:
- /Scene/Architecture, /Scene/Furniture, /Scene/Products,
  /Scene/Lighting, /Scene/Props

The user may request custom group names instead — use whatever
they prefer. Use `rename_prim` to reorganize after placement.

CRITICAL: When reporting the scene state to the user, use
`list_scene` to check what actually exists — do NOT assume
groups exist just because they are listed above.

## Spatial Reasoning
- Tables, chairs, shelves → floor (Y = 0)
- Ceiling lights, pendants → ceiling (Y = room height, typically 2.7)
- Wall-mounted items → against walls with 0.01m offset
- Maintain minimum 1.2m walkways between furniture groups

### Placing objects on surfaces
Do NOT guess surface heights or positions. ALWAYS call `list_scene`
first and use the `bounds` of the support object:
- `translate_y` = support `bounds.max.y` (surface height)
- `translate_x` must be between support `bounds.min.x` and
  `bounds.max.x` (stay within the surface)
- `translate_z` must be between support `bounds.min.z` and
  `bounds.max.z` (stay within the surface)

When arranging multiple objects on the same surface, also check
each object's own bounds to ensure they do not overlap or hang
off the edge.

## Lighting

Use `create_light` to add native USD lights. There are two levels:

### Where does the light go?
When the user asks to create a light, determine if it belongs to the
**scene** or to a **specific asset**:
- "add a sun" / "set up lighting" / "add an HDRI" → **scene light**
- "add a bulb to the lamp" / "this lamp needs a light" → **asset light**
- Ambiguous ("add a light") → ASK the user: "Should this be a scene
  light (general illumination) or attached to a specific asset?"

### Scene-level lights (default)
Lights that belong to the scene — sun, environment, key/fill/rim.
These go in `/Scene/Lighting` and are authored in `scene.usda`.
Use these for general illumination and environment setup.

### Asset-level lights
Lights that belong to a specific asset — a lamp's bulb, a candle's
flame, a neon sign's glow. These travel with the asset.
Set `asset_prim_path` to the asset's prim path to create the light
in the asset's `lgt.usda` file instead of the scene.

CRITICAL: For asset lights, translate values are OFFSETS from the
asset's bounding box surfaces, NOT absolute positions.
BowerBot reads the geometry bounds and computes the final position:
- translate_y = 1.0 → 1 meter above the top surface
- translate_y = -0.5 → 0.5m below the bottom surface
- translate_x = 0.5 → 0.5m to the right of the right face
- translate_x = -0.5 → 0.5m to the left of the left face
- If no translate is provided → defaults to 0.5m above top center

Do NOT use scene world coordinates for asset lights.
Values are in meters — BowerBot converts to asset units.

Example: "add a point light to the desk lamp" → use `asset_prim_path`
pointing to the lamp's prim in the scene.

### Light types
- **DistantLight** — sun/directional. Only rotation matters.
  Use `rotate_x` for sun angle (-45 = afternoon). `angle: 0.53` = sun.
- **DomeLight** — environment/HDRI. Set `texture` to HDRI path.
  Intensity typically 1.0. No rotation needed.
- **SphereLight** — point/omni. Emits in all directions. No rotation.
  Radius 0.05-0.1 for lamps, bulbs.
- **RectLight** — rectangular area. Default faces -Z direction.
- **DiskLight** — circular area. Default faces -Z direction.
- **CylinderLight** — tube. Radius 0.02, length 1.2.

### Light rotation
Directional lights (DiskLight, RectLight) default to facing -Z.
Set rotation based on where the user wants the light to point:
- Facing DOWN onto a surface below: `rotate_x: -90`
- Facing UP from below: `rotate_x: 90`
- Facing LEFT: `rotate_y: 90`
- Facing RIGHT: `rotate_y: -90`
- Facing FORWARD (+Z): `rotate_y: 180`
Always choose rotation based on the user's description of what the
light should illuminate. Ask the user if the direction is ambiguous.

### Modifying lights
When the user wants to adjust an existing light (intensity, color,
size, position, rotation), use `update_light` — do NOT create a new
light. `update_light` modifies the existing light in place.

`update_light` works for BOTH scene-level and asset-level lights.
Just provide the light's `prim_path` — use `list_scene` to find it.
BowerBot automatically detects whether it's a scene or asset light.

Only use `create_light` when adding a brand new light.

### Removing lights
Use `remove_light` to delete a light. Works for both scene-level
and asset-level lights — provide the `prim_path`.

If the result includes a `texture_file` field (DomeLight with HDRI),
the texture file still exists in the project's `textures/` folder.
Ask the user if they want to delete it. If they confirm, use
`delete_project_texture` with the file name. BowerBot will scan all
USD files in the project to ensure it is not referenced elsewhere
before deleting.

### CRITICAL: Do NOT switch light levels
If a light was created as an **asset light**, it MUST stay an asset
light when the user asks to move, reposition, or adjust it. Use
`update_light` to change its position/rotation — do NOT remove it
and recreate as a scene light.

Only switch from asset light to scene light (or vice versa) if the
user **explicitly** asks for it (e.g. "make this a scene light
instead").

When the user says "move the light next to the table" and the light
is an asset light, update its offset values — do NOT create a new
scene light.

### Defaults
- Intensity: 1000 for interior, 500 for Distant, 1.0 for Dome
- Color: warm white (1.0, 0.9, 0.8), cool (0.9, 0.95, 1.0)
- Scene lights go in `/Scene/Lighting`
- Asset lights go in the asset's `lgt.usda` under `/{asset}/lgt/`

## Materials

BowerBot applies existing material files — it does NOT create materials.
Material files are `.usda` files with material definitions under `/mtl/`.

Materials are written into the asset folder's `mtl.usd`, NOT the scene file.
The scene stays clean — only references to asset folders.

### Material binding workflow (CRITICAL)
1. Search for the material using `search_assets` with category "mtl"
2. If the search returns MORE THAN ONE material, you MUST stop and list
   ALL matching materials to the user with their names. Ask the user to
   choose. Do NOT pick a material on their behalf. This is mandatory.
3. Call `list_prim_children` on the target asset to discover its internal parts
   (table top, legs, frame, etc.) — NEVER skip this step
4. Show the user the available parts and ask which ones to apply the material to
5. Call `bind_material` with the EXACT mesh prim path from `list_prim_children`
   — NEVER bind to the top-level prim, always the specific mesh part
6. Use `list_materials` to verify, `remove_material` to clear

### Key rules
- ALWAYS call `list_prim_children` before `bind_material`
- Materials go into the asset folder's mtl.usd — never into scene.usda
- BowerBot does NOT create materials — only applies existing ones
- `bind_material` only works on ASWF asset folders (not USDZ)
- For USDZ assets, materials are baked in — cannot override

## ASWF Asset Folders

BowerBot follows ASWF USD Working Group guidelines for asset structure.

### How it works
- `place_asset` with a loose .usda file automatically creates an ASWF folder:
  ```
  project/assets/chair/
    chair.usd    <- root (sublayers geo.usd)
    geo.usd      <- geometry
  ```
- `bind_material` adds materials incrementally:
  ```
  project/assets/chair/
    chair.usd    <- root (now sublayers geo.usd + mtl.usd)
    geo.usd      <- geometry
    mtl.usd      <- materials defined inline + bindings
  ```
- `place_asset` with an existing ASWF folder copies the entire folder
- `place_asset` with a USDZ copies the single file (no folder)

### Key rules
- Loose geometry is wrapped in ASWF folders on placement
- USDZ files stay as-is (self-contained)
- The scene.usda only contains references — no material sublayers
- Existing ASWF folders are copied whole, preserving structure

## Room Defaults
- Width: 10m (X axis)
- Height: 3m (Y axis)
- Depth: 8m (Z axis)
- Origin (0,0,0) is back-left corner at floor level
- Center of room: (5.0, 0.0, 4.0)
"""


class SceneBuilder:
    """Adapter between LLM tool calls and the USD engine.

    Maintains engine instances (StageWriter, AssetAssembler, etc.)
    across tool calls so the LLM can create a stage, place assets
    into it, validate, and package.
    """

    def __init__(
        self,
        scene_defaults: SceneDefaults | None = None,
    ) -> None:
        defaults = scene_defaults or SceneDefaults()

        self.writer = StageWriter(
            meters_per_unit=defaults.meters_per_unit,
            up_axis=defaults.up_axis,
        )
        self.graph = SceneGraphBuilder(room_bounds=defaults.default_room_bounds)
        self.validator = SceneValidator(
            meters_per_unit=defaults.meters_per_unit,
            up_axis=defaults.up_axis,
        )
        self.packager = Packager()
        self.assembler = AssetAssembler()

        self._project: Project | None = None
        self._stage_path: Path | None = None
        self._assets_dir: Path | None = None
        self._object_count: int = 0

    def set_project(self, project: Project) -> None:
        """Bind to a project. All output goes into the project folder."""
        self._project = project
        self._stage_path = project.scene_path
        self._assets_dir = project.assets_dir

        # If the scene file already exists, reopen it
        if self._stage_path.exists():
            self.writer.open_stage(self._stage_path)
            objects = self.writer.list_prims()
            self._object_count = len(objects)
            logger.info(f"Resumed project '{project.name}' with {self._object_count} object(s)")

    def get_prompt(self) -> str:
        """Return scene building instructions for the system prompt."""
        return SCENE_BUILDER_PROMPT

    def get_tools(self) -> list[dict[str, Any]]:
        """Return all tools in LLM function-calling schema format."""
        return [tool.to_llm_schema() for tool in self._tool_definitions()]

    def get_tool_names(self) -> set[str]:
        """Return the set of tool names owned by this builder."""
        return {t.name for t in self._tool_definitions()}

    async def execute_tool(
        self, tool_name: str, params: dict[str, Any],
    ) -> ToolResult:
        """Execute a tool by name with the given parameters."""
        try:
            match tool_name:
                case "create_stage":
                    return self._create_stage(params)
                case "place_asset":
                    return self._place_asset(params)
                case "compute_grid_layout":
                    return self._compute_grid_layout(params)
                case "validate_scene":
                    return self._validate_scene()
                case "package_scene":
                    return self._package_scene()
                case "list_scene":
                    return self._list_scene()
                case "rename_prim":
                    return self._rename_prim(params)
                case "move_asset":
                    return self._move_asset(params)
                case "remove_prim":
                    return self._remove_prim(params)
                case "create_light":
                    return self._create_light(params)
                case "update_light":
                    return self._update_light(params)
                case "remove_light":
                    return self._remove_light(params)
                case "bind_material":
                    return self._bind_material(params)
                case "list_materials":
                    return self._list_materials()
                case "remove_material":
                    return self._remove_material(params)
                case "list_prim_children":
                    return self._list_prim_children(params)
                case "list_project_assets":
                    return self._list_project_assets(params)
                case "delete_project_asset":
                    return self._delete_project_asset(params)
                case "delete_project_texture":
                    return self._delete_project_texture(params)
                case _:
                    return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
        except Exception as e:
            logger.exception(f"Scene builder tool error: {tool_name}")
            return ToolResult(success=False, error=str(e))

    # ── Tool Definitions ──────────────────────────────────────────

    @staticmethod
    def _tool_definitions() -> list[Tool]:
        return [
            Tool(
                name="create_stage",
                description=(
                    "Create a new empty USD stage with standard BowerBot hierarchy. "
                    "Call this FIRST before placing any assets. "
                    "Creates: /Scene/Architecture, /Scene/Furniture, /Scene/Products, "
                    "/Scene/Lighting, /Scene/Props"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Name for the scene file (without extension). Example: 'retail_store'",
                        },
                    },
                    "required": ["filename"],
                },
            ),
            Tool(
                name="place_asset",
                description=(
                    "Place a 3D asset into the current scene. The asset is added as a "
                    "USD reference at the specified prim path with the given transform. "
                    "Use the standard hierarchy: Furniture, Products, Lighting, Props."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "asset_file_path": {
                            "type": "string",
                            "description": "Local file path to the .usda/.usdc/.usdz asset.",
                        },
                        "asset_name": {
                            "type": "string",
                            "description": "Human-readable name for this asset instance.",
                        },
                        "group": {
                            "type": "string",
                            "enum": ["Architecture", "Furniture", "Products", "Lighting", "Props"],
                            "description": "Which scene group to place the asset in.",
                        },
                        "translate_x": {
                            "type": "number",
                            "description": "X position in meters. 0 = left edge of room.",
                        },
                        "translate_y": {
                            "type": "number",
                            "description": "Y position in meters. 0 = floor, 2.7 = typical ceiling.",
                        },
                        "translate_z": {
                            "type": "number",
                            "description": "Z position in meters. 0 = back wall.",
                        },
                        "rotate_y": {
                            "type": "number",
                            "description": (
                                "Rotation around Y axis in "
                                "degrees. 0 = facing forward."
                            ),
                            "default": 0.0,
                        },
                        "fix_root_prim": {
                            "type": "boolean",
                            "description": (
                                "If true, automatically wraps "
                                "a non-Xform root prim under "
                                "an Xform to comply with ASWF "
                                "guidelines. Only use when the "
                                "user confirms they want the fix."
                            ),
                            "default": False,
                        },
                    },
                    "required": [
                        "asset_file_path",
                        "asset_name",
                        "group",
                        "translate_x",
                        "translate_y",
                        "translate_z",
                    ],
                },
            ),
            Tool(
                name="compute_grid_layout",
                description=(
                    "Compute evenly spaced positions for N objects in a grid, "
                    "centered in the room. Returns a list of (x, z) positions. "
                    "Use this to plan furniture layouts before calling place_asset."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "Number of objects to arrange.",
                        },
                        "spacing": {
                            "type": "number",
                            "description": "Distance between objects in meters.",
                            "default": 2.0,
                        },
                    },
                    "required": ["count"],
                },
            ),
            Tool(
                name="validate_scene",
                description=(
                    "Run validation checks on the current scene. "
                    "Checks: defaultPrim, metersPerUnit, upAxis, and reference resolution. "
                    "Call this after placing all assets and BEFORE packaging."
                ),
                parameters={"type": "object", "properties": {}},
            ),
            Tool(
                name="package_scene",
                description=(
                    "Package the current scene into a .usdz file for distribution. "
                    "Call validate_scene first to ensure correctness. "
                    "Returns the path to the output .usdz file."
                ),
                parameters={"type": "object", "properties": {}},
            ),
            Tool(
                name="list_scene",
                description=(
                    "List all objects currently in the scene with their prim paths, "
                    "asset names, and positions. Use this to show the user what's "
                    "in the scene so they can request changes."
                ),
                parameters={"type": "object", "properties": {}},
            ),
            Tool(
                name="rename_prim",
                description=(
                    "Move/rename a prim to a new path in the scene hierarchy. "
                    "This changes the USD prim path, letting the user reorganize "
                    "the scene structure. The new path can be any valid USD path."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "old_path": {
                            "type": "string",
                            "description": "Current prim path (e.g. '/Scene/Products/mug_01')",
                        },
                        "new_path": {
                            "type": "string",
                            "description": "New prim path (e.g. '/Scene/MyDisplay/CoffeeMug')",
                        },
                    },
                    "required": ["old_path", "new_path"],
                },
            ),
            Tool(
                name="move_asset",
                description=(
                    "Move an existing object to a new position. "
                    "Use this instead of place_asset when repositioning "
                    "an object that is already in the scene."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prim_path": {
                            "type": "string",
                            "description": (
                                "Prim path of the object to move "
                                "(e.g. '/Scene/Products/Mug_01'). "
                                "Use list_scene to find prim paths."
                            ),
                        },
                        "translate_x": {
                            "type": "number",
                            "description": "New X position in meters.",
                        },
                        "translate_y": {
                            "type": "number",
                            "description": "New Y position in meters.",
                        },
                        "translate_z": {
                            "type": "number",
                            "description": "New Z position in meters.",
                        },
                        "rotate_y": {
                            "type": "number",
                            "description": (
                                "Rotation around Y axis in degrees."
                            ),
                            "default": 0.0,
                        },
                    },
                    "required": [
                        "prim_path",
                        "translate_x",
                        "translate_y",
                        "translate_z",
                    ],
                },
            ),
            Tool(
                name="remove_prim",
                description=(
                    "Remove an object from the scene by its prim path."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prim_path": {
                            "type": "string",
                            "description": "Prim path to remove (e.g. '/Scene/Furniture/Table_01')",
                        },
                    },
                    "required": ["prim_path"],
                },
            ),
            Tool(
                name="create_light",
                description=(
                    "Create a USD light. By default creates a "
                    "scene-level light in /Scene/Lighting. If "
                    "asset_prim_path is provided, creates an "
                    "asset-level light in that asset's lgt.usda "
                    "(e.g. a lamp's bulb light). For asset lights, "
                    "use offset_y instead of translate — BowerBot "
                    "computes the position from the geometry bounds."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "asset_prim_path": {
                            "type": "string",
                            "description": (
                                "Optional: prim path of an asset "
                                "in the scene to attach the light "
                                "to. If provided, the light is "
                                "created in the asset's lgt.usda. "
                                "If omitted, the light is created "
                                "as a scene-level light."
                            ),
                        },
                        "light_type": {
                            "type": "string",
                            "enum": [t.value for t in LightType],
                            "description": (
                                "Type of light. DistantLight = sun/directional, "
                                "DomeLight = environment/HDRI, SphereLight = point, "
                                "RectLight = area, DiskLight = round area, "
                                "CylinderLight = tube."
                            ),
                        },
                        "light_name": {
                            "type": "string",
                            "description": "Human-readable name (e.g. 'Key_Light', 'Sun').",
                        },
                        "intensity": {
                            "type": "number",
                            "description": "Light intensity. Default: 1000 for most lights, 1.0 for DomeLight.",
                            "default": 1000.0,
                        },
                        "color_r": {
                            "type": "number",
                            "description": "Red channel (0-1). Default: 1.0.",
                            "default": 1.0,
                        },
                        "color_g": {
                            "type": "number",
                            "description": "Green channel (0-1). Default: 1.0.",
                            "default": 1.0,
                        },
                        "color_b": {
                            "type": "number",
                            "description": "Blue channel (0-1). Default: 1.0.",
                            "default": 1.0,
                        },
                        "translate_x": {
                            "type": "number",
                            "description": "X position in meters.",
                            "default": 0.0,
                        },
                        "translate_y": {
                            "type": "number",
                            "description": "Y position in meters.",
                            "default": 0.0,
                        },
                        "translate_z": {
                            "type": "number",
                            "description": "Z position in meters.",
                            "default": 0.0,
                        },
                        "rotate_x": {
                            "type": "number",
                            "description": "Rotation around X axis in degrees.",
                            "default": 0.0,
                        },
                        "rotate_y": {
                            "type": "number",
                            "description": "Rotation around Y axis in degrees.",
                            "default": 0.0,
                        },
                        "rotate_z": {
                            "type": "number",
                            "description": "Rotation around Z axis in degrees.",
                            "default": 0.0,
                        },
                        "angle": {
                            "type": "number",
                            "description": "DistantLight only: angular size in degrees. 0.53 = realistic sun.",
                        },
                        "texture": {
                            "type": "string",
                            "description": "DomeLight only: path to HDRI texture file.",
                        },
                        "radius": {
                            "type": "number",
                            "description": "SphereLight/DiskLight/CylinderLight: light radius in meters.",
                        },
                        "width": {
                            "type": "number",
                            "description": "RectLight only: width in meters.",
                        },
                        "height": {
                            "type": "number",
                            "description": "RectLight only: height in meters.",
                        },
                        "length": {
                            "type": "number",
                            "description": "CylinderLight only: length in meters.",
                        },
                    },
                    "required": ["light_type", "light_name"],
                },
            ),
            Tool(
                name="update_light",
                description=(
                    "Update an existing light's parameters. "
                    "Works for both scene-level and asset-level "
                    "lights. Only modifies values you provide — "
                    "everything else stays the same. Use this "
                    "instead of creating a new light when the "
                    "user wants to adjust intensity, color, "
                    "size, position, or rotation. For asset "
                    "lights, translate values are OFFSETS from "
                    "bounds (same as create_light)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prim_path": {
                            "type": "string",
                            "description": (
                                "Full prim path of the light "
                                "to update (scene or asset). "
                                "Use list_scene to find it."
                            ),
                        },
                        "intensity": {
                            "type": "number",
                            "description": "New intensity.",
                        },
                        "color_r": {
                            "type": "number",
                            "description": "New red (0-1).",
                        },
                        "color_g": {
                            "type": "number",
                            "description": "New green (0-1).",
                        },
                        "color_b": {
                            "type": "number",
                            "description": "New blue (0-1).",
                        },
                        "translate_x": {
                            "type": "number",
                            "description": "New X position.",
                        },
                        "translate_y": {
                            "type": "number",
                            "description": "New Y position.",
                        },
                        "translate_z": {
                            "type": "number",
                            "description": "New Z position.",
                        },
                        "radius": {
                            "type": "number",
                            "description": "New radius.",
                        },
                        "angle": {
                            "type": "number",
                            "description": "New angle.",
                        },
                        "width": {
                            "type": "number",
                            "description": "New width.",
                        },
                        "height": {
                            "type": "number",
                            "description": "New height.",
                        },
                        "length": {
                            "type": "number",
                            "description": "New length.",
                        },
                        "rotate_x": {
                            "type": "number",
                            "description": "New X rotation.",
                        },
                        "rotate_y": {
                            "type": "number",
                            "description": "New Y rotation.",
                        },
                        "rotate_z": {
                            "type": "number",
                            "description": "New Z rotation.",
                        },
                    },
                    "required": ["prim_path"],
                },
            ),
            Tool(
                name="remove_light",
                description=(
                    "Remove a light from the scene. Works for both "
                    "scene-level and asset-level lights. For asset "
                    "lights, removes from the asset's lgt.usda."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prim_path": {
                            "type": "string",
                            "description": (
                                "Full prim path of the light "
                                "to remove. Use list_scene to "
                                "find it."
                            ),
                        },
                    },
                    "required": ["prim_path"],
                },
            ),
            Tool(
                name="bind_material",
                description=(
                    "Bind a material to a prim. Copies the material file to "
                    "project assets, adds it as a sublayer, and binds it to "
                    "the target prim. Use this for individual material assignments."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prim_path": {
                            "type": "string",
                            "description": (
                                "Prim path of the geometry to apply the material to "
                                "(e.g. '/Scene/Furniture/Table_01')."
                            ),
                        },
                        "material_file": {
                            "type": "string",
                            "description": "Local file path to the material .usda file.",
                        },
                        "material_prim_path": {
                            "type": "string",
                            "description": (
                                "USD prim path of the material inside the file "
                                "(e.g. '/mtl/wood_varnished'). If omitted, the "
                                "first Material prim found is used."
                            ),
                        },
                    },
                    "required": ["prim_path", "material_file"],
                },
            ),
            Tool(
                name="list_materials",
                description=(
                    "List all materials in the scene and which prims they are "
                    "bound to. Use this to show current material assignments."
                ),
                parameters={"type": "object", "properties": {}},
            ),
            Tool(
                name="remove_material",
                description=(
                    "Remove material binding from a prim. Clears the "
                    "material assignment and removes any unused material "
                    "sublayers from the scene. Use list_prim_children "
                    "first to find the exact mesh prim path."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prim_path": {
                            "type": "string",
                            "description": (
                                "Prim path to remove the material from "
                                "(e.g. '.../single_table/table/table'). "
                                "Use list_prim_children to find the exact path."
                            ),
                        },
                    },
                    "required": ["prim_path"],
                },
            ),
            Tool(
                name="list_prim_children",
                description=(
                    "List all geometry parts inside a referenced asset. "
                    "Use this BEFORE bind_material to discover the internal "
                    "parts (table top, legs, frame, etc.) so you can target "
                    "the exact mesh for material binding. Returns each part's "
                    "name, type, and current material."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prim_path": {
                            "type": "string",
                            "description": (
                                "Prim path of the asset to inspect "
                                "(e.g. '/Scene/Furniture/Table_01')."
                            ),
                        },
                    },
                    "required": ["prim_path"],
                },
            ),
            Tool(
                name="list_project_assets",
                description=(
                    "List asset folders in the current "
                    "project's assets directory. Shows which "
                    "ones are referenced in the scene and "
                    "which are unused. Use this to find "
                    "asset folders that can be cleaned up. "
                    "Optionally filter by name."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Optional keyword to filter "
                                "by asset name."
                            ),
                        },
                    },
                },
            ),
            Tool(
                name="delete_project_asset",
                description=(
                    "Delete an asset folder from the project's "
                    "assets directory. Use this after removing "
                    "an asset from the scene when the user "
                    "confirms they want to delete the files too. "
                    "Only deletes ASWF asset folders, not USDZ "
                    "files or loose files."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "folder_name": {
                            "type": "string",
                            "description": (
                                "Name of the asset folder to "
                                "delete (e.g. 'single_table')."
                            ),
                        },
                    },
                    "required": ["folder_name"],
                },
            ),
            Tool(
                name="delete_project_texture",
                description=(
                    "Delete a texture file from the project's "
                    "textures/ directory. Scans all USD files "
                    "in the project to ensure the texture is "
                    "not referenced elsewhere before deleting."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "file_name": {
                            "type": "string",
                            "description": (
                                "Name of the texture file to "
                                "delete (e.g. 'studio.exr')."
                            ),
                        },
                    },
                    "required": ["file_name"],
                },
            ),
        ]

    # ── Private Helpers ───────────────────────────────────────────

    def _resolve_output_dir(self) -> Path:
        if self._project:
            return self._project.path
        msg = "No project set. Use 'bowerbot new' to create a project first."
        raise RuntimeError(msg)

    def _resolve_assets_dir(self) -> Path:
        if self._assets_dir:
            self._assets_dir.mkdir(parents=True, exist_ok=True)
            return self._assets_dir
        msg = "No project set. Use 'bowerbot new' to create a project first."
        raise RuntimeError(msg)

    def _update_project_meta(self) -> None:
        if self._project:
            self._project.save()

    # ── Tool Handlers ─────────────────────────────────────────────

    def _create_stage(self, params: dict[str, Any]) -> ToolResult:
        filename = params["filename"]
        safe_name = safe_file_name(filename)
        if not safe_name:
            safe_name = "scene"

        output_dir = self._resolve_output_dir()

        if self._project:
            self._stage_path = self._project.scene_path
        else:
            self._stage_path = output_dir / f"{safe_name}.usda"

        if self._stage_path.exists():
            self.writer.open_stage(self._stage_path)
            objects = self.writer.list_prims()
            self._object_count = len(objects)
            logger.info(f"Reopened existing stage: {self._stage_path}")
            return ToolResult(
                success=True,
                data={
                    "stage_path": str(self._stage_path),
                    "object_count": self._object_count,
                    "message": (
                        f"Stage already exists at "
                        f"{self._stage_path} with "
                        f"{self._object_count} object(s). Reopened."
                    ),
                },
            )

        self._object_count = 0
        self.writer.create_stage(self._stage_path)
        self.writer.save()
        self._update_project_meta()

        logger.info(f"Created stage: {self._stage_path}")
        return ToolResult(
            success=True,
            data={
                "stage_path": str(self._stage_path),
                "message": f"Stage created at {self._stage_path} with standard hierarchy.",
            },
        )

    def _place_asset(self, params: dict[str, Any]) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage created yet. Call create_stage first.",
            )

        asset_path = Path(params["asset_file_path"])
        asset_name = params["asset_name"]
        group = params["group"]
        tx = float(params["translate_x"])
        ty = float(params["translate_y"])
        tz = float(params["translate_z"])
        ry = float(params.get("rotate_y", 0.0))

        self._object_count += 1
        safe_asset_name = safe_prim_name(asset_name)
        prim_path = f"/Scene/{group}/{safe_asset_name}_{self._object_count:02d}"

        assets_dir = self._resolve_assets_dir()

        try:
            relative_path = self.assembler.prepare_asset(
                asset_path, assets_dir,
                fix_root_prim=params.get("fix_root_prim", False),
            )
        except ValueError as e:
            self._object_count -= 1
            return ToolResult(success=False, error=str(e))

        scene_object = SceneObject(
            prim_path=prim_path,
            asset=AssetMetadata(
                name=asset_name,
                source_skill="local",
                source_id=str(asset_path),
                file_path=relative_path,
            ),
            translate=(tx, ty, tz),
            rotate=(0.0, ry, 0.0),
        )

        self.writer.add_reference(scene_object)
        self.writer.save()
        self._update_project_meta()

        logger.info(f"Placed {asset_name} at {prim_path} ({tx}, {ty}, {tz})")
        return ToolResult(
            success=True,
            data={
                "prim_path": prim_path,
                "asset": asset_name,
                "position": {"x": tx, "y": ty, "z": tz},
                "rotation_y": ry,
                "message": f"Placed {asset_name} at {prim_path}",
            },
        )

    def _move_asset(self, params: dict[str, Any]) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        prim_path = params["prim_path"]
        tx = float(params["translate_x"])
        ty = float(params["translate_y"])
        tz = float(params["translate_z"])
        ry = float(params.get("rotate_y", 0.0))

        try:
            self.writer.set_transform(
                prim_path,
                translate=(tx, ty, tz),
                rotate=(0.0, ry, 0.0),
            )
        except (RuntimeError, ValueError) as e:
            return ToolResult(success=False, error=str(e))

        self.writer.save()

        logger.info(f"Moved {prim_path} to ({tx}, {ty}, {tz})")
        return ToolResult(
            success=True,
            data={
                "prim_path": prim_path,
                "position": {"x": tx, "y": ty, "z": tz},
                "rotation_y": ry,
                "message": f"Moved {prim_path} to ({tx}, {ty}, {tz})",
            },
        )

    def _list_scene(self) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        objects = self.writer.list_prims()
        return ToolResult(
            success=True,
            data={
                "object_count": len(objects),
                "objects": objects,
                "message": f"Scene has {len(objects)} object(s).",
            },
        )

    def _rename_prim(self, params: dict[str, Any]) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        old_path = params["old_path"]
        new_path = params["new_path"]

        try:
            success = self.writer.rename_prim(old_path, new_path)
        except (RuntimeError, ValueError) as e:
            return ToolResult(success=False, error=str(e))

        if not success:
            return ToolResult(
                success=False,
                error=f"Failed to rename {old_path} to {new_path}",
            )

        logger.info(f"Renamed {old_path} -> {new_path}")
        return ToolResult(
            success=True,
            data={
                "old_path": old_path,
                "new_path": new_path,
                "message": f"Renamed {old_path} -> {new_path}",
            },
        )

    def _remove_prim(self, params: dict[str, Any]) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        prim_path = params["prim_path"]

        try:
            success = self.writer.remove_prim(prim_path)
        except (RuntimeError, ValueError) as e:
            return ToolResult(success=False, error=str(e))

        if not success:
            return ToolResult(
                success=False,
                error=f"Failed to remove {prim_path}",
            )

        self._object_count = max(0, self._object_count - 1)
        self._update_project_meta()

        logger.info(f"Removed {prim_path}")
        return ToolResult(
            success=True,
            data={
                "prim_path": prim_path,
                "message": f"Removed {prim_path}",
            },
        )

    def _prepare_scene_texture(self, file_path: str | None) -> str | None:
        """Copy a texture to the project textures/ dir if it exists on disk."""
        if file_path is None:
            return None
        source = Path(file_path)
        if not source.exists():
            return file_path
        return copy_texture_to_project(source, self._resolve_output_dir())

    def _create_light(self, params: dict[str, Any]) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        light_type = LightType(params["light_type"])
        light_name = params["light_name"]
        asset_prim_path = params.get("asset_prim_path")

        tx = float(params.get("translate_x", 0.0))
        ty = float(params.get("translate_y", 0.0))
        tz = float(params.get("translate_z", 0.0))

        # Asset-level light
        if asset_prim_path:
            asset_dir, ref_prim_path = resolve_asset_dir_for_prim(self.writer.stage,asset_prim_path)
            if asset_dir is None or ref_prim_path is None:
                return ToolResult(
                    success=False,
                    error=(
                        f"Cannot find ASWF asset folder for "
                        f"{asset_prim_path}. Asset-level lights "
                        f"only work on ASWF folder assets."
                    ),
                )

            bounds = self.assembler.get_geometry_bounds(asset_dir)
            if bounds:
                tx, ty, tz = SceneGraphBuilder.apply_bounds_offsets(
                    bounds, tx, ty, tz,
                    has_explicit_y=params.get("translate_y") is not None,
                )

            texture = params.get("texture")
            if texture:
                maps_dir = asset_dir / ASWFLayerNames.MAPS
                maps_dir.mkdir(exist_ok=True)
                tex_path = Path(texture)
                if tex_path.exists():
                    dest = maps_dir / tex_path.name
                    if not dest.exists():
                        shutil.copy2(tex_path, dest)
                    texture = f"./{ASWFLayerNames.MAPS}/{tex_path.name}"

            safe_name = safe_prim_name(light_name)

            try:
                composed_path = self.assembler.add_light(
                    asset_dir=asset_dir,
                    light_name=safe_name,
                    light_type=light_type.value,
                    translate=(tx, ty, tz),
                    rotate=(
                        float(params.get("rotate_x", 0.0)),
                        float(params.get("rotate_y", 0.0)),
                        float(params.get("rotate_z", 0.0)),
                    ),
                    intensity=float(params.get("intensity", 1000.0)),
                    color=(
                        float(params.get("color_r", 1.0)),
                        float(params.get("color_g", 1.0)),
                        float(params.get("color_b", 1.0)),
                    ),
                    angle=params.get("angle"),
                    texture=texture,
                    radius=params.get("radius"),
                    width=params.get("width"),
                    height=params.get("height"),
                    length=params.get("length"),
                )
            except (ValueError, RuntimeError) as e:
                return ToolResult(success=False, error=str(e))

            self.writer.open_stage(self._stage_path)

            logger.info(
                f"Created asset light {light_type.value} in {asset_dir.name}/lgt.usda"
            )
            scene_light_path = f"{ref_prim_path}/{composed_path.lstrip('/')}"

            return ToolResult(
                success=True,
                data={
                    "prim_path": scene_light_path,
                    "light_type": light_type.value,
                    "asset_folder": asset_dir.name,
                    "position": {"x": tx, "y": ty, "z": tz},
                    "message": (
                        f"Created {light_type.value} in "
                        f"{asset_dir.name}/lgt.usda. "
                        f"To update this light, use "
                        f"prim_path: {scene_light_path}"
                    ),
                },
            )

        # Scene-level light
        self._object_count += 1
        safe_name = safe_prim_name(light_name)
        prim_path = f"/Scene/Lighting/{safe_name}_{self._object_count:02d}"

        light_params = LightParams(
            prim_path=prim_path,
            light_type=light_type,
            intensity=float(params.get("intensity", 1000.0)),
            color=(
                float(params.get("color_r", 1.0)),
                float(params.get("color_g", 1.0)),
                float(params.get("color_b", 1.0)),
            ),
            translate=(tx, ty, tz),
            rotate=(
                float(params.get("rotate_x", 0.0)),
                float(params.get("rotate_y", 0.0)),
                float(params.get("rotate_z", 0.0)),
            ),
            angle=params.get("angle"),
            texture=self._prepare_scene_texture(params.get("texture")),
            radius=params.get("radius"),
            width=params.get("width"),
            height=params.get("height"),
            length=params.get("length"),
        )

        self.writer.create_light(light_params)
        self.writer.save()
        self._update_project_meta()

        logger.info(f"Created {light_type.value} at {prim_path}")
        return ToolResult(
            success=True,
            data={
                "prim_path": prim_path,
                "light_type": light_type.value,
                "position": {"x": tx, "y": ty, "z": tz},
                "intensity": light_params.intensity,
                "message": f"Created {light_type.value} at {prim_path}",
            },
        )

    def _update_light(self, params: dict[str, Any]) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        prim_path = params["prim_path"]
        asset_dir, _ = resolve_asset_dir_for_prim(self.writer.stage,prim_path)

        translate = None
        if any(params.get(k) is not None for k in ("translate_x", "translate_y", "translate_z")):
            translate = (
                float(params.get("translate_x", 0.0)),
                float(params.get("translate_y", 0.0)),
                float(params.get("translate_z", 0.0)),
            )

        color = None
        if any(params.get(k) is not None for k in ("color_r", "color_g", "color_b")):
            color = (
                float(params.get("color_r", 1.0)),
                float(params.get("color_g", 1.0)),
                float(params.get("color_b", 1.0)),
            )

        intensity = params.get("intensity")
        if intensity is not None:
            intensity = float(intensity)

        extra = {}
        for key in ("radius", "angle", "width", "height", "length"):
            if params.get(key) is not None:
                extra[key] = float(params[key])

        rotate = None
        if any(params.get(k) is not None for k in ("rotate_x", "rotate_y", "rotate_z")):
            rotate = (
                float(params.get("rotate_x", 0.0)),
                float(params.get("rotate_y", 0.0)),
                float(params.get("rotate_z", 0.0)),
            )

        if asset_dir is not None:
            light_name = prim_path.rstrip("/").split("/")[-1]

            if translate is not None:
                bounds = self.assembler.get_geometry_bounds(asset_dir)
                if bounds:
                    translate = SceneGraphBuilder.apply_bounds_offsets(
                        bounds, *translate,
                        has_explicit_y=params.get("translate_y") is not None,
                    )

            try:
                self.assembler.update_light(
                    asset_dir=asset_dir,
                    light_name=light_name,
                    translate=translate,
                    rotate=rotate,
                    intensity=intensity,
                    color=color,
                    **extra,
                )
            except (ValueError, RuntimeError) as e:
                return ToolResult(success=False, error=str(e))

            self.writer.open_stage(self._stage_path)

            logger.info(f"Updated asset light at {prim_path}")
            return ToolResult(
                success=True,
                data={
                    "prim_path": prim_path,
                    "asset_folder": asset_dir.name,
                    "message": f"Updated asset light at {prim_path}",
                },
            )

        try:
            self.writer.update_light(
                prim_path=prim_path,
                intensity=intensity,
                color=color,
                translate=translate,
                rotate=rotate,
                **extra,
            )
        except (ValueError, RuntimeError) as e:
            return ToolResult(success=False, error=str(e))

        self.writer.save()

        logger.info(f"Updated scene light at {prim_path}")
        return ToolResult(
            success=True,
            data={
                "prim_path": prim_path,
                "message": f"Updated scene light at {prim_path}",
            },
        )

    def _remove_light(self, params: dict[str, Any]) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        prim_path = params["prim_path"]
        asset_dir, _ = resolve_asset_dir_for_prim(self.writer.stage,prim_path)

        if asset_dir is not None:
            light_name = prim_path.rstrip("/").split("/")[-1]

            try:
                self.assembler.remove_light(
                    asset_dir=asset_dir,
                    light_name=light_name,
                )
            except (ValueError, RuntimeError) as e:
                return ToolResult(success=False, error=str(e))

            self.writer.open_stage(self._stage_path)

            logger.info(f"Removed asset light {light_name} from {asset_dir.name}")
            return ToolResult(
                success=True,
                data={
                    "prim_path": prim_path,
                    "asset_folder": asset_dir.name,
                    "message": f"Removed light {light_name} from {asset_dir.name}",
                },
            )

        # Scene-level light — check for texture before removing
        texture_file = None
        prim = self.writer.stage.GetPrimAtPath(prim_path)
        if prim and prim.IsValid():
            tex_attr = prim.GetAttribute("inputs:texture:file")
            if tex_attr and tex_attr.Get():
                tex_val = tex_attr.Get()
                texture_file = tex_val.path if hasattr(tex_val, "path") else str(tex_val)

        try:
            success = self.writer.remove_prim(prim_path)
        except (RuntimeError, ValueError) as e:
            return ToolResult(success=False, error=str(e))

        if not success:
            return ToolResult(
                success=False,
                error=f"Failed to remove light {prim_path}",
            )

        self.writer.save()

        logger.info(f"Removed scene light at {prim_path}")
        result_data: dict[str, Any] = {
            "prim_path": prim_path,
            "message": f"Removed light at {prim_path}",
        }
        if texture_file:
            result_data["texture_file"] = texture_file

        return ToolResult(success=True, data=result_data)

    def _compute_grid_layout(self, params: dict[str, Any]) -> ToolResult:
        count = int(params["count"])
        spacing = float(params.get("spacing", 2.0))

        placements = self.graph.suggest_grid_layout(count=count, spacing=spacing)

        positions = [
            {"x": round(p.translate[0], 2), "z": round(p.translate[2], 2)}
            for p in placements
        ]

        return ToolResult(
            success=True,
            data={
                "count": count,
                "spacing": spacing,
                "positions": positions,
                "message": f"Computed {count} positions in grid with {spacing}m spacing.",
            },
        )

    def _validate_scene(self) -> ToolResult:
        if self._stage_path is None:
            return ToolResult(
                success=False,
                error="No stage to validate. Call create_stage first.",
            )

        result = self.validator.validate(str(self._stage_path))

        issues = [
            {"severity": i.severity.value, "message": i.message, "prim": i.prim_path}
            for i in result.issues
        ]

        return ToolResult(
            success=True,
            data={
                "is_valid": result.is_valid,
                "error_count": result.error_count,
                "issues": issues,
                "message": "Scene is valid!" if result.is_valid else f"Found {result.error_count} error(s).",
            },
        )

    def _package_scene(self) -> ToolResult:
        if self._stage_path is None:
            return ToolResult(
                success=False,
                error="No stage to package. Call create_stage first.",
            )

        output_path = self._stage_path.with_suffix(".usdz")
        result_path = self.packager.package(self._stage_path, output_path)

        logger.info(f"Packaged scene: {result_path}")
        return ToolResult(
            success=True,
            data={
                "usdz_path": str(result_path),
                "message": f"Scene packaged to {result_path}",
            },
        )

    # ── Material Operations ────────────────────────────────────────

    def _bind_material(self, params: dict[str, Any]) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        prim_path = params["prim_path"]
        material_file = Path(params["material_file"])
        material_prim_path = params.get("material_prim_path")

        if not material_file.exists():
            return ToolResult(
                success=False,
                error=f"Material file not found: {material_file}",
            )

        asset_dir, ref_prim_path = resolve_asset_dir_for_prim(self.writer.stage,prim_path)
        if asset_dir is None or ref_prim_path is None:
            return ToolResult(
                success=False,
                error=(
                    f"Cannot find ASWF asset folder for {prim_path}. "
                    "Material binding only works on assets placed "
                    "as ASWF folders (not USDZ)."
                ),
            )

        asset_local_path = prim_path
        if prim_path.startswith(ref_prim_path):
            asset_local_path = prim_path[len(ref_prim_path):]
            if not asset_local_path:
                asset_local_path = "/"

        try:
            material_prim_path = self.assembler.add_material(
                asset_dir=asset_dir,
                material_file=material_file,
                prim_path=asset_local_path,
                material_prim_path=material_prim_path,
            )
        except (ValueError, RuntimeError) as e:
            return ToolResult(success=False, error=str(e))

        self.writer.open_stage(self._stage_path)

        logger.info(f"Bound {material_prim_path} to {prim_path} in {asset_dir.name}/")
        return ToolResult(
            success=True,
            data={
                "prim_path": prim_path,
                "material": material_prim_path,
                "asset_folder": asset_dir.name,
                "message": (
                    f"Bound {material_prim_path} to {prim_path} "
                    f"in {asset_dir.name}/mtl.usd"
                ),
            },
        )

    def _remove_material(self, params: dict[str, Any]) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        prim_path = params["prim_path"]

        asset_dir, ref_prim_path = resolve_asset_dir_for_prim(self.writer.stage,prim_path)
        if asset_dir is None or ref_prim_path is None:
            return ToolResult(
                success=False,
                error=f"Cannot find ASWF asset folder for {prim_path}.",
            )

        asset_local_path = prim_path
        if prim_path.startswith(ref_prim_path):
            asset_local_path = prim_path[len(ref_prim_path):]
            if not asset_local_path:
                asset_local_path = "/"

        self.assembler.remove_material_binding(asset_dir, asset_local_path)
        self.writer.open_stage(self._stage_path)

        logger.info(f"Removed material from {prim_path}")
        return ToolResult(
            success=True,
            data={
                "prim_path": prim_path,
                "asset_folder": asset_dir.name,
                "message": f"Removed material binding from {prim_path}",
            },
        )

    def _list_materials(self) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        assets_dir = self._resolve_assets_dir()
        all_materials: list[dict] = []

        for entry in assets_dir.iterdir():
            if not entry.is_dir():
                continue
            mtl_path = entry / "mtl.usd"
            if mtl_path.exists():
                materials = self.assembler.list_materials(entry)
                for mat in materials:
                    mat["asset_folder"] = entry.name
                all_materials.extend(materials)

        return ToolResult(
            success=True,
            data={
                "material_count": len(all_materials),
                "materials": all_materials,
                "message": f"Scene has {len(all_materials)} material(s).",
            },
        )

    def _list_prim_children(self, params: dict[str, Any]) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        prim_path = params["prim_path"]
        children = self.writer.list_prim_children(prim_path)

        if not children:
            return ToolResult(
                success=True,
                data={
                    "prim_path": prim_path,
                    "part_count": 0,
                    "parts": [],
                    "message": f"No geometry parts found under {prim_path}.",
                },
            )

        return ToolResult(
            success=True,
            data={
                "prim_path": prim_path,
                "part_count": len(children),
                "parts": children,
                "message": (
                    f"Found {len(children)} geometry part(s) under {prim_path}. "
                    "Use the prim_path of a specific part with bind_material."
                ),
            },
        )

    # ── Project Asset Management ──────────────────────────────────

    def _list_project_assets(self, params: dict[str, Any]) -> ToolResult:
        if self._project is None:
            return ToolResult(success=False, error="No project open.")

        assets_dir = self._resolve_assets_dir()
        if not assets_dir.exists():
            return ToolResult(
                success=True,
                data={"assets": [], "message": "No assets directory found."},
            )

        referenced: set[str] = set()
        if self.writer.stage is not None:
            for prim in self.writer.stage.Traverse():
                referenced.update(iter_prim_ref_paths(prim))

        query = params.get("query", "")
        query_lower = query.lower() if query else ""

        results = []
        for entry in sorted(assets_dir.iterdir()):
            if query_lower and query_lower not in entry.name.lower():
                continue
            in_scene = any(entry.name in r for r in referenced)
            results.append({
                "name": entry.name,
                "type": "folder" if entry.is_dir() else "file",
                "in_scene": in_scene,
            })

        unused = [a for a in results if not a["in_scene"]]

        return ToolResult(
            success=True,
            data={
                "total": len(results),
                "unused_count": len(unused),
                "assets": results,
                "message": f"Project has {len(results)} asset(s), {len(unused)} unused.",
            },
        )

    def _delete_project_asset(self, params: dict[str, Any]) -> ToolResult:
        if self._project is None:
            return ToolResult(success=False, error="No project open.")

        folder_name = params["folder_name"]
        assets_dir = self._resolve_assets_dir()
        asset_folder = assets_dir / folder_name

        if not asset_folder.exists():
            return ToolResult(
                success=False,
                error=f"Asset folder not found: {folder_name}",
            )

        if not asset_folder.is_dir():
            return ToolResult(
                success=False,
                error=(
                    f"'{folder_name}' is not a folder. "
                    "This tool only deletes ASWF asset folders."
                ),
            )

        referencing = find_asset_references(
            self._project.path, folder_name, skip_dir=asset_folder,
        )
        if referencing:
            files_list = ", ".join(referencing)
            return ToolResult(
                success=False,
                error=(
                    f"Asset '{folder_name}' is still "
                    f"referenced by: {files_list}. "
                    f"Remove those references first."
                ),
            )

        shutil.rmtree(asset_folder)
        logger.info(f"Deleted project asset: {asset_folder}")

        return ToolResult(
            success=True,
            data={
                "folder": folder_name,
                "message": f"Deleted asset folder '{folder_name}' from project assets.",
            },
        )

    def _delete_project_texture(self, params: dict[str, Any]) -> ToolResult:
        if self._project is None:
            return ToolResult(success=False, error="No project open.")

        file_name = params["file_name"]
        project_dir = self._project.path
        tex_dir = project_dir / ASWFLayerNames.TEXTURES
        tex_file = tex_dir / file_name

        if not tex_file.exists():
            return ToolResult(
                success=False,
                error=f"Texture file not found: {ASWFLayerNames.TEXTURES}/{file_name}",
            )

        referencing = find_texture_references(self._project.path, file_name)
        if referencing:
            files_list = ", ".join(referencing)
            return ToolResult(
                success=False,
                error=(
                    f"Texture '{file_name}' is still "
                    f"referenced by: {files_list}. "
                    f"Remove those references first."
                ),
            )

        tex_file.unlink()
        logger.info(f"Deleted project texture: {file_name}")

        if tex_dir.exists() and not any(tex_dir.iterdir()):
            tex_dir.rmdir()

        return ToolResult(
            success=True,
            data={
                "file": file_name,
                "message": f"Deleted texture '{file_name}' from project textures.",
            },
        )
