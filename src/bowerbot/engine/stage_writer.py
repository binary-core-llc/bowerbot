# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""StageWriter — creates and writes USD stages.

Handles all direct USD API calls: creating stages, adding references,
setting transforms, managing composition arcs.
"""

import os
from pathlib import Path

from pxr import Gf, Kind, Sdf, Usd, UsdGeom, UsdLux, UsdShade

from bowerbot.utils.usd_utils import LIGHT_CLASSES, get_prim_ref_paths
from bowerbot.schemas import LightParams, SceneObject


class StageWriter:
    """Writes USD stages using the pxr API.

    All USD file operations are centralized here so the rest of
    BowerBot never touches pxr directly.
    """

    def __init__(self, meters_per_unit: float = 1.0, up_axis: str = "Y") -> None:
        self.meters_per_unit = meters_per_unit
        self.up_axis = up_axis
        self._stage = None

    @staticmethod
    def create_empty_scene(path: str | Path) -> None:
        """Create a minimal scene file with BowerBot defaults.

        Writes metersPerUnit, upAxis, and a root /Scene Xform.
        Does not retain the stage — used for project initialization.
        Skips creation if the file already exists.
        """
        path = Path(path)
        if path.exists():
            return

        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

        root = stage.DefinePrim("/Scene", "Xform")
        stage.SetDefaultPrim(root)
        Usd.ModelAPI(root).SetKind(Kind.Tokens.assembly)

        stage.Save()

    def create_stage(self, path: str | Path) -> None:
        """Create a new USD stage and keep it open for editing."""
        self.create_empty_scene(path)
        self._stage = Usd.Stage.Open(str(path))

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

    def add_reference(self, scene_object: SceneObject) -> None:
        """Add a referenced asset to the stage at the given prim path.

        Uses a wrapper prim pattern to keep BowerBot's positioning
        separate from the referenced geometry's own transforms:

          /Scene/Furniture/Table_01  (wrapper: translate + scale)
            /Scene/Furniture/Table_01/asset  (reference: geometry's own ops)

        This ensures DCC export transforms (Maya pivots, rotations)
        are preserved untouched inside the reference while BowerBot
        controls positioning through the parent wrapper.
        """
        if self._stage is None:
            msg = "No stage open. Call create_stage() first."
            raise RuntimeError(msg)

        asset_path = (
            scene_object.asset.file_path
            or scene_object.asset.source_id
        )

        # Compute unit conversion before adding the reference
        unit_scale = self._compute_unit_scale(asset_path)

        # Create wrapper prim with BowerBot's transform
        wrapper = self._stage.DefinePrim(
            scene_object.prim_path, "Xform",
        )
        xformable = UsdGeom.Xformable(wrapper)

        tx, ty, tz = scene_object.translate
        xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))

        rx, ry, rz = scene_object.rotate
        if any(v != 0.0 for v in (rx, ry, rz)):
            xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))

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

        # Create child prim with the reference — geometry's own
        # xformOps live here, untouched by the wrapper's ops
        asset_prim = self._stage.DefinePrim(
            f"{scene_object.prim_path}/asset", "Xform",
        )
        asset_prim.GetReferences().AddReference(asset_path)

    def create_light(self, light: LightParams) -> None:
        """Create a USD light prim in the stage."""
        if self._stage is None:
            msg = "No stage open. Call create_stage() first."
            raise RuntimeError(msg)

        light_cls = LIGHT_CLASSES[light.light_type.value]
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

    def update_light(
        self,
        prim_path: str,
        intensity: float | None = None,
        color: tuple[float, float, float] | None = None,
        translate: tuple[float, float, float] | None = None,
        rotate: tuple[float, float, float] | None = None,
        **extra_attrs: float | None,
    ) -> None:
        """Update an existing scene-level light's attributes.

        Only modifies parameters that are provided (not None).
        """
        if self._stage is None:
            msg = "No stage open."
            raise RuntimeError(msg)

        prim = self._stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            msg = f"Prim not found: {prim_path}"
            raise ValueError(msg)

        if intensity is not None:
            attr = prim.GetAttribute("inputs:intensity")
            if attr:
                attr.Set(intensity)

        if color is not None:
            attr = prim.GetAttribute("inputs:color")
            if attr:
                attr.Set(Gf.Vec3f(*color))

        for attr_name, usd_attr in {
            "radius": "inputs:radius",
            "angle": "inputs:angle",
            "width": "inputs:width",
            "height": "inputs:height",
            "length": "inputs:length",
        }.items():
            value = extra_attrs.get(attr_name)
            if value is not None:
                attr = prim.GetAttribute(usd_attr)
                if attr:
                    attr.Set(float(value))

        if translate is not None:
            xformable = UsdGeom.Xformable(prim)
            for op in xformable.GetOrderedXformOps():
                if op.GetOpName() == "xformOp:translate":
                    op.Set(Gf.Vec3d(*translate))
                    break

        if rotate is not None:
            xformable = UsdGeom.Xformable(prim)
            for op in xformable.GetOrderedXformOps():
                if (
                    op.GetOpType()
                    == UsdGeom.XformOp.TypeRotateXYZ
                ):
                    op.Set(Gf.Vec3f(*rotate))
                    break

    def set_transform(
        self,
        prim_path: str,
        translate: tuple[float, float, float],
        rotate: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        """Update the transform on an existing prim.

        Only modifies the translate, rotate, and scale ops that
        BowerBot authored. Preserves any unit-conversion scale.
        Does not touch the referenced geometry's own transforms.
        """
        if self._stage is None:
            msg = "No stage open."
            raise RuntimeError(msg)

        prim = self._stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            msg = f"Prim not found: {prim_path}"
            raise ValueError(msg)

        xformable = UsdGeom.Xformable(prim)

        # Update existing ops in-place rather than clearing
        tx, ty, tz = translate
        rx, ry, rz = rotate

        found_translate = False
        found_rotate = False

        for op in xformable.GetOrderedXformOps():
            if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                if op.GetOpName() == "xformOp:translate":
                    op.Set(Gf.Vec3d(tx, ty, tz))
                    found_translate = True
            elif op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                op.Set(Gf.Vec3f(rx, ry, rz))
                found_rotate = True

        # If ops don't exist yet (shouldn't happen), add them
        if not found_translate:
            xformable.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))
        if not found_rotate and any(v != 0.0 for v in (rx, ry, rz)):
            xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))

    def save(self) -> None:
        if self._stage is None:
            msg = "No stage open."
            raise RuntimeError(msg)
        self._stage.Save()

    def list_prims(self) -> list[dict]:
        """List all placed objects and lights in the stage."""
        if self._stage is None:
            return []

        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_],
        )

        results = []
        for prim in self._stage.Traverse():
            is_light = prim.HasAPI(UsdLux.LightAPI)
            has_refs = prim.GetMetadata("references") is not None

            if not has_refs and not is_light:
                continue

            position = self._extract_position(prim)

            if is_light:
                results.append(self._format_light_prim(prim, position))
            else:
                results.append(
                    self._format_geometry_prim(prim, position, bbox_cache),
                )

        return results

    @staticmethod
    def _extract_position(prim: Usd.Prim) -> dict[str, float] | None:
        xformable = UsdGeom.Xformable(prim)
        if not xformable:
            return None
        t = xformable.GetLocalTransformation().ExtractTranslation()
        return {"x": round(t[0], 2), "y": round(t[1], 2), "z": round(t[2], 2)}

    @staticmethod
    def _format_light_prim(
        prim: Usd.Prim, position: dict[str, float] | None,
    ) -> dict:
        data: dict = {
            "prim_path": str(prim.GetPath()),
            "light_type": prim.GetTypeName(),
            "position": position,
        }
        intensity_attr = prim.GetAttribute("inputs:intensity")
        if intensity_attr:
            data["intensity"] = intensity_attr.Get()
        color_attr = prim.GetAttribute("inputs:color")
        if color_attr:
            c = color_attr.Get()
            data["color"] = {
                "r": round(c[0], 3), "g": round(c[1], 3), "b": round(c[2], 3),
            }
        return data

    @staticmethod
    def _format_geometry_prim(
        prim: Usd.Prim,
        position: dict[str, float] | None,
        bbox_cache: UsdGeom.BBoxCache,
    ) -> dict:
        bounds = None
        rng = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if not rng.IsEmpty():
            mn, mx = rng.GetMin(), rng.GetMax()
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

        ref_paths = get_prim_ref_paths(prim)
        return {
            "prim_path": str(prim.GetPath()),
            "asset": ref_paths[0] if ref_paths else None,
            "position": position,
            "bounds": bounds,
        }

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
