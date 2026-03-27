# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Assembly skill — exposes USD scene assembly as tools for the LLM.

This skill holds the state of the scene being built (the current USD stage)
and provides tools to create, populate, validate, and package it.
When a Project is set, all files go into the project directory.
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
from bowerbot.engine.dependency_resolver import DependencyResolver
from bowerbot.engine.packager import Packager
from bowerbot.engine.scene_graph import SceneGraphBuilder
from bowerbot.engine.stage_writer import StageWriter
from bowerbot.engine.validator import SceneValidator
from bowerbot.schemas import AssetMetadata, LightParams, LightType, SceneObject
from bowerbot.skills.base import Skill, SkillCategory, Tool, ToolResult

logger = logging.getLogger(__name__)


class AssemblySkill(Skill):
    """USD Assembly tools — the LLM calls these to build scenes.

    Maintains a StageWriter instance across tool calls so the LLM
    can create a stage, place assets into it, validate, and package.
    """

    name = "assembly"
    category = SkillCategory.DCC

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
        self.resolver = DependencyResolver()
        self.assembler = AssetAssembler()

        self._project = None
        self._stage_path: Path | None = None
        self._assets_dir: Path | None = None
        self._object_count: int = 0

    def set_project(self, project: Project) -> None:
        """Bind this skill to a project. All output goes into the project folder."""
        self._project = project
        self._stage_path = project.scene_path
        self._assets_dir = project.assets_dir

        # If the scene file already exists, reopen it
        if self._stage_path.exists():
            self.writer.open_stage(self._stage_path)
            # Count existing objects
            objects = self.writer.list_prims()
            self._object_count = len(objects)
            logger.info(f"Resumed project '{project.name}' with {self._object_count} object(s)")

    def _resolve_output_dir(self) -> Path:
        """Get the directory for output files."""
        if self._project:
            return self._project.path
        msg = "No project set. Use 'bowerbot new' to create a project first."
        raise RuntimeError(msg)

    def _resolve_assets_dir(self) -> Path:
        """Get the directory for asset files."""
        if self._assets_dir:
            self._assets_dir.mkdir(parents=True, exist_ok=True)
            return self._assets_dir
        msg = "No project set. Use 'bowerbot new' to create a project first."
        raise RuntimeError(msg)

    def _update_project_meta(self) -> None:
        """Update project metadata if we're inside a project."""
        if self._project:
            self._project.meta.object_count = self._object_count
            self._project.save()

    def get_tools(self) -> list[Tool]:
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
                    "Create a USD light in the scene. Lights are native USD prims "
                    "(not asset references). They go in /Scene/Lighting."
                ),
                parameters={
                    "type": "object",
                    "properties": {
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
        ]

    async def execute(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
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
                case _:
                    return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
        except Exception as e:
            logger.exception(f"Assembly tool error: {tool_name}")
            return ToolResult(success=False, error=str(e))

    def _create_stage(self, params: dict[str, Any]) -> ToolResult:
        filename = params["filename"]
        safe_name = "".join(c for c in filename if c.isalnum() or c in "_-").strip()
        if not safe_name:
            safe_name = "scene"

        output_dir = self._resolve_output_dir()

        # If inside a project, always use scene.usda
        if self._project:
            self._stage_path = self._project.scene_path
        else:
            self._stage_path = output_dir / f"{safe_name}.usda"

        self._object_count = 0

        if self._stage_path.exists():
            self._stage_path.unlink()

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
        safe_asset_name = "".join(c for c in asset_name if c.isalnum() or c == "_").strip()
        prim_path = f"/Scene/{group}/{safe_asset_name}_{self._object_count:02d}"

        # Copy asset to project assets dir
        assets_dir = self._resolve_assets_dir()

        if self._is_asset_folder_root(asset_path):
            # ASWF asset folder — copy entire folder
            relative_path = self._copy_asset_folder(
                asset_path, assets_dir,
            )
        elif asset_path.suffix.lower() == ".usdz":
            # USDZ — self-contained, copy as single file
            local_copy = assets_dir / asset_path.name
            if not local_copy.exists():
                shutil.copy2(asset_path, local_copy)
            relative_path = f"assets/{asset_path.name}"
        else:
            # Loose geometry — check ASWF compliance
            bad_type = self.assembler.check_root_prim_type(
                asset_path,
            )
            fix_root = params.get("fix_root_prim", False)

            if bad_type and not fix_root:
                return ToolResult(
                    success=False,
                    error=(
                        f"Asset '{asset_path.name}' has a "
                        f"{bad_type} as its root prim instead "
                        f"of an Xform. Per ASWF USD guidelines, "
                        f"the root prim should be an Xform with "
                        f"geometry as children. Ask the user if "
                        f"they want to fix this automatically, "
                        f"then call place_asset again with "
                        f"fix_root_prim set to true."
                    ),
                )

            if bad_type and fix_root:
                self.assembler.wrap_root_prim(asset_path)
                logger.info(
                    "Wrapped %s root prim in Xform for "
                    "ASWF compliance",
                    asset_path.name,
                )

            # Create ASWF folder
            folder_name = asset_path.stem
            root_file = self.assembler.create_asset_folder(
                output_dir=assets_dir,
                asset_name=folder_name,
                geometry_file=asset_path,
            )
            relative_path = (
                f"assets/{folder_name}/{root_file.name}"
            )

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

        logger.info(
            f"Moved {prim_path} to ({tx}, {ty}, {tz})"
        )
        return ToolResult(
            success=True,
            data={
                "prim_path": prim_path,
                "position": {"x": tx, "y": ty, "z": tz},
                "rotation_y": ry,
                "message": f"Moved {prim_path} to "
                f"({tx}, {ty}, {tz})",
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

    def _copy_to_assets(self, file_path: str | None, subfolder: str = "") -> str | None:
        """Copy a file to the project assets dir and return a relative path.

        Used for any file that needs to live alongside the USD stage
        (HDRI textures, material maps, etc.).
        """
        if file_path is None:
            return None

        source = Path(file_path)
        if not source.exists():
            return file_path

        assets_dir = self._resolve_assets_dir()
        if subfolder:
            target_dir = assets_dir / subfolder
            target_dir.mkdir(parents=True, exist_ok=True)
        else:
            target_dir = assets_dir

        local_copy = target_dir / source.name

        if not local_copy.exists():
            shutil.copy2(source, local_copy)

        relative = f"assets/{subfolder}/{source.name}" if subfolder else f"assets/{source.name}"
        return relative

    def _create_light(self, params: dict[str, Any]) -> ToolResult:
        if self._stage_path is None or self.writer.stage is None:
            return ToolResult(
                success=False,
                error="No stage open. Call create_stage first.",
            )

        light_type = LightType(params["light_type"])
        light_name = params["light_name"]

        self._object_count += 1
        safe_name = "".join(c for c in light_name if c.isalnum() or c == "_").strip()
        prim_path = f"/Scene/Lighting/{safe_name}_{self._object_count:02d}"

        tx = float(params.get("translate_x", 0.0))
        ty = float(params.get("translate_y", 0.0))
        tz = float(params.get("translate_z", 0.0))

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
            texture=self._copy_to_assets(params.get("texture"), subfolder="textures"),
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

        # Find which asset folder this prim belongs to
        asset_dir, ref_prim_path = self._resolve_asset_dir_for_prim(
            prim_path,
        )
        if asset_dir is None or ref_prim_path is None:
            return ToolResult(
                success=False,
                error=(
                    f"Cannot find ASWF asset folder for {prim_path}. "
                    "Material binding only works on assets placed "
                    "as ASWF folders (not USDZ)."
                ),
            )

        # Convert scene path to asset-local path by stripping
        # everything up to the reference prim
        asset_local_path = prim_path
        if prim_path.startswith(ref_prim_path):
            asset_local_path = prim_path[len(ref_prim_path):]
            if not asset_local_path:
                asset_local_path = "/"

        # Add material into the asset folder's mtl.usd
        try:
            material_prim_path = self.assembler.add_material(
                asset_dir=asset_dir,
                material_file=material_file,
                prim_path=asset_local_path,
                material_prim_path=material_prim_path,
            )
        except (ValueError, RuntimeError) as e:
            return ToolResult(success=False, error=str(e))

        # Reopen scene stage to pick up the updated composition
        self.writer.open_stage(self._stage_path)

        logger.info(
            f"Bound {material_prim_path} to {prim_path} "
            f"in {asset_dir.name}/"
        )
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

        asset_dir, ref_prim_path = self._resolve_asset_dir_for_prim(
            prim_path,
        )
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

        self.assembler.remove_material_binding(
            asset_dir, asset_local_path,
        )

        # Reopen scene stage to pick up changes
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

        # Collect materials from all ASWF asset folders
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

    # ── ASWF Asset Folder Operations ───────────────────────────────

    @staticmethod
    def _is_asset_folder_root(asset_path: Path) -> bool:
        """Check if asset_path is the root file of an ASWF asset folder.

        An ASWF root file has the same stem as its parent directory
        (e.g. ``single_table/single_table.usd``).
        """
        return (
            asset_path.stem == asset_path.parent.name
            and asset_path.suffix.lower() in {".usd", ".usda", ".usdc"}
        )

    @staticmethod
    def _copy_asset_folder(
        root_file: Path, assets_dir: Path,
    ) -> str:
        """Copy an entire ASWF asset folder to the project assets dir.

        Returns the relative path from the stage file to the root file.
        """
        source_dir = root_file.parent
        folder_name = source_dir.name
        dest_dir = assets_dir / folder_name

        if not dest_dir.exists():
            shutil.copytree(source_dir, dest_dir)

        return f"assets/{folder_name}/{root_file.name}"

    def _resolve_asset_dir_for_prim(
        self, prim_path: str,
    ) -> tuple[Path | None, str | None]:
        """Find the ASWF asset folder for a given prim path.

        Walks the prim hierarchy to find the reference, then returns
        the asset folder path and the prim path where the reference
        lives. The caller can use the reference prim path to convert
        scene paths to asset-local paths.

        Returns:
            (asset_dir, ref_prim_path) or (None, None) if not found.
        """
        if self.writer.stage is None:
            return None, None

        stage = self.writer.stage
        path_parts = prim_path.strip("/").split("/")

        for i in range(len(path_parts), 0, -1):
            check_path = "/" + "/".join(path_parts[:i])
            prim = stage.GetPrimAtPath(check_path)
            if not prim.IsValid():
                continue

            refs = prim.GetMetadata("references")
            if refs is None:
                continue

            for ref_list in (
                refs.prependedItems,
                refs.appendedItems,
                refs.explicitItems,
            ):
                if not ref_list:
                    continue
                for ref in ref_list:
                    asset_path = ref.assetPath
                    if not asset_path:
                        continue

                    stage_dir = Path(
                        stage.GetRootLayer().realPath,
                    ).parent
                    resolved = (stage_dir / asset_path).resolve()

                    if resolved.exists() and resolved.parent.is_dir():
                        folder = resolved.parent
                        for ext in (".usd", ".usda", ".usdc"):
                            if resolved.name == f"{folder.name}{ext}":
                                return folder, check_path

        return None, None

    def _list_project_assets(
        self, params: dict[str, Any],
    ) -> ToolResult:
        if self._project is None:
            return ToolResult(
                success=False,
                error="No project open.",
            )

        assets_dir = self._resolve_assets_dir()
        if not assets_dir.exists():
            return ToolResult(
                success=True,
                data={
                    "assets": [],
                    "message": "No assets directory found.",
                },
            )

        # Collect referenced asset paths from the scene
        referenced: set[str] = set()
        if self.writer.stage is not None:
            for prim in self.writer.stage.Traverse():
                refs = prim.GetMetadata("references")
                if refs is None:
                    continue
                for ref_list in (
                    refs.prependedItems,
                    refs.appendedItems,
                    refs.explicitItems,
                ):
                    if not ref_list:
                        continue
                    for ref in ref_list:
                        if ref.assetPath:
                            referenced.add(ref.assetPath)

        # List asset folders and files, optionally filtered
        query = params.get("query", "")
        query_lower = query.lower() if query else ""

        results = []
        for entry in sorted(assets_dir.iterdir()):
            if query_lower and query_lower not in entry.name.lower():
                continue

            in_scene = any(
                entry.name in r for r in referenced
            )
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
                "message": (
                    f"Project has {len(results)} asset(s), "
                    f"{len(unused)} unused."
                ),
            },
        )

    def _delete_project_asset(
        self, params: dict[str, Any],
    ) -> ToolResult:
        if self._project is None:
            return ToolResult(
                success=False,
                error="No project open.",
            )

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

        # Check if still referenced in the scene
        if self.writer.stage is not None:
            for prim in self.writer.stage.Traverse():
                refs = prim.GetMetadata("references")
                if refs is None:
                    continue
                for ref_list in (
                    refs.prependedItems,
                    refs.appendedItems,
                    refs.explicitItems,
                ):
                    if not ref_list:
                        continue
                    for ref in ref_list:
                        if folder_name in ref.assetPath:
                            return ToolResult(
                                success=False,
                                error=(
                                    f"Asset '{folder_name}' is "
                                    f"still referenced in the "
                                    f"scene. Remove it from the "
                                    f"scene first."
                                ),
                            )

        shutil.rmtree(asset_folder)
        logger.info(f"Deleted project asset: {asset_folder}")

        return ToolResult(
            success=True,
            data={
                "folder": folder_name,
                "message": (
                    f"Deleted asset folder '{folder_name}' "
                    f"from project assets."
                ),
            },
        )

    def validate_config(self) -> bool:
        """Assembly skill is always valid — no external config needed."""
        return True