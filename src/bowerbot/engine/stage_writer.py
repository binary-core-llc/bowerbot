# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""StageWriter — creates and writes USD stages.

Handles all direct USD API calls: creating stages, adding references,
setting transforms, managing composition arcs.
"""

import os
from pathlib import Path

from pxr import Gf, Kind, Sdf, Usd, UsdGeom, UsdLux, UsdShade

from bowerbot.schemas import LightParams, LightType, SceneObject


class StageWriter:
    """Writes USD stages using the pxr API.

    All USD file operations are centralized here so the rest of
    BowerBot never touches pxr directly.
    """

    def __init__(self, meters_per_unit: float = 1.0, up_axis: str = "Y") -> None:
        self.meters_per_unit = meters_per_unit
        self.up_axis = up_axis
        self._stage = None

    def create_stage(self, path: str | Path) -> None:
        """Create a new USD stage with BowerBot defaults."""

        path = str(path)
        self._stage = Usd.Stage.CreateNew(path)

        # Set stage metadata
        UsdGeom.SetStageMetersPerUnit(self._stage, self.meters_per_unit)
        UsdGeom.SetStageUpAxis(
            self._stage,
            UsdGeom.Tokens.y if self.up_axis == "Y" else UsdGeom.Tokens.z,
        )

        # Create root prim and set as default
        root = self._stage.DefinePrim("/Scene", "Xform")
        self._stage.SetDefaultPrim(root)
        Usd.ModelAPI(root).SetKind(Kind.Tokens.assembly)

        # Create standard hierarchy
        for group in ["Architecture", "Furniture", "Products", "Lighting", "Props"]:
            self._stage.DefinePrim(f"/Scene/{group}", "Xform")

        self._stage.Save()

    def _compute_unit_scale(self, asset_path: str) -> float:
        """Return the scale needed to convert asset units to scene units.

        Opens the referenced asset, reads its ``metersPerUnit``, and
        returns ``asset_mpu / scene_mpu``.  For example a centimetre
        asset (0.01) in a metre scene (1.0) returns 0.01.
        """

        # Resolve relative paths against the stage directory
        if not os.path.isabs(asset_path):
            stage_dir = os.path.dirname(
                self._stage.GetRootLayer().realPath,
            )
            asset_path = os.path.join(stage_dir, asset_path)

        asset_stage = Usd.Stage.Open(asset_path)
        if asset_stage is None:
            return 1.0

        asset_mpu = UsdGeom.GetStageMetersPerUnit(asset_stage)
        scene_mpu = UsdGeom.GetStageMetersPerUnit(self._stage)
        if scene_mpu == 0:
            return 1.0

        return asset_mpu / scene_mpu

    @staticmethod
    def _read_existing_scale(xformable):
        """Read the scale value from a prim's current xform ops."""

        for op in xformable.GetOrderedXformOps():
            if op.GetOpType() == UsdGeom.XformOp.TypeScale:
                return op.Get()
        return None

    def add_reference(self, scene_object: SceneObject) -> None:
        """Add a referenced asset to the stage at the given prim path."""

        if self._stage is None:
            msg = "No stage open. Call create_stage() first."
            raise RuntimeError(msg)

        asset_path = (
            scene_object.asset.file_path
            or scene_object.asset.source_id
        )

        # Compute unit conversion before adding the reference
        unit_scale = self._compute_unit_scale(asset_path)

        # Define the prim and add reference
        prim = self._stage.DefinePrim(
            scene_object.prim_path, "Xform",
        )
        prim.GetReferences().AddReference(asset_path)

        # Set transform
        xformable = UsdGeom.Xformable(prim)
        xformable.ClearXformOpOrder()

        tx, ty, tz = scene_object.translate
        xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))

        rx, ry, rz = scene_object.rotate
        if any(v != 0.0 for v in (rx, ry, rz)):
            xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))

        # Apply unit-conversion scale when the asset uses
        # different units than the scene (e.g. cm → m).
        if abs(unit_scale - 1.0) > 1e-6:
            xformable.AddScaleOp().Set(
                Gf.Vec3f(unit_scale, unit_scale, unit_scale),
            )
        else:
            sx, sy, sz = scene_object.scale
            if any(v != 1.0 for v in (sx, sy, sz)):
                xformable.AddScaleOp().Set(
                    Gf.Vec3f(sx, sy, sz),
                )

    # Mapping from LightType to UsdLux class and supported extra attributes.
    _LIGHT_CLASSES: dict = {
        LightType.DISTANT: UsdLux.DistantLight,
        LightType.DOME: UsdLux.DomeLight,
        LightType.SPHERE: UsdLux.SphereLight,
        LightType.RECT: UsdLux.RectLight,
        LightType.DISK: UsdLux.DiskLight,
        LightType.CYLINDER: UsdLux.CylinderLight,
    }

    def create_light(self, light: LightParams) -> None:
        """Create a USD light prim in the stage."""
        if self._stage is None:
            msg = "No stage open. Call create_stage() first."
            raise RuntimeError(msg)

        light_cls = self._LIGHT_CLASSES[light.light_type]
        light_prim = light_cls.Define(self._stage, light.prim_path)

        # Common attributes
        light_prim.CreateIntensityAttr(light.intensity)
        light_prim.CreateColorAttr(Gf.Vec3f(*light.color))

        # Type-specific attributes
        attr_map = {
            "angle": "CreateAngleAttr",
            "texture": "CreateTextureFileAttr",
            "radius": "CreateRadiusAttr",
            "width": "CreateWidthAttr",
            "height": "CreateHeightAttr",
            "length": "CreateLengthAttr",
        }
        for field_name, create_method in attr_map.items():
            value = getattr(light, field_name, None)
            if value is not None and hasattr(light_prim, create_method):
                getattr(light_prim, create_method)().Set(value)

        # Set transform
        xformable = UsdGeom.Xformable(light_prim)
        xformable.ClearXformOpOrder()

        tx, ty, tz = light.translate
        xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))

        rx, ry, rz = light.rotate
        if any(v != 0.0 for v in (rx, ry, rz)):
            xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))

    def set_transform(
        self,
        prim_path: str,
        translate: tuple[float, float, float],
        rotate: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        """Update the transform on an existing prim.

        Preserves any unit-conversion scale that was applied when
        the asset was first referenced.
        """

        if self._stage is None:
            msg = "No stage open."
            raise RuntimeError(msg)

        prim = self._stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            msg = f"Prim not found: {prim_path}"
            raise ValueError(msg)

        xformable = UsdGeom.Xformable(prim)

        # Capture the existing scale before clearing ops
        existing_scale = self._read_existing_scale(xformable)

        xformable.ClearXformOpOrder()

        tx, ty, tz = translate
        xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))

        rx, ry, rz = rotate
        if any(v != 0.0 for v in (rx, ry, rz)):
            xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))

        # Re-apply the scale so unit conversion is preserved
        if existing_scale is not None:
            xformable.AddScaleOp().Set(existing_scale)

    def save(self) -> None:
        """Save the current stage to disk."""
        if self._stage is None:
            msg = "No stage open."
            raise RuntimeError(msg)
        self._stage.Save()

    def list_prims(self) -> list[dict]:
        """List all placed objects (prims with references) in the stage."""

        if self._stage is None:
            return []

        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_],
        )

        objects = []
        for prim in self._stage.Traverse():
            refs = prim.GetMetadata("references")
            is_light = prim.HasAPI(UsdLux.LightAPI)

            if refs is None and not is_light:
                continue

            position = None
            xformable = UsdGeom.Xformable(prim)
            if xformable:
                local_xform = xformable.GetLocalTransformation()
                t = local_xform.ExtractTranslation()
                position = {
                    "x": round(t[0], 2),
                    "y": round(t[1], 2),
                    "z": round(t[2], 2),
                }

            if is_light:
                # Light prims have no geometry bounds — report type and attributes
                light_data = {
                    "prim_path": str(prim.GetPath()),
                    "light_type": prim.GetTypeName(),
                    "position": position,
                }
                intensity_attr = prim.GetAttribute("inputs:intensity")
                if intensity_attr:
                    light_data["intensity"] = intensity_attr.Get()
                color_attr = prim.GetAttribute("inputs:color")
                if color_attr:
                    c = color_attr.Get()
                    light_data["color"] = {
                        "r": round(c[0], 3),
                        "g": round(c[1], 3),
                        "b": round(c[2], 3),
                    }
                objects.append(light_data)
                continue

            # Compute world-space bounding box so the LLM
            # can read surface heights from the geometry.
            bounds = None
            world_bbox = bbox_cache.ComputeWorldBound(prim)
            rng = world_bbox.ComputeAlignedRange()
            if not rng.IsEmpty():
                mn = rng.GetMin()
                mx = rng.GetMax()
                bounds = {
                    "min": {
                        "x": round(mn[0], 4),
                        "y": round(mn[1], 4),
                        "z": round(mn[2], 4),
                    },
                    "max": {
                        "x": round(mx[0], 4),
                        "y": round(mx[1], 4),
                        "z": round(mx[2], 4),
                    },
                }

            asset_path = None
            for ref_list in [
                refs.prependedItems,
                refs.appendedItems,
                refs.explicitItems,
            ]:
                if ref_list:
                    for ref in ref_list:
                        asset_path = ref.assetPath
                        break

            objects.append({
                "prim_path": str(prim.GetPath()),
                "asset": asset_path,
                "position": position,
                "bounds": bounds,
            })

        return objects

    def rename_prim(self, old_path: str, new_path: str) -> bool:
        """Move/rename a prim to a new path in the hierarchy."""

        if self._stage is None:
            msg = "No stage open."
            raise RuntimeError(msg)

        old_prim = self._stage.GetPrimAtPath(old_path)
        if not old_prim.IsValid():
            msg = f"Prim not found: {old_path}"
            raise ValueError(msg)

        # Ensure parent hierarchy exists
        parent_path = str(Sdf.Path(new_path).GetParentPath())
        if parent_path and parent_path != "/":
            parent_prim = self._stage.GetPrimAtPath(parent_path)
            if not parent_prim.IsValid():
                self._stage.DefinePrim(parent_path, "Xform")

        layer = self._stage.GetRootLayer()
        edit = Sdf.BatchNamespaceEdit()
        edit.Add(old_path, new_path)
        success = layer.Apply(edit)

        if success:
            self._stage.Save()
            # Reload stage to pick up namespace changes
            self._stage = Usd.Stage.Open(str(self._stage.GetRootLayer().realPath))

        return success

    def remove_prim(self, prim_path: str) -> bool:
        """Remove a prim from the stage."""

        if self._stage is None:
            msg = "No stage open."
            raise RuntimeError(msg)

        prim = self._stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            msg = f"Prim not found: {prim_path}"
            raise ValueError(msg)

        result = self._stage.RemovePrim(prim_path)
        if result:
            self._stage.Save()

        return result

    def open_stage(self, path: str | Path) -> None:
        """Open an existing USD stage from disk."""
        self._stage = Usd.Stage.Open(str(path))

    # ── Material Operations ──────────────────────────────────────

    def add_material_sublayer(self, material_path: str) -> None:
        """Add a material .usda file as a sublayer to the current stage.

        The material definitions inside the file (e.g. ``/mtl/wood_varnished``)
        become available for binding. Deduplicates: if the sublayer path
        is already present, this is a no-op.
        """
        if self._stage is None:
            msg = "No stage open. Call create_stage() first."
            raise RuntimeError(msg)

        root_layer = self._stage.GetRootLayer()
        existing = list(root_layer.subLayerPaths)

        # Normalize to forward slashes for comparison
        normalized = material_path.replace("\\", "/")
        if normalized not in [p.replace("\\", "/") for p in existing]:
            root_layer.subLayerPaths.append(normalized)

    def bind_material(self, prim_path: str, material_prim_path: str) -> None:
        """Bind a material to a prim using UsdShade.MaterialBindingAPI.

        After binding, removes any sublayered material files that are
        no longer bound to any prim in the scene.

        Parameters:
            prim_path: The target geometry prim
                (e.g. ``"/Scene/Furniture/Table_01"``).
            material_prim_path: The USD prim path of the material
                (e.g. ``"/mtl/wood_varnished"``), NOT a file path.
        """
        if self._stage is None:
            msg = "No stage open."
            raise RuntimeError(msg)

        prim = self._stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            msg = f"Prim not found: {prim_path}"
            raise ValueError(msg)

        material_prim = self._stage.GetPrimAtPath(material_prim_path)
        if not material_prim.IsValid():
            msg = (
                f"Material prim not found: {material_prim_path}. "
                "Is the material file sublayered?"
            )
            raise ValueError(msg)

        material = UsdShade.Material(material_prim)
        if not material:
            msg = f"Prim at {material_prim_path} is not a Material."
            raise ValueError(msg)

        binding_api = UsdShade.MaterialBindingAPI.Apply(prim)
        binding_api.Bind(material)

        self.cleanup_unused_material_sublayers()

    def cleanup_unused_material_sublayers(self) -> int:
        """Remove sublayered material files that no bound prim references.

        Walks all prims to collect bound material prim paths, then checks
        each sublayer. If a sublayer contributes no materials that are
        currently bound, it is removed from the sublayer list.

        Returns the number of sublayers removed.
        """
        if self._stage is None:
            return 0

        # Collect all material prim paths that are actively bound
        bound_materials: set[str] = set()
        for prim in self._stage.Traverse():
            binding_api = UsdShade.MaterialBindingAPI(prim)
            bound_mat, _ = binding_api.ComputeBoundMaterial()
            if bound_mat:
                bound_materials.add(str(bound_mat.GetPath()))

        # Check each sublayer — does it define any bound material?
        root_layer = self._stage.GetRootLayer()
        stage_dir = os.path.dirname(root_layer.realPath)
        keep: list[str] = []
        removed = 0

        for sub_path in root_layer.subLayerPaths:
            abs_path = os.path.join(stage_dir, sub_path)

            is_needed = False
            temp_stage = Usd.Stage.Open(abs_path)
            if temp_stage:
                for p in temp_stage.Traverse():
                    if p.IsA(UsdShade.Material):
                        if str(p.GetPath()) in bound_materials:
                            is_needed = True
                            break
            else:
                # Can't open the file — keep it to be safe
                is_needed = True

            if is_needed:
                keep.append(sub_path)
            else:
                removed += 1

        # Replace sublayer list with only the needed ones
        root_layer.subLayerPaths.clear()
        for path in keep:
            root_layer.subLayerPaths.append(path)

        return removed

    def clear_material_bindings(self, prim_path: str) -> None:
        """Remove material:binding opinions on a prim.

        Used before applying a look file to clear manual bindings
        that would otherwise override the look file's opinions.
        """
        if self._stage is None:
            msg = "No stage open."
            raise RuntimeError(msg)

        prim = self._stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            msg = f"Prim not found: {prim_path}"
            raise ValueError(msg)

        binding_api = UsdShade.MaterialBindingAPI(prim)
        binding_api.UnbindAllBindings()

    def swap_reference(self, prim_path: str, new_asset_path: str) -> None:
        """Replace the reference on a prim with a new one, preserving transforms.

        Used to swap a geometry reference for a look file reference.
        The existing translate, rotate, and scale xform ops are preserved.
        """
        if self._stage is None:
            msg = "No stage open."
            raise RuntimeError(msg)

        prim = self._stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            msg = f"Prim not found: {prim_path}"
            raise ValueError(msg)

        # Capture current transform ops before modifying references
        xformable = UsdGeom.Xformable(prim)
        saved_ops: list[tuple] = []
        for op in xformable.GetOrderedXformOps():
            saved_ops.append((op.GetOpType(), op.Get()))

        # Clear all references and add the new one
        prim.GetReferences().ClearReferences()
        prim.GetReferences().AddReference(new_asset_path.replace("\\", "/"))

        # Re-apply the saved transform ops
        xformable.ClearXformOpOrder()
        for op_type, value in saved_ops:
            if op_type == UsdGeom.XformOp.TypeTranslate:
                xformable.AddTranslateOp().Set(value)
            elif op_type == UsdGeom.XformOp.TypeRotateXYZ:
                xformable.AddRotateXYZOp().Set(value)
            elif op_type == UsdGeom.XformOp.TypeScale:
                xformable.AddScaleOp().Set(value)

    def list_materials(self) -> list[dict]:
        """Return all materials in the scene and their bindings.

        Returns a list of dicts with:
          - ``material_path``: the USD prim path of the material
          - ``material_name``: the material's display name
          - ``bound_prims``: list of prim paths bound to this material
        """
        if self._stage is None:
            return []

        # Collect all material prims
        materials: dict[str, list[str]] = {}
        for prim in self._stage.Traverse():
            if prim.IsA(UsdShade.Material):
                materials[str(prim.GetPath())] = []

        # Find all bindings
        for prim in self._stage.Traverse():
            binding_api = UsdShade.MaterialBindingAPI(prim)
            bound_mat, _ = binding_api.ComputeBoundMaterial()
            if bound_mat:
                mat_path = str(bound_mat.GetPath())
                if mat_path in materials:
                    materials[mat_path].append(str(prim.GetPath()))

        return [
            {
                "material_path": mat_path,
                "material_name": Sdf.Path(mat_path).name,
                "bound_prims": bound_prims,
            }
            for mat_path, bound_prims in materials.items()
        ]

    def list_prim_children(self, prim_path: str) -> list[dict]:
        """Return all descendant prims of the given prim with their types.

        For each descendant, reports:
          - ``prim_path``: full USD path
          - ``name``: the prim's name (leaf)
          - ``type``: the USD type name (Mesh, Xform, Scope, etc.)
          - ``has_geometry``: whether this prim or its children contain mesh data
          - ``current_material``: the currently bound material path, if any

        This is used to discover the internal parts of a referenced asset
        (e.g. table top, legs, frame) so the user can target specific
        parts for material binding.
        """
        if self._stage is None:
            return []

        root_prim = self._stage.GetPrimAtPath(prim_path)
        if not root_prim.IsValid():
            return []

        results = []
        for prim in Usd.PrimRange(root_prim):
            # Skip the root prim itself
            if str(prim.GetPath()) == prim_path:
                continue

            type_name = prim.GetTypeName()

            # Check if this prim is a mesh or has mesh children
            is_mesh = type_name == "Mesh"
            has_geometry = is_mesh
            if not has_geometry:
                for child in Usd.PrimRange(prim):
                    if child.GetTypeName() == "Mesh":
                        has_geometry = True
                        break

            # Get current material binding if any
            current_material = None
            binding_api = UsdShade.MaterialBindingAPI(prim)
            bound_mat, _ = binding_api.ComputeBoundMaterial()
            if bound_mat:
                current_material = str(bound_mat.GetPath())

            # Only include prims that are meshes or contain geometry
            if has_geometry:
                results.append({
                    "prim_path": str(prim.GetPath()),
                    "name": prim.GetName(),
                    "type": type_name or "Xform",
                    "is_mesh": is_mesh,
                    "current_material": current_material,
                })

        return results

    @property
    def stage(self):  # noqa: ANN201
        """Access the underlying Usd.Stage (for validator, etc.)."""
        return self._stage
