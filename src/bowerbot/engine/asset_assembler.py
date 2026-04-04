# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""AssetAssembler — creates and manages ASWF-compliant USD asset folders.

Builds asset folders incrementally as the user works:
1. place_asset creates the folder with root + geo.usda
2. bind_material adds materials into mtl.usda
3. add_light adds lights into lgt.usda

Follows the ASWF USD Working Group asset structure guidelines:

    asset_name/
      asset_name.usd   <- root (references geo.usda, mtl.usda, lgt.usda)
      geo.usda          <- geometry layer
      mtl.usda          <- materials defined inline + bindings
      lgt.usda          <- asset-level lights
      maps/            <- texture files

Reference: https://github.com/usd-wg/assets/blob/main/docs/asset-structure-guidelines.md
"""

from __future__ import annotations

import logging
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade

from bowerbot.schemas import ASWFLayerNames
from bowerbot.utils.usd_utils import LIGHT_CLASSES, iter_prim_ref_paths

logger = logging.getLogger(__name__)


class AssetAssembler:
    """Creates and manages ASWF-compliant USD asset folders.

    All pxr API usage for asset folder operations lives here.
    Skills call this through the engine layer — they never touch pxr.
    """

    # ── Asset Folder Operations ──────────────────────────────────

    def create_asset_folder(
        self,
        output_dir: Path,
        asset_name: str,
        geometry_file: Path,
    ) -> Path:
        """Create an ASWF asset folder with root + geo.usda.

        Returns:
            Path to the root file (``output_dir/asset_name/asset_name.usd``).
        """
        asset_dir = output_dir / asset_name
        asset_dir.mkdir(parents=True, exist_ok=True)

        mpu, up = self._read_stage_metadata(geometry_file)

        geo_path = asset_dir / ASWFLayerNames.GEO
        if not geo_path.exists():
            self._create_geo_layer(geo_path, geometry_file)

        root_path = asset_dir / f"{asset_name}.usda"
        if not root_path.exists():
            self._create_root_file(root_path, mpu, up, has_mtl=False)

        logger.info("Created ASWF asset folder: %s", asset_dir)
        return root_path

    # ── Material Operations ──────────────────────────────────────

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
        updates the root file to reference it.

        Returns:
            The material prim path that was bound.
        """
        mtl_path = asset_dir / ASWFLayerNames.MTL

        if not material_prim_path:
            material_prim_path = self._find_first_material(material_file)
            if not material_prim_path:
                msg = f"No Material prim found in {material_file.name}"
                raise ValueError(msg)

        if mtl_path.exists():
            mtl_layer = Sdf.Layer.FindOrOpen(str(mtl_path))
        else:
            mtl_layer = Sdf.Layer.CreateNew(str(mtl_path))

        source_layer = Sdf.Layer.FindOrOpen(str(material_file))
        if source_layer is None:
            msg = f"Cannot open material file: {material_file}"
            raise RuntimeError(msg)

        default_prim_name = self._resolve_default_prim_name(
            asset_dir,
        )

        # Ensure /{root}/mtl scope exists in mtl.usda
        self._ensure_layer_scope(
            mtl_layer, default_prim_name, "mtl", "Scope",
        )

        # Copy material definition into the asset's namespace
        mat_name = Sdf.Path(material_prim_path).name
        dest_mat_path = Sdf.Path(
            f"/{default_prim_name}/mtl/{mat_name}",
        )
        Sdf.CopySpec(
            source_layer, Sdf.Path(material_prim_path),
            mtl_layer, dest_mat_path,
        )

        mtl_layer.defaultPrim = default_prim_name
        mtl_layer.Save()

        # Author binding opinion
        local_prim_path = self._to_layer_local_path(
            prim_path, default_prim_name,
        )
        composed_mat_path = (
            f"/{default_prim_name}/mtl/{mat_name}"
        )

        stage = Usd.Stage.Open(str(mtl_path))
        if stage is not None:
            prim = stage.OverridePrim(local_prim_path)
            mat_prim = stage.GetPrimAtPath(composed_mat_path)
            if mat_prim.IsValid():
                material = UsdShade.Material(mat_prim)
                binding_api = UsdShade.MaterialBindingAPI.Apply(
                    prim,
                )
                binding_api.Bind(material)
            stage.Save()

        self._ensure_root_reference(asset_dir, ASWFLayerNames.MTL)

        logger.info(
            "Added material %s -> %s in %s",
            composed_mat_path, prim_path, asset_dir.name,
        )
        return composed_mat_path

    def remove_material_binding(
        self,
        asset_dir: Path,
        prim_path: str,
    ) -> None:
        """Remove a material binding from an asset folder's mtl.usda.

        Clears the binding opinion. If no bindings remain in mtl.usda,
        removes it and updates the root file.
        """
        mtl_path = asset_dir / ASWFLayerNames.MTL
        if not mtl_path.exists():
            return

        default_prim_name = self._resolve_default_prim_name(
            asset_dir,
        )
        local_path = self._to_layer_local_path(
            prim_path, default_prim_name,
        )

        stage = Usd.Stage.Open(str(mtl_path))
        if stage is None:
            return

        prim = stage.GetPrimAtPath(local_path)
        if prim.IsValid():
            binding_api = UsdShade.MaterialBindingAPI(prim)
            binding_api.UnbindAllBindings()

        stage.Save()

        self._cleanup_unused_materials(mtl_path, asset_dir)

    def list_materials(self, asset_dir: Path) -> list[dict]:
        """List all materials and bindings in an asset folder."""
        mtl_path = asset_dir / ASWFLayerNames.MTL
        if not mtl_path.exists():
            return []

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
                    materials[mat_path].append(
                        str(prim.GetPath()),
                    )

        return [
            {
                "material_path": mat_path,
                "material_name": Sdf.Path(mat_path).name,
                "bound_prims": bound_prims,
            }
            for mat_path, bound_prims in materials.items()
        ]

    # ── Geometry Operations ──────────────────────────────────────

    def get_geometry_bounds(
        self, asset_dir: Path,
    ) -> dict[str, dict[str, float]] | None:
        """Return the asset's geometry bounds in meters.

        Returns a dict with 'min', 'max', 'center', and 'size'
        keys, each containing x, y, z values in meters.
        Returns None if bounds cannot be computed.
        """
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

    # ── Light Operations ─────────────────────────────────────────

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
        file to reference it.

        Returns:
            The light prim path in the composed stage.
        """
        lgt_path = asset_dir / ASWFLayerNames.LGT
        default_prim_name = self._resolve_default_prim_name(
            asset_dir,
        )

        # Create or open lgt.usda with proper scope
        if lgt_path.exists():
            lgt_layer = Sdf.Layer.FindOrOpen(str(lgt_path))
        else:
            lgt_layer = Sdf.Layer.CreateNew(str(lgt_path))
            lgt_layer.defaultPrim = default_prim_name

        lgt_scope_path = Sdf.Path(
            f"/{default_prim_name}/lgt",
        )
        self._ensure_layer_scope(
            lgt_layer, default_prim_name, "lgt", "Xform",
        )
        lgt_layer.Save()

        # Cancel inherited geometry transform
        self._apply_inverse_transform(
            asset_dir, lgt_path, lgt_scope_path,
        )

        # Create the light prim
        stage = Usd.Stage.Open(str(lgt_path))
        if stage is None:
            msg = f"Cannot open lgt layer: {lgt_path}"
            raise RuntimeError(msg)

        light_prim_path = (
            f"/{default_prim_name}/lgt/{light_name}"
        )

        light_cls = LIGHT_CLASSES.get(light_type)
        if light_cls is None:
            msg = f"Unknown light type: {light_type}"
            raise ValueError(msg)

        light_prim = light_cls.Define(stage, light_prim_path)
        light_prim.CreateIntensityAttr(intensity)
        light_prim.CreateColorAttr(Gf.Vec3f(*color))

        self._set_light_extra_attrs(light_prim, extra_attrs)

        # Apply transform in asset units
        unit_factor = self._unit_factor(asset_dir)
        xformable = UsdGeom.Xformable(light_prim)
        xformable.AddTranslateOp().Set(
            Gf.Vec3d(
                translate[0] * unit_factor,
                translate[1] * unit_factor,
                translate[2] * unit_factor,
            ),
        )

        if any(v != 0.0 for v in rotate):
            xformable.AddRotateXYZOp().Set(
                Gf.Vec3f(*rotate),
            )

        stage.Save()

        self._ensure_root_reference(asset_dir, ASWFLayerNames.LGT)

        logger.info(
            "Added light %s (%s) to %s",
            light_name, light_type, asset_dir.name,
        )
        return f"/{default_prim_name}/lgt/{light_name}"

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
        """
        lgt_path = asset_dir / ASWFLayerNames.LGT
        if not lgt_path.exists():
            msg = f"No {ASWFLayerNames.LGT} found in asset folder"
            raise ValueError(msg)

        default_prim_name = self._resolve_default_prim_name(
            asset_dir,
        )
        light_prim_path = (
            f"/{default_prim_name}/lgt/{light_name}"
        )

        stage = Usd.Stage.Open(str(lgt_path))
        if stage is None:
            msg = f"Cannot open lgt layer: {lgt_path}"
            raise RuntimeError(msg)

        prim = stage.GetPrimAtPath(light_prim_path)
        if not prim.IsValid():
            msg = f"Light not found: {light_name}"
            raise ValueError(msg)

        if intensity is not None:
            prim.GetAttribute("inputs:intensity").Set(intensity)

        if color is not None:
            prim.GetAttribute("inputs:color").Set(
                Gf.Vec3f(*color),
            )

        # Update type-specific attributes
        self._update_light_extra_attrs(
            prim, asset_dir, extra_attrs,
        )

        # Update transform
        if translate is not None:
            self._set_translate(
                prim, translate, self._unit_factor(asset_dir),
            )

        if rotate is not None:
            self._set_rotate(prim, rotate)

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

        default_prim_name = self._resolve_default_prim_name(
            asset_dir,
        )
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

        self._remove_empty_layer(
            lgt_path, asset_dir,
            lambda p: p.HasAPI(UsdLux.LightAPI),
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

        return [
            {
                "prim_path": str(prim.GetPath()),
                "name": prim.GetName(),
                "type": prim.GetTypeName(),
            }
            for prim in stage.Traverse()
            if prim.HasAPI(UsdLux.LightAPI)
        ]

    # ── Asset Preparation ───────────────────────────────────────

    @staticmethod
    def is_asset_folder_root(asset_path: Path) -> bool:
        """Return True if *asset_path* is the root file of an ASWF folder.

        An ASWF root file has the same stem as its parent directory
        (e.g. ``single_table/single_table.usd``).
        """
        return (
            asset_path.stem == asset_path.parent.name
            and asset_path.suffix.lower() in {".usd", ".usda", ".usdc"}
        )

    @staticmethod
    def copy_asset_folder(root_file: Path, dest_dir: Path) -> str:
        """Copy an entire ASWF asset folder into *dest_dir*.

        Skips the copy if the destination already exists.

        Returns:
            Relative path from the stage file to the copied root
            (e.g. ``"assets/chair/chair.usd"``).
        """
        import shutil

        source_dir = root_file.parent
        folder_name = source_dir.name
        target = dest_dir / folder_name

        if not target.exists():
            shutil.copytree(source_dir, target)

        return f"assets/{folder_name}/{root_file.name}"

    def prepare_asset(
        self,
        asset_path: Path,
        assets_dir: Path,
        fix_root_prim: bool = False,
    ) -> str:
        """Prepare an asset for scene placement.

        Handles three asset formats:

        * **ASWF folder root** — copies the entire folder.
        * **USDZ** — copies the single file.
        * **Loose geometry** — wraps in an ASWF folder
          (optionally fixing a non-Xform root prim).

        Args:
            asset_path: Path to the source asset file.
            assets_dir: Project assets directory to copy into.
            fix_root_prim: When ``True``, automatically wrap a
                non-Xform root prim under an Xform.

        Returns:
            Relative path string for the scene reference
            (e.g. ``"assets/chair/chair.usd"``).

        Raises:
            ValueError: If the root prim is non-Xform and
                *fix_root_prim* is ``False``.
        """
        import shutil

        if self.is_asset_folder_root(asset_path):
            return self.copy_asset_folder(asset_path, assets_dir)

        if asset_path.suffix.lower() == ".usdz":
            local_copy = assets_dir / asset_path.name
            if not local_copy.exists():
                shutil.copy2(asset_path, local_copy)
            return f"assets/{asset_path.name}"

        # Loose geometry — check ASWF root prim compliance
        bad_type = self.check_root_prim_type(asset_path)

        if bad_type and not fix_root_prim:
            msg = (
                f"Asset '{asset_path.name}' has a "
                f"{bad_type} as its root prim instead "
                f"of an Xform. Per ASWF USD guidelines, "
                f"the root prim should be an Xform with "
                f"geometry as children. Ask the user if "
                f"they want to fix this automatically, "
                f"then call place_asset again with "
                f"fix_root_prim set to true."
            )
            raise ValueError(msg)

        if bad_type:
            self.wrap_root_prim(asset_path)
            logger.info(
                "Wrapped %s root prim in Xform for ASWF compliance",
                asset_path.name,
            )

        folder_name = asset_path.stem
        root_file = self.create_asset_folder(
            output_dir=assets_dir,
            asset_name=folder_name,
            geometry_file=asset_path,
        )
        return f"assets/{folder_name}/{root_file.name}"

    # ── ASWF Compliance ──────────────────────────────────────────

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
        original geometry as a child. This makes the asset ASWF-compliant.
        """
        import shutil
        import tempfile

        source_layer = Sdf.Layer.FindOrOpen(str(geometry_file))
        if source_layer is None:
            return

        default_prim_name = source_layer.defaultPrim
        if not default_prim_name:
            return

        root_path = Sdf.Path(f"/{default_prim_name}")
        root_spec = source_layer.GetPrimAtPath(root_path)
        if root_spec is None or root_spec.typeName in (
            "Xform", "",
        ):
            return

        with tempfile.NamedTemporaryFile(
            suffix=".usda", delete=False,
        ) as tmp:
            tmp_path = tmp.name

        dest_layer = Sdf.Layer.CreateNew(tmp_path)

        Sdf.CreatePrimInLayer(dest_layer, root_path)
        wrapper = dest_layer.GetPrimAtPath(root_path)
        wrapper.specifier = Sdf.SpecifierDef
        wrapper.typeName = "Xform"

        child_path = Sdf.Path(f"/{default_prim_name}/mesh")
        Sdf.CopySpec(
            source_layer, root_path, dest_layer, child_path,
        )

        dest_layer.defaultPrim = default_prim_name
        dest_layer.Save()

        shutil.move(tmp_path, str(geometry_file))

    # ── Internal Helpers ─────────────────────────────────────────

    def _resolve_default_prim_name(
        self, asset_dir: Path,
    ) -> str:
        """Get the defaultPrim name, falling back to folder name."""
        name = self._get_default_prim_name(asset_dir)
        return name if name else asset_dir.name

    @staticmethod
    def _to_layer_local_path(
        prim_path: str, default_prim_name: str,
    ) -> str:
        """Convert a composed prim path to a layer-local path.

        Strips the root prim prefix and re-adds it, handling
        the case where the path IS the root prim.
        """
        prefix = f"/{default_prim_name}"
        relative = prim_path
        if prim_path.startswith(prefix):
            relative = prim_path[len(prefix):]
            if not relative:
                relative = "/"
        return f"/{default_prim_name}{relative}"

    def _unit_factor(self, asset_dir: Path) -> float:
        """Return the factor to convert meters to asset units."""
        mpu, _ = self._read_stage_metadata_from_dir(asset_dir)
        return 1.0 / mpu if mpu > 0 else 1.0

    def _meters_to_asset_units(
        self, asset_dir: Path, value: float,
    ) -> float:
        """Convert a value from meters to the asset's native units."""
        mpu, _ = self._read_stage_metadata_from_dir(asset_dir)
        if mpu <= 0 or abs(mpu - 1.0) < 1e-6:
            return value
        return value / mpu

    @staticmethod
    def _set_translate(
        prim: Usd.Prim,
        translate: tuple[float, float, float],
        unit_factor: float,
    ) -> None:
        """Set or update a translate xform op on a prim."""
        converted = Gf.Vec3d(
            translate[0] * unit_factor,
            translate[1] * unit_factor,
            translate[2] * unit_factor,
        )
        xformable = UsdGeom.Xformable(prim)
        for op in xformable.GetOrderedXformOps():
            if op.GetOpName() == "xformOp:translate":
                op.Set(converted)
                return
        xformable.AddTranslateOp().Set(converted)

    @staticmethod
    def _set_rotate(
        prim: Usd.Prim,
        rotate: tuple[float, float, float],
    ) -> None:
        """Set or update a rotateXYZ xform op on a prim."""
        xformable = UsdGeom.Xformable(prim)
        for op in xformable.GetOrderedXformOps():
            if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                op.Set(Gf.Vec3f(*rotate))
                return
        if any(v != 0.0 for v in rotate):
            xformable.AddRotateXYZOp().Set(
                Gf.Vec3f(*rotate),
            )

    @staticmethod
    def _set_light_extra_attrs(
        light_prim: Usd.Prim,
        extra_attrs: dict[str, float | str | None],
    ) -> None:
        """Set type-specific attributes on a newly created light."""
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
            if value is not None and hasattr(
                light_prim, create_method,
            ):
                getattr(light_prim, create_method)().Set(value)

    def _update_light_extra_attrs(
        self,
        prim: Usd.Prim,
        asset_dir: Path,
        extra_attrs: dict[str, float | str | None],
    ) -> None:
        """Update type-specific attributes on an existing light."""
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

    @staticmethod
    def _ensure_layer_scope(
        layer: Sdf.Layer,
        default_prim_name: str,
        scope_name: str,
        scope_type: str,
    ) -> None:
        """Ensure /{root}/{scope} exists in a layer.

        Creates the root prim as an over and the scope prim
        as a def with the given type.
        """
        root_prim_path = Sdf.Path(f"/{default_prim_name}")
        scope_path = Sdf.Path(
            f"/{default_prim_name}/{scope_name}",
        )

        if not layer.GetPrimAtPath(root_prim_path):
            Sdf.CreatePrimInLayer(layer, root_prim_path)
            layer.GetPrimAtPath(
                root_prim_path,
            ).specifier = Sdf.SpecifierOver

        if not layer.GetPrimAtPath(scope_path):
            Sdf.CreatePrimInLayer(layer, scope_path)
            scope = layer.GetPrimAtPath(scope_path)
            scope.specifier = Sdf.SpecifierDef
            scope.typeName = scope_type

    @staticmethod
    def _has_reference(
        root_prim: Usd.Prim, asset_path: str,
    ) -> bool:
        """Check if a root prim already references a given asset."""
        return asset_path in iter_prim_ref_paths(root_prim)

    def _ensure_root_reference(
        self, asset_dir: Path, layer_file: str,
    ) -> None:
        """Ensure the root file references a given layer file.

        Adds the layer as a prepended reference on the root prim
        if not already present.
        """
        root_file = self._find_root_file(asset_dir)
        if root_file is None:
            return

        stage = Usd.Stage.Open(str(root_file))
        if stage is None:
            return

        root_prim = stage.GetDefaultPrim()
        if root_prim is None:
            return

        ref_path = f"./{layer_file}"
        if self._has_reference(root_prim, ref_path):
            return

        root_prim.GetReferences().AddReference(
            ref_path,
            position=Usd.ListPositionFrontOfPrependList,
        )
        stage.Save()

    def _remove_empty_layer(
        self,
        layer_path: Path,
        asset_dir: Path,
        has_content: callable,
    ) -> None:
        """Remove a layer file if it has no relevant content.

        Args:
            layer_path: Path to the layer file.
            asset_dir: Path to the asset folder.
            has_content: Callable that takes a Usd.Prim and returns
                True if the prim is relevant content (e.g. a light
                or material).
        """
        stage = Usd.Stage.Open(str(layer_path))
        if stage:
            for prim in stage.Traverse():
                if has_content(prim):
                    return

        layer_path.unlink()
        self._rebuild_root_references(asset_dir)

        logger.info(
            "Removed empty %s from %s",
            layer_path.name, asset_dir.name,
        )

    def _rebuild_root_references(
        self, asset_dir: Path,
    ) -> None:
        """Rebuild root file references from existing layers."""
        root_file = self._find_root_file(asset_dir)
        if root_file is None:
            return

        stage = Usd.Stage.Open(str(root_file))
        if stage is None:
            return

        root_prim = stage.GetDefaultPrim()
        if root_prim is None:
            return

        root_prim.GetReferences().ClearReferences()

        # Add references in opinion strength order
        for layer_file in (
            ASWFLayerNames.LGT,
            ASWFLayerNames.MTL,
            ASWFLayerNames.GEO,
        ):
            if (asset_dir / layer_file).exists():
                root_prim.GetReferences().AddReference(
                    f"./{layer_file}",
                )

        stage.Save()

    @staticmethod
    def _apply_inverse_transform(
        asset_dir: Path,
        lgt_path: Path,
        lgt_scope_path: Sdf.Path,
    ) -> None:
        """Apply the inverse of the geometry's root transform on the lgt Xform.

        Cancels the inherited transform from the root prim so
        lights authored under lgt/ are in clean world-aligned space.
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

        if local_xform == Gf.Matrix4d(1.0):
            return

        inverse = local_xform.GetInverse()

        lgt_stage = Usd.Stage.Open(str(lgt_path))
        if lgt_stage is None:
            return

        scope_prim = lgt_stage.GetPrimAtPath(
            str(lgt_scope_path),
        )
        if not scope_prim.IsValid():
            return

        scope_xf = UsdGeom.Xformable(scope_prim)
        if not scope_xf.GetOrderedXformOps():
            scope_xf.AddTransformOp().Set(inverse)

        lgt_stage.Save()

    @staticmethod
    def _read_stage_metadata(
        file_path: Path,
    ) -> tuple[float, str]:
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
        """Write the root .usd that references geo.usda (and mtl.usda)."""
        geo_path = root_path.parent / ASWFLayerNames.GEO
        default_prim_name = root_path.parent.name
        if geo_path.exists():
            geo_layer = Sdf.Layer.FindOrOpen(str(geo_path))
            if geo_layer and geo_layer.defaultPrim:
                default_prim_name = geo_layer.defaultPrim

        stage = Usd.Stage.CreateNew(str(root_path))

        UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
        UsdGeom.SetStageUpAxis(
            stage,
            UsdGeom.Tokens.y
            if up_axis == "Y"
            else UsdGeom.Tokens.z,
        )

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
        source_layer = Sdf.Layer.FindOrOpen(
            str(geometry_source),
        )
        if source_layer is None:
            msg = (
                f"Cannot open geometry source: "
                f"{geometry_source}"
            )
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
    def _get_default_prim_name(
        asset_dir: Path,
    ) -> str | None:
        """Get the defaultPrim name from geo.usda."""
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
    def _find_first_material(
        file_path: Path,
    ) -> str | None:
        """Return the prim path of the first Material in a USD file."""
        stage = Usd.Stage.Open(str(file_path))
        if stage is None:
            return None
        for prim in stage.Traverse():
            if prim.IsA(UsdShade.Material):
                return str(prim.GetPath())
        return None

    def _cleanup_unused_materials(
        self, mtl_path: Path, asset_dir: Path,
    ) -> None:
        """Remove unused material definitions from mtl.usda.

        If mtl.usda becomes empty after cleanup, deletes the
        file and rebuilds root references.
        """
        default_prim_name = self._resolve_default_prim_name(
            asset_dir,
        )

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

        # Remove unbound materials
        mtl_layer = stage.GetRootLayer()
        mtl_scope_path = Sdf.Path(
            f"/{default_prim_name}/mtl",
        )
        mtl_scope = mtl_layer.GetPrimAtPath(mtl_scope_path)
        if mtl_scope:
            to_remove = [
                child.path
                for child in mtl_scope.nameChildren
                if str(child.path) not in bound_materials
            ]
            for path in to_remove:
                edit = Sdf.BatchNamespaceEdit()
                edit.Add(path, Sdf.Path.emptyPath)
                mtl_layer.Apply(edit)

        mtl_layer.Save()

        # If no materials remain, remove mtl.usda
        self._remove_empty_layer(
            mtl_path, asset_dir,
            lambda p: p.IsA(UsdShade.Material),
        )
