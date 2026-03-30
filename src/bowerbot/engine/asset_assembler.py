# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""AssetAssembler — creates and manages ASWF-compliant USD asset folders.

Builds asset folders incrementally as the user works:
1. place_asset creates the folder with root + geo.usda
2. bind_material adds materials into mtl.usda
3. remove_material_binding cleans up mtl.usda

Follows the ASWF USD Working Group asset structure guidelines:

    asset_name/
      asset_name.usd   <- root (sublayers geo.usda + mtl.usda)
      geo.usda          <- geometry layer
      mtl.usda          <- materials defined inline + bindings
      maps/            <- texture files

Reference: https://github.com/usd-wg/assets/blob/main/docs/asset-structure-guidelines.md
"""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade

from bowerbot.schemas import ASWFLayerNames

logger = logging.getLogger(__name__)


class AssetAssembler:
    """Creates and manages ASWF-compliant USD asset folders.

    All pxr API usage for asset folder operations lives here.
    Skills call this through the engine layer — they never touch pxr.
    """

    def create_asset_folder(
        self,
        output_dir: Path,
        asset_name: str,
        geometry_file: Path,
    ) -> Path:
        """Create an ASWF asset folder with root + geo.usda.

        Parameters:
            output_dir: Parent directory for the asset folder.
            asset_name: Name for the asset (folder + root file name).
            geometry_file: Source geometry file to copy.

        Returns:
            Path to the root file (``output_dir/asset_name/asset_name.usd``).
        """
        asset_dir = output_dir / asset_name
        asset_dir.mkdir(parents=True, exist_ok=True)

        # Read source metadata
        mpu, up = self._read_stage_metadata(geometry_file)

        # Create geo.usda from source geometry
        geo_path = asset_dir / ASWFLayerNames.GEO
        if not geo_path.exists():
            self._create_geo_layer(geo_path, geometry_file)

        # Create root file that sublayers geo.usda
        root_path = asset_dir / f"{asset_name}.usda"
        if not root_path.exists():
            self._create_root_file(root_path, mpu, up, has_mtl=False)

        logger.info("Created ASWF asset folder: %s", asset_dir)
        return root_path

    def add_material(
        self,
        asset_dir: Path,
        material_file: Path,
        prim_path: str,
        material_prim_path: str | None = None,
    ) -> str:
        """Add a material to an asset folder's mtl.usda.

        Copies the material definition inline into mtl.usda and writes
        the binding opinion. Creates mtl.usda if it doesn't exist and
        updates the root file to sublayer it.

        Parameters:
            asset_dir: Path to the asset folder.
            material_file: Source material .usda file.
            prim_path: Geometry prim path to bind to
                (relative to the asset root, e.g. ``"/table/top"``).
            material_prim_path: Material prim path (e.g. ``"/mtl/wood"``).
                If None, discovers the first Material in the file.

        Returns:
            The material prim path that was bound.
        """
        mtl_path = asset_dir / ASWFLayerNames.MTL

        # Discover material prim path if not provided
        if not material_prim_path:
            material_prim_path = self._find_first_material(material_file)
            if not material_prim_path:
                msg = f"No Material prim found in {material_file.name}"
                raise ValueError(msg)

        # Create or open mtl.usda
        if mtl_path.exists():
            mtl_layer = Sdf.Layer.FindOrOpen(str(mtl_path))
        else:
            mpu, up = self._read_stage_metadata_from_dir(asset_dir)
            mtl_layer = Sdf.Layer.CreateNew(str(mtl_path))
            mtl_layer.defaultPrim = "mtl"

        # Copy the material definition inline from source
        source_layer = Sdf.Layer.FindOrOpen(str(material_file))
        if source_layer is None:
            msg = f"Cannot open material file: {material_file}"
            raise RuntimeError(msg)

        # Get the asset root prim name (e.g. "table") so materials
        # and bindings are structured under the same namespace.
        # When mtl.usda is referenced onto /table, everything maps correctly:
        #   /table/mtl/wood → material
        #   /table/top      → geometry with binding to /table/mtl/wood
        default_prim_name = self._get_default_prim_name(asset_dir)
        if not default_prim_name:
            default_prim_name = asset_dir.name

        # Ensure /{root}/mtl scope exists in mtl.usda
        mtl_scope_path = Sdf.Path(f"/{default_prim_name}/mtl")
        root_prim_path = Sdf.Path(f"/{default_prim_name}")

        if not mtl_layer.GetPrimAtPath(root_prim_path):
            Sdf.CreatePrimInLayer(mtl_layer, root_prim_path)
            mtl_layer.GetPrimAtPath(root_prim_path).specifier = (
                Sdf.SpecifierOver
            )

        if not mtl_layer.GetPrimAtPath(mtl_scope_path):
            Sdf.CreatePrimInLayer(mtl_layer, mtl_scope_path)
            mtl_layer.GetPrimAtPath(mtl_scope_path).specifier = (
                Sdf.SpecifierDef
            )
            mtl_layer.GetPrimAtPath(mtl_scope_path).typeName = "Scope"

        # Extract material name from prim path (e.g. /mtl/wood → wood)
        mat_name = Sdf.Path(material_prim_path).name
        dest_mat_path = Sdf.Path(f"/{default_prim_name}/mtl/{mat_name}")

        # Copy the material definition into the asset's namespace
        source_mat_path = Sdf.Path(material_prim_path)
        Sdf.CopySpec(
            source_layer, source_mat_path,
            mtl_layer, dest_mat_path,
        )

        mtl_layer.defaultPrim = default_prim_name
        mtl_layer.Save()

        # Author binding opinion.
        # Strip the root prim prefix from the target prim path since
        # we're authoring inside mtl.usda under /{default_prim_name}.
        prefix = f"/{default_prim_name}"
        relative_prim = prim_path
        if prim_path.startswith(prefix):
            relative_prim = prim_path[len(prefix):]
            if not relative_prim:
                relative_prim = "/"
        bind_prim_path = f"/{default_prim_name}{relative_prim}"

        # The material path in the composed stage
        composed_mat_path = f"/{default_prim_name}/mtl/{mat_name}"

        stage = Usd.Stage.Open(str(mtl_path))
        if stage is not None:
            prim = stage.OverridePrim(bind_prim_path)
            mat_prim = stage.GetPrimAtPath(composed_mat_path)
            if mat_prim.IsValid():
                material = UsdShade.Material(mat_prim)
                binding_api = UsdShade.MaterialBindingAPI.Apply(prim)
                binding_api.Bind(material)
            stage.Save()

        # Update the returned material prim path to the composed path
        material_prim_path = composed_mat_path

        # Ensure root file sublayers mtl.usda
        self._ensure_root_references_mtl(asset_dir)

        logger.info(
            "Added material %s -> %s in %s",
            material_prim_path, prim_path, asset_dir.name,
        )
        return material_prim_path

    def remove_material_binding(
        self,
        asset_dir: Path,
        prim_path: str,
    ) -> None:
        """Remove a material binding from an asset folder's mtl.usda.

        Clears the binding opinion. If no bindings remain in mtl.usda,
        removes it and updates the root file.

        Parameters:
            asset_dir: Path to the asset folder.
            prim_path: Geometry prim path to unbind.
        """
        mtl_path = asset_dir / ASWFLayerNames.MTL
        if not mtl_path.exists():
            return

        # Convert composed prim path to mtl.usda-local path
        default_prim_name = self._get_default_prim_name(asset_dir)
        if not default_prim_name:
            default_prim_name = asset_dir.name

        prefix = f"/{default_prim_name}"
        relative_prim = prim_path
        if prim_path.startswith(prefix):
            relative_prim = prim_path[len(prefix):]
        local_path = f"/{default_prim_name}{relative_prim}"

        stage = Usd.Stage.Open(str(mtl_path))
        if stage is None:
            return

        prim = stage.GetPrimAtPath(local_path)
        if prim.IsValid():
            binding_api = UsdShade.MaterialBindingAPI(prim)
            binding_api.UnbindAllBindings()

        stage.Save()

        # Clean up unused materials
        self._cleanup_unused_materials(mtl_path, asset_dir)

    def list_materials(self, asset_dir: Path) -> list[dict]:
        """List all materials and bindings in an asset folder's mtl.usda.

        Returns a list of dicts with material_path, material_name,
        and bound_prims.
        """
        mtl_path = asset_dir / ASWFLayerNames.MTL
        if not mtl_path.exists():
            return []

        # Open the full asset to resolve composition
        root_file = self._find_root_file(asset_dir)
        if root_file is None:
            return []

        stage = Usd.Stage.Open(str(root_file))
        if stage is None:
            return []

        materials: dict[str, list[str]] = {}
        for prim in stage.Traverse():
            if prim.IsA(UsdShade.Material):
                materials[str(prim.GetPath())] = []

        for prim in stage.Traverse():
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

    def get_geometry_bounds(
        self, asset_dir: Path,
    ) -> dict[str, dict[str, float]] | None:
        """Return the asset's geometry bounds in meters.

        Opens the root file, computes world bounds of the default
        prim, and converts from asset units to meters.

        Returns a dict with 'min', 'max', 'center', and 'size'
        keys, each containing x, y, z values in meters.
        Returns None if bounds cannot be computed.
        """
        root_file = self._find_root_file(asset_dir)
        if root_file is None:
            return None

        geo_path = asset_dir / ASWFLayerNames.GEO
        if not geo_path.exists():
            return None

        stage = Usd.Stage.Open(str(geo_path))
        if stage is None:
            return None

        root = stage.GetDefaultPrim()
        if root is None:
            return None

        bbox = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_],
        )
        rng = bbox.ComputeWorldBound(root).ComputeAlignedRange()
        if rng.IsEmpty():
            return None

        mpu, _ = self._read_stage_metadata_from_dir(asset_dir)
        mn = rng.GetMin()
        mx = rng.GetMax()

        return {
            "min": {
                "x": mn[0] * mpu,
                "y": mn[1] * mpu,
                "z": mn[2] * mpu,
            },
            "max": {
                "x": mx[0] * mpu,
                "y": mx[1] * mpu,
                "z": mx[2] * mpu,
            },
            "center": {
                "x": (mn[0] + mx[0]) / 2 * mpu,
                "y": (mn[1] + mx[1]) / 2 * mpu,
                "z": (mn[2] + mx[2]) / 2 * mpu,
            },
            "size": {
                "x": (mx[0] - mn[0]) * mpu,
                "y": (mx[1] - mn[1]) * mpu,
                "z": (mx[2] - mn[2]) * mpu,
            },
        }

    # ── Light Operations ──────────────────────────────────────────

    def add_light(
        self,
        asset_dir: Path,
        light_name: str,
        light_type: str,
        translate: tuple[float, float, float] = (0.0, 0.0, 0.0),
        rotate: tuple[float, float, float] = (0.0, 0.0, 0.0),
        intensity: float = 1000.0,
        color: tuple[float, float, float] = (1.0, 1.0, 1.0),
        **extra_attrs: float | str | None,
    ) -> str:
        """Add a light to an asset folder's lgt.usda.

        Creates lgt.usda if it doesn't exist and updates the root
        file to reference it. Lights are defined under
        ``/{default_prim}/lgt/{light_name}``.

        Parameters:
            asset_dir: Path to the asset folder.
            light_name: Name for the light prim (e.g. "bulb").
            light_type: USD light type (e.g. "SphereLight").
            translate: Position relative to the asset origin.
            rotate: Rotation in degrees (X, Y, Z).
            intensity: Light intensity.
            color: RGB color (0-1).
            **extra_attrs: Type-specific attributes (angle, radius,
                width, height, length, texture).

        Returns:
            The light prim path in the composed stage.
        """
        lgt_path = asset_dir / ASWFLayerNames.LGT

        default_prim_name = self._get_default_prim_name(asset_dir)
        if not default_prim_name:
            default_prim_name = asset_dir.name

        # Create or open lgt.usda
        if lgt_path.exists():
            lgt_layer = Sdf.Layer.FindOrOpen(str(lgt_path))
        else:
            lgt_layer = Sdf.Layer.CreateNew(str(lgt_path))
            lgt_layer.defaultPrim = default_prim_name

        # Ensure /{root}/lgt scope exists
        root_prim_path = Sdf.Path(f"/{default_prim_name}")
        lgt_scope_path = Sdf.Path(f"/{default_prim_name}/lgt")

        if not lgt_layer.GetPrimAtPath(root_prim_path):
            Sdf.CreatePrimInLayer(lgt_layer, root_prim_path)
            lgt_layer.GetPrimAtPath(root_prim_path).specifier = (
                Sdf.SpecifierOver
            )

        if not lgt_layer.GetPrimAtPath(lgt_scope_path):
            Sdf.CreatePrimInLayer(lgt_layer, lgt_scope_path)
            scope = lgt_layer.GetPrimAtPath(lgt_scope_path)
            scope.specifier = Sdf.SpecifierDef
            scope.typeName = "Xform"

        lgt_layer.Save()

        # Apply inverse of geometry's root transform on the lgt
        # Xform. This cancels the inherited transform from the
        # root prim, so lights are in clean world-aligned space.
        # Same principle as the wrapper prim for scene placement.
        self._apply_inverse_transform(asset_dir, lgt_path, lgt_scope_path)

        # Create the light prim using UsdLux
        stage = Usd.Stage.Open(str(lgt_path))
        if stage is None:
            msg = f"Cannot open lgt layer: {lgt_path}"
            raise RuntimeError(msg)

        light_prim_path = f"/{default_prim_name}/lgt/{light_name}"

        light_classes = {
            "DistantLight": UsdLux.DistantLight,
            "DomeLight": UsdLux.DomeLight,
            "SphereLight": UsdLux.SphereLight,
            "RectLight": UsdLux.RectLight,
            "DiskLight": UsdLux.DiskLight,
            "CylinderLight": UsdLux.CylinderLight,
        }

        light_cls = light_classes.get(light_type)
        if light_cls is None:
            msg = f"Unknown light type: {light_type}"
            raise ValueError(msg)

        light_prim = light_cls.Define(stage, light_prim_path)
        light_prim.CreateIntensityAttr(intensity)
        light_prim.CreateColorAttr(Gf.Vec3f(*color))

        # Type-specific attributes
        attr_map = {
            "angle": "CreateAngleAttr",
            "texture": "CreateTextureFileAttr",
            "radius": "CreateRadiusAttr",
            "width": "CreateWidthAttr",
            "height": "CreateHeightAttr",
            "length": "CreateLengthAttr",
        }
        for attr_name, create_method in attr_map.items():
            value = extra_attrs.get(attr_name)
            if value is not None and hasattr(light_prim, create_method):
                getattr(light_prim, create_method)().Set(value)

        # The lgt Xform has an inverse transform that cancels
        # the geometry's root ops. Lights are in clean space —
        # author positions in meters, radii in meters, etc.
        # The scene's unit scale handles the final conversion.
        mpu, _ = self._read_stage_metadata_from_dir(asset_dir)
        unit_factor = 1.0 / mpu if mpu > 0 else 1.0

        tx, ty, tz = translate
        xformable = UsdGeom.Xformable(light_prim)
        xformable.AddTranslateOp().Set(
            Gf.Vec3d(
                tx * unit_factor,
                ty * unit_factor,
                tz * unit_factor,
            ),
        )

        rx, ry, rz = rotate
        if any(v != 0.0 for v in (rx, ry, rz)):
            xformable.AddRotateXYZOp().Set(Gf.Vec3f(rx, ry, rz))

        stage.Save()

        # Ensure root file references lgt.usda
        self._ensure_root_references_lgt(asset_dir)

        composed_path = f"/{default_prim_name}/lgt/{light_name}"
        logger.info(
            "Added light %s (%s) to %s",
            light_name, light_type, asset_dir.name,
        )
        return composed_path

    def update_light(
        self,
        asset_dir: Path,
        light_name: str,
        translate: tuple[float, float, float] | None = None,
        rotate: tuple[float, float, float] | None = None,
        intensity: float | None = None,
        color: tuple[float, float, float] | None = None,
        **extra_attrs: float | str | None,
    ) -> None:
        """Update an existing light's attributes in an asset folder.

        Only modifies parameters that are provided (not None).
        The light must already exist in lgt.usda.
        """
        lgt_path = asset_dir / ASWFLayerNames.LGT
        if not lgt_path.exists():
            msg = f"No {ASWFLayerNames.LGT} found in asset folder"
            raise ValueError(msg)

        default_prim_name = self._get_default_prim_name(asset_dir)
        if not default_prim_name:
            default_prim_name = asset_dir.name

        light_prim_path = f"/{default_prim_name}/lgt/{light_name}"

        stage = Usd.Stage.Open(str(lgt_path))
        if stage is None:
            msg = f"Cannot open lgt layer: {lgt_path}"
            raise RuntimeError(msg)

        prim = stage.GetPrimAtPath(light_prim_path)
        if not prim.IsValid():
            msg = f"Light not found: {light_name}"
            raise ValueError(msg)

        # Update common attributes
        if intensity is not None:
            prim.GetAttribute("inputs:intensity").Set(intensity)

        if color is not None:
            prim.GetAttribute("inputs:color").Set(
                Gf.Vec3f(*color),
            )

        # Update type-specific attributes (convert spatial ones)
        spatial_attrs = {"radius", "width", "height", "length"}
        attr_map = {
            "angle": "inputs:angle",
            "texture": "inputs:texture:file",
            "radius": "inputs:radius",
            "width": "inputs:width",
            "height": "inputs:height",
            "length": "inputs:length",
        }
        for attr_name, usd_attr in attr_map.items():
            value = extra_attrs.get(attr_name)
            if value is not None:
                if attr_name in spatial_attrs:
                    value = self._meters_to_asset_units(
                        asset_dir, float(value),
                    )
                attr = prim.GetAttribute(usd_attr)
                if attr:
                    attr.Set(value)

        # Update transform (convert to asset units)
        if translate is not None:
            mpu, _ = self._read_stage_metadata_from_dir(
                asset_dir,
            )
            uf = 1.0 / mpu if mpu > 0 else 1.0
            converted = (
                translate[0] * uf,
                translate[1] * uf,
                translate[2] * uf,
            )
            xformable = UsdGeom.Xformable(prim)
            for op in xformable.GetOrderedXformOps():
                if op.GetOpName() == "xformOp:translate":
                    op.Set(Gf.Vec3d(*converted))
                    break
            else:
                xformable.AddTranslateOp().Set(
                    Gf.Vec3d(*converted),
                )

        if rotate is not None:
            xformable = UsdGeom.Xformable(prim)
            found = False
            for op in xformable.GetOrderedXformOps():
                if (
                    op.GetOpType()
                    == UsdGeom.XformOp.TypeRotateXYZ
                ):
                    op.Set(Gf.Vec3f(*rotate))
                    found = True
                    break
            if not found and any(v != 0.0 for v in rotate):
                xformable.AddRotateXYZOp().Set(
                    Gf.Vec3f(*rotate),
                )

        stage.Save()
        logger.info(
            "Updated light %s in %s",
            light_name, asset_dir.name,
        )

    def remove_light(
        self,
        asset_dir: Path,
        light_name: str,
    ) -> None:
        """Remove a light from an asset folder's lgt.usda.

        If no lights remain, removes lgt.usda and updates the root.
        """
        lgt_path = asset_dir / ASWFLayerNames.LGT
        if not lgt_path.exists():
            return

        default_prim_name = self._get_default_prim_name(asset_dir)
        if not default_prim_name:
            default_prim_name = asset_dir.name

        light_prim_path = Sdf.Path(
            f"/{default_prim_name}/lgt/{light_name}",
        )

        lgt_layer = Sdf.Layer.FindOrOpen(str(lgt_path))
        if lgt_layer is None:
            return

        if lgt_layer.GetPrimAtPath(light_prim_path):
            edit = Sdf.BatchNamespaceEdit()
            edit.Add(light_prim_path, Sdf.Path.emptyPath)
            lgt_layer.Apply(edit)
            lgt_layer.Save()

        # If no lights remain, remove lgt.usda
        stage = Usd.Stage.Open(str(lgt_path))
        has_lights = False
        if stage:
            for prim in stage.Traverse():
                if prim.HasAPI(UsdLux.LightAPI):
                    has_lights = True
                    break

        if not has_lights:
            lgt_path.unlink()

            # Remove reference from root file
            root_file = self._find_root_file(asset_dir)
            if root_file:
                stage = Usd.Stage.Open(str(root_file))
                if stage:
                    root_prim = stage.GetDefaultPrim()
                    if root_prim:
                        root_prim.GetReferences().ClearReferences()
                        # Re-add geo and mtl if they exist
                        mtl_path = asset_dir / ASWFLayerNames.MTL
                        if mtl_path.exists():
                            root_prim.GetReferences().AddReference(
                                f"./{ASWFLayerNames.MTL}",
                            )
                        root_prim.GetReferences().AddReference(
                            f"./{ASWFLayerNames.GEO}",
                        )
                    stage.Save()

            logger.info(
                "Removed empty lgt.usda from %s", asset_dir.name,
            )

    def list_lights(self, asset_dir: Path) -> list[dict]:
        """List all lights in an asset folder's lgt.usda."""
        lgt_path = asset_dir / ASWFLayerNames.LGT
        if not lgt_path.exists():
            return []

        root_file = self._find_root_file(asset_dir)
        if root_file is None:
            return []

        stage = Usd.Stage.Open(str(root_file))
        if stage is None:
            return []

        results = []
        for prim in stage.Traverse():
            if prim.HasAPI(UsdLux.LightAPI):
                results.append({
                    "prim_path": str(prim.GetPath()),
                    "name": prim.GetName(),
                    "type": prim.GetTypeName(),
                })

        return results

    @staticmethod
    def _ensure_root_references_lgt(asset_dir: Path) -> None:
        """Ensure the root file references lgt.usda.

        Adds lgt.usda as a prepended reference on the root prim.
        """
        root_file = AssetAssembler._find_root_file(asset_dir)
        if root_file is None:
            return

        stage = Usd.Stage.Open(str(root_file))
        if stage is None:
            return

        root_prim = stage.GetDefaultPrim()
        if root_prim is None:
            return

        # Check if lgt.usda is already referenced
        refs_meta = root_prim.GetMetadata("references")
        if refs_meta:
            for ref_list in (
                refs_meta.prependedItems,
                refs_meta.appendedItems,
                refs_meta.explicitItems,
            ):
                if ref_list:
                    for ref in ref_list:
                        if ref.assetPath == f"./{ASWFLayerNames.LGT}":
                            return

        root_prim.GetReferences().AddReference(
            f"./{ASWFLayerNames.LGT}",
            position=Usd.ListPositionFrontOfPrependList,
        )
        stage.Save()

    def _meters_to_asset_units(
        self, asset_dir: Path, value: float,
    ) -> float:
        """Convert a value from meters to the asset's native units.

        BowerBot and the LLM work in meters. Asset files may use
        different units (e.g. centimeters with metersPerUnit=0.01).
        This method converts spatial values (translate, radius, etc.)
        from meters to the asset's coordinate space.
        """
        mpu, _ = self._read_stage_metadata_from_dir(asset_dir)
        if mpu <= 0 or abs(mpu - 1.0) < 1e-6:
            return value
        return value / mpu

    @staticmethod
    def _apply_inverse_transform(
        asset_dir: Path,
        lgt_path: Path,
        lgt_scope_path: Sdf.Path,
    ) -> None:
        """Apply the inverse of the geometry's root transform on the lgt Xform.

        This cancels the inherited transform from the root prim so
        lights authored under lgt/ are in clean world-aligned space.
        Same principle as the wrapper prim pattern for scene placement.
        """
        geo_path = asset_dir / ASWFLayerNames.GEO
        if not geo_path.exists():
            return

        geo_stage = Usd.Stage.Open(str(geo_path))
        if geo_stage is None:
            return

        root = geo_stage.GetDefaultPrim()
        if root is None:
            return

        xf = UsdGeom.Xformable(root)
        local_xform = xf.GetLocalTransformation()

        # Skip if identity — no compensation needed
        if local_xform == Gf.Matrix4d(1.0):
            return

        inverse = local_xform.GetInverse()

        # Open lgt.usda and set the inverse as a matrix op
        lgt_stage = Usd.Stage.Open(str(lgt_path))
        if lgt_stage is None:
            return

        scope_prim = lgt_stage.GetPrimAtPath(str(lgt_scope_path))
        if not scope_prim.IsValid():
            return

        scope_xf = UsdGeom.Xformable(scope_prim)
        # Only set once — check if already has ops
        if not scope_xf.GetOrderedXformOps():
            scope_xf.AddTransformOp().Set(inverse)

        lgt_stage.Save()

    @staticmethod
    def check_root_prim_type(geometry_file: Path) -> str | None:
        """Check if the geometry file's root prim follows ASWF guidelines.

        Returns None if the root prim is an Xform (correct).
        Returns the actual type name if it's not (e.g. "Mesh").
        """
        layer = Sdf.Layer.FindOrOpen(str(geometry_file))
        if layer is None or not layer.defaultPrim:
            return None

        root_spec = layer.GetPrimAtPath(
            Sdf.Path(f"/{layer.defaultPrim}"),
        )
        if root_spec is None:
            return None

        if root_spec.typeName in ("Xform", ""):
            return None

        return root_spec.typeName

    @staticmethod
    def wrap_root_prim(geometry_file: Path) -> None:
        """Wrap a non-Xform root prim under an Xform parent in place.

        Rewrites the file so the root prim becomes an Xform with the
        original geometry as a child. For example, if the file has
        ``/plate`` as a Mesh, it becomes ``/plate`` (Xform) with
        ``/plate/mesh`` (Mesh) as a child.

        This makes the asset ASWF-compliant.
        """
        source_layer = Sdf.Layer.FindOrOpen(str(geometry_file))
        if source_layer is None:
            return

        default_prim_name = source_layer.defaultPrim
        if not default_prim_name:
            return

        root_path = Sdf.Path(f"/{default_prim_name}")
        root_spec = source_layer.GetPrimAtPath(root_path)
        if root_spec is None or root_spec.typeName in ("Xform", ""):
            return

        # Create a temp layer with the wrapped structure
        import tempfile
        with tempfile.NamedTemporaryFile(
            suffix=".usda", delete=False,
        ) as tmp:
            tmp_path = tmp.name

        dest_layer = Sdf.Layer.CreateNew(tmp_path)

        # Create Xform wrapper
        Sdf.CreatePrimInLayer(dest_layer, root_path)
        wrapper = dest_layer.GetPrimAtPath(root_path)
        wrapper.specifier = Sdf.SpecifierDef
        wrapper.typeName = "Xform"

        # Copy original prim as child /asset_name/mesh
        child_path = Sdf.Path(f"/{default_prim_name}/mesh")
        Sdf.CopySpec(source_layer, root_path, dest_layer, child_path)

        dest_layer.defaultPrim = default_prim_name
        dest_layer.Save()

        # Replace the original file
        import shutil
        shutil.move(tmp_path, str(geometry_file))

    # ── Internal Helpers ─────────────────────────────────────────

    @staticmethod
    def _read_stage_metadata(file_path: Path) -> tuple[float, str]:
        """Read metersPerUnit and upAxis from a USD file."""
        stage = Usd.Stage.Open(str(file_path))
        if stage is None:
            return 1.0, "Y"

        mpu = UsdGeom.GetStageMetersPerUnit(stage)
        up = UsdGeom.GetStageUpAxis(stage)
        up_str = "Y" if up == UsdGeom.Tokens.y else "Z"
        return mpu, up_str

    @staticmethod
    def _read_stage_metadata_from_dir(
        asset_dir: Path,
    ) -> tuple[float, str]:
        """Read metadata from the geo.usda in an asset folder."""
        geo_path = asset_dir / ASWFLayerNames.GEO
        if geo_path.exists():
            return AssetAssembler._read_stage_metadata(geo_path)
        return 1.0, "Y"

    @staticmethod
    def _create_root_file(
        root_path: Path,
        meters_per_unit: float,
        up_axis: str,
        has_mtl: bool,
    ) -> None:
        """Write the root .usd that references geo.usda (and mtl.usda).

        Uses references (not sublayers) per ASWF guidelines.
        This keeps opinion strength predictable and prevents
        geometry transforms from bleeding into the scene level.
        """
        # Read the defaultPrim name from geo.usda
        geo_path = root_path.parent / ASWFLayerNames.GEO
        default_prim_name = root_path.parent.name  # fallback
        if geo_path.exists():
            geo_layer = Sdf.Layer.FindOrOpen(str(geo_path))
            if geo_layer and geo_layer.defaultPrim:
                default_prim_name = geo_layer.defaultPrim

        stage = Usd.Stage.CreateNew(str(root_path))

        UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
        UsdGeom.SetStageUpAxis(
            stage,
            UsdGeom.Tokens.y if up_axis == "Y" else UsdGeom.Tokens.z,
        )

        # Define the root prim and reference geo.usda + mtl.usda
        root_prim = stage.DefinePrim(
            f"/{default_prim_name}", "Xform",
        )
        stage.SetDefaultPrim(root_prim)

        refs = root_prim.GetReferences()
        if has_mtl:
            refs.AddReference(f"./{ASWFLayerNames.MTL}")
        refs.AddReference(f"./{ASWFLayerNames.GEO}")

        stage.Save()

    @staticmethod
    def _create_geo_layer(
        geo_dest: Path,
        geometry_source: Path,
    ) -> None:
        """Copy geometry into geo.usda using Sdf layer copy."""
        source_layer = Sdf.Layer.FindOrOpen(str(geometry_source))
        if source_layer is None:
            msg = f"Cannot open geometry source: {geometry_source}"
            raise RuntimeError(msg)

        dest_layer = Sdf.Layer.CreateNew(str(geo_dest))

        for prim_spec in source_layer.rootPrims:
            Sdf.CopySpec(
                source_layer, prim_spec.path,
                dest_layer, prim_spec.path,
            )

        dest_layer.defaultPrim = source_layer.defaultPrim
        dest_layer.Save()

    @staticmethod
    def _ensure_root_references_mtl(asset_dir: Path) -> None:
        """Ensure the root file's defaultPrim references mtl.usda.

        Adds mtl.usda as a prepended reference on the root prim
        so material opinions are stronger than geometry opinions.
        """
        root_file = AssetAssembler._find_root_file(asset_dir)
        if root_file is None:
            return

        stage = Usd.Stage.Open(str(root_file))
        if stage is None:
            return

        root_prim = stage.GetDefaultPrim()
        if root_prim is None:
            return

        # Check if mtl.usda is already referenced
        refs_meta = root_prim.GetMetadata("references")
        if refs_meta:
            for ref_list in (
                refs_meta.prependedItems,
                refs_meta.appendedItems,
                refs_meta.explicitItems,
            ):
                if ref_list:
                    for ref in ref_list:
                        if ref.assetPath == f"./{ASWFLayerNames.MTL}":
                            return  # already referenced

        # Add mtl.usda as prepended reference (stronger than geo.usda)
        root_prim.GetReferences().AddReference(
            f"./{ASWFLayerNames.MTL}", position=Usd.ListPositionFrontOfPrependList,
        )
        stage.Save()

    @staticmethod
    def _get_default_prim_name(asset_dir: Path) -> str | None:
        """Get the defaultPrim name from the asset folder's geo.usda."""
        geo_path = asset_dir / ASWFLayerNames.GEO
        if geo_path.exists():
            layer = Sdf.Layer.FindOrOpen(str(geo_path))
            if layer and layer.defaultPrim:
                return layer.defaultPrim
        return None

    @staticmethod
    def _find_root_file(asset_dir: Path) -> Path | None:
        """Find the ASWF root file in an asset folder."""
        for ext in (".usd", ".usda", ".usdc"):
            candidate = asset_dir / f"{asset_dir.name}{ext}"
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _find_first_material(file_path: Path) -> str | None:
        """Return the prim path of the first Material in a USD file."""
        stage = Usd.Stage.Open(str(file_path))
        if stage is None:
            return None
        for prim in stage.Traverse():
            if prim.IsA(UsdShade.Material):
                return str(prim.GetPath())
        return None

    @staticmethod
    def _cleanup_unused_materials(
        mtl_path: Path, asset_dir: Path,
    ) -> None:
        """Remove material definitions from mtl.usda that have no bindings.

        If mtl.usda becomes empty after cleanup, deletes the file
        and removes it from the root file's references.
        """
        default_prim_name = AssetAssembler._get_default_prim_name(
            asset_dir,
        )
        if not default_prim_name:
            default_prim_name = asset_dir.name

        stage = Usd.Stage.Open(str(mtl_path))
        if stage is None:
            return

        # Collect bound material paths
        bound_materials: set[str] = set()
        for prim in stage.Traverse():
            binding_api = UsdShade.MaterialBindingAPI(prim)
            bound_mat, _ = binding_api.ComputeBoundMaterial()
            if bound_mat:
                bound_materials.add(str(bound_mat.GetPath()))

        # Find unused materials under /{root}/mtl and remove them
        mtl_layer = stage.GetRootLayer()
        mtl_scope_path = Sdf.Path(f"/{default_prim_name}/mtl")
        mtl_scope = mtl_layer.GetPrimAtPath(mtl_scope_path)
        if mtl_scope:
            to_remove = []
            for child in mtl_scope.nameChildren:
                if str(child.path) not in bound_materials:
                    to_remove.append(child.path)

            for path in to_remove:
                edit = Sdf.BatchNamespaceEdit()
                edit.Add(path, Sdf.Path.emptyPath)
                mtl_layer.Apply(edit)

        mtl_layer.Save()

        # If no materials remain, remove mtl.usda entirely
        stage = Usd.Stage.Open(str(mtl_path))
        has_materials = False
        if stage:
            for prim in stage.Traverse():
                if prim.IsA(UsdShade.Material):
                    has_materials = True
                    break

        if not has_materials:
            asset_dir = mtl_path.parent
            mtl_path.unlink()

            # Remove mtl.usda reference from root file
            root_file = AssetAssembler._find_root_file(asset_dir)
            if root_file:
                stage = Usd.Stage.Open(str(root_file))
                if stage:
                    root_prim = stage.GetDefaultPrim()
                    if root_prim:
                        # Clear and re-add only geo.usda
                        root_prim.GetReferences().ClearReferences()
                        root_prim.GetReferences().AddReference(
                            f"./{ASWFLayerNames.GEO}",
                        )
                    stage.Save()

            logger.info("Removed empty mtl.usda from %s", asset_dir.name)
