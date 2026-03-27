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

from pxr import Sdf, Usd, UsdGeom, UsdShade

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
        geo_path = asset_dir / "geo.usda"
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
        mtl_path = asset_dir / "mtl.usda"

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
        mtl_path = asset_dir / "mtl.usda"
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
        mtl_path = asset_dir / "mtl.usda"
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
        geo_path = asset_dir / "geo.usda"
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
        geo_path = root_path.parent / "geo.usda"
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
            refs.AddReference("./mtl.usda")
        refs.AddReference("./geo.usda")

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
                        if ref.assetPath == "./mtl.usda":
                            return  # already referenced

        # Add mtl.usda as prepended reference (stronger than geo.usda)
        root_prim.GetReferences().AddReference(
            "./mtl.usda", position=Usd.ListPositionFrontOfPrependList,
        )
        stage.Save()

    @staticmethod
    def _get_default_prim_name(asset_dir: Path) -> str | None:
        """Get the defaultPrim name from the asset folder's geo.usda."""
        geo_path = asset_dir / "geo.usda"
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
                            "./geo.usda",
                        )
                    stage.Save()

            logger.info("Removed empty mtl.usda from %s", asset_dir.name)
