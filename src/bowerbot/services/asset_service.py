# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset service — prepare and assemble ASWF-compliant asset folders.

Handles:

* **prepare_asset** — copy or wrap any input asset (ASWF folder root,
  USDZ, or loose geometry) into the project's assets directory.
* **ASWF compliance repair** — validate and fix root-prim issues
  before creating a folder.
* **Folder creation** — build ``asset_name/`` with ``asset_name.usda``
  + ``geo.usda`` following the USD WG guidelines.

Reference: https://github.com/usd-wg/assets/blob/main/docs/asset-structure-guidelines.md
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom

from bowerbot.schemas import ASWFLayerNames, DetectionOutcome, IntakeReport
from bowerbot.services import intake_service
from bowerbot.utils.usd_utils import get_prim_ref_paths

logger = logging.getLogger(__name__)


def prepare_asset(
    asset_path: Path,
    assets_dir: Path,
    *,
    fix_root_prim: bool = False,
) -> IntakeReport:
    """Bring an asset into the project and return an :class:`IntakeReport`.

    Routes USDZ as-is, delegates folders with a detectable root to
    :func:`intake_service.intake_folder`, and wraps loose files in a
    fresh ASWF folder named after the file stem.
    """
    if asset_path.suffix.lower() == ".usdz":
        return _intake_usdz(asset_path, assets_dir)

    parent = asset_path.parent.resolve()
    if parent != assets_dir.resolve() and parent.is_dir():
        detection = intake_service.detect_folder_root(parent)
        if detection.outcome is DetectionOutcome.UNAMBIGUOUS:
            return intake_service.intake_folder(parent, assets_dir)

    ensure_aswf_compliance(asset_path, fix_root_prim=fix_root_prim)

    folder_name = asset_path.stem
    root_file = create_asset_folder(
        output_dir=assets_dir,
        asset_name=folder_name,
        geometry_file=asset_path,
    )
    return IntakeReport(
        scene_ref_path=f"assets/{folder_name}/{root_file.name}",
        asset_folder_name=folder_name,
        root_original_name=asset_path.name,
        root_canonical_name=root_file.name,
        was_renamed=asset_path.name != root_file.name,
        files_copied=1,
    )


def _intake_usdz(asset_path: Path, assets_dir: Path) -> IntakeReport:
    """Copy a USDZ into *assets_dir* as-is."""
    local_copy = assets_dir / asset_path.name
    copied = 0
    if not local_copy.exists():
        shutil.copy2(asset_path, local_copy)
        copied = 1
    return IntakeReport(
        scene_ref_path=f"assets/{asset_path.name}",
        asset_folder_name=asset_path.stem,
        root_original_name=asset_path.name,
        root_canonical_name=asset_path.name,
        was_renamed=False,
        files_copied=copied,
    )


def is_asset_folder_root(asset_path: Path) -> bool:
    """Return True if *asset_path* is the root file of an ASWF folder.

    An ASWF root file has the same stem as its parent directory
    (e.g. ``single_table/single_table.usd``).
    """
    return (
        asset_path.stem == asset_path.parent.name
        and asset_path.suffix.lower() in {".usd", ".usda", ".usdc"}
    )


def copy_asset_folder(root_file: Path, dest_dir: Path) -> str:
    """Copy an entire ASWF asset folder into *dest_dir*.

    Skips the copy if the destination already exists.
    """
    source_dir = root_file.parent
    folder_name = source_dir.name
    target = dest_dir / folder_name

    if not target.exists():
        shutil.copytree(source_dir, target)

    return f"assets/{folder_name}/{root_file.name}"


def create_asset_folder(
    output_dir: Path,
    asset_name: str,
    geometry_file: Path,
) -> Path:
    """Create an ASWF asset folder with root + ``geo.usda``.

    Returns the path to the root file
    (``output_dir/asset_name/asset_name.usda``).
    """
    asset_dir = output_dir / asset_name
    asset_dir.mkdir(parents=True, exist_ok=True)

    mpu, up = read_stage_metadata(geometry_file)

    geo_path = asset_dir / ASWFLayerNames.GEO
    if not geo_path.exists():
        _create_geo_layer(geo_path, geometry_file)

    root_path = asset_dir / f"{asset_name}.usda"
    if not root_path.exists():
        _create_root_file(root_path, mpu, up, has_mtl=False)

    logger.info("Created ASWF asset folder: %s", asset_dir)
    return root_path


def ensure_aswf_compliance(
    geometry_file: Path,
    *,
    fix_root_prim: bool = False,
) -> None:
    """Validate and repair a geometry file for ASWF compliance.

    Checks and fixes issues in order:

    1. **No root prims** — raises ``ValueError``.
    2. **Empty ``defaultPrim``, single root prim** — auto-sets it.
    3. **Empty ``defaultPrim``, multiple root prims** — raises.
    4. **``defaultPrim`` points to a nonexistent prim** — raises.
    5. **Root prim is not an Xform** — wraps when *fix_root_prim*,
       otherwise raises.
    """
    layer = Sdf.Layer.FindOrOpen(str(geometry_file))
    if layer is None:
        msg = f"Cannot open geometry file: {geometry_file.name}"
        raise ValueError(msg)

    root_prims = list(layer.rootPrims)

    if not root_prims:
        msg = (
            f"Asset '{geometry_file.name}' contains no geometry. "
            f"Export it from your DCC with geometry under a root prim."
        )
        raise ValueError(msg)

    if not layer.defaultPrim:
        if len(root_prims) == 1:
            layer.defaultPrim = root_prims[0].name
            layer.Save()
            logger.info(
                "Auto-set defaultPrim to '%s' in %s",
                root_prims[0].name, geometry_file.name,
            )
        else:
            prim_names = ", ".join(p.name for p in root_prims)
            msg = (
                f"Asset '{geometry_file.name}' has multiple root prims "
                f"({prim_names}) and no defaultPrim. Export it from your "
                f"DCC with a single root Xform."
            )
            raise ValueError(msg)

    root_spec = layer.GetPrimAtPath(Sdf.Path(f"/{layer.defaultPrim}"))
    if root_spec is None:
        msg = (
            f"Asset '{geometry_file.name}' has defaultPrim "
            f"'{layer.defaultPrim}' but that prim does not exist."
        )
        raise ValueError(msg)

    if root_spec.typeName not in ("Xform", ""):
        if not fix_root_prim:
            msg = (
                f"Asset '{geometry_file.name}' has a {root_spec.typeName} "
                f"as its root prim instead of an Xform. Per ASWF USD "
                f"guidelines, the root prim should be an Xform with "
                f"geometry as children. Ask the user if they want to "
                f"fix this automatically, then call place_asset again "
                f"with fix_root_prim set to true."
            )
            raise ValueError(msg)
        _wrap_root_prim(geometry_file)
        logger.info(
            "Wrapped %s root prim in Xform for ASWF compliance",
            geometry_file.name,
        )


def read_stage_metadata(file_path: Path) -> tuple[float, str]:
    """Read ``metersPerUnit`` and ``upAxis`` from a USD file."""
    stage = Usd.Stage.Open(str(file_path))
    if stage is None:
        return 1.0, "Y"

    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    up = UsdGeom.GetStageUpAxis(stage)
    up_str = "Y" if up == UsdGeom.Tokens.y else "Z"
    return mpu, up_str


def read_stage_metadata_from_dir(asset_dir: Path) -> tuple[float, str]:
    """Read ``metersPerUnit`` + ``upAxis`` from an asset's ``geo.usda``."""
    geo_path = asset_dir / ASWFLayerNames.GEO
    if geo_path.exists():
        return read_stage_metadata(geo_path)
    return 1.0, "Y"


def read_asset_mpu_from_file(asset_file: Path) -> float:
    """Read ``metersPerUnit`` from any USD file. Defaults to 1.0."""
    mpu, _ = read_stage_metadata(asset_file)
    return mpu if mpu > 0 else 1.0


def resolve_default_prim_name(asset_dir: Path) -> str:
    """Return the asset's ``defaultPrim`` name, falling back to folder name."""
    name = _get_default_prim_name(asset_dir)
    return name if name else asset_dir.name


def find_root_file(asset_dir: Path) -> Path | None:
    """Find the ASWF root file in an asset folder."""
    for ext in (".usd", ".usda", ".usdc"):
        candidate = asset_dir / f"{asset_dir.name}{ext}"
        if candidate.exists():
            return candidate
    return None


def to_layer_local_path(prim_path: str, default_prim_name: str) -> str:
    """Convert a composed prim path to a layer-local path.

    Strips the root prim prefix and re-adds it, handling the case
    where the path *is* the root prim.
    """
    prefix = f"/{default_prim_name}"
    relative = prim_path
    if prim_path.startswith(prefix):
        relative = prim_path[len(prefix):]
        if not relative:
            relative = "/"
    return f"/{default_prim_name}{relative}"


def ensure_layer_scope(
    layer: Sdf.Layer,
    default_prim_name: str,
    scope_name: str,
    scope_type: str,
) -> None:
    """Ensure ``/{default_prim_name}/{scope_name}`` exists in *layer*.

    Creates the root prim as an over and the scope prim as a def
    with the given type.
    """
    root_prim_path = Sdf.Path(f"/{default_prim_name}")
    scope_path = Sdf.Path(f"/{default_prim_name}/{scope_name}")

    if not layer.GetPrimAtPath(root_prim_path):
        Sdf.CreatePrimInLayer(layer, root_prim_path)
        layer.GetPrimAtPath(root_prim_path).specifier = Sdf.SpecifierOver

    if not layer.GetPrimAtPath(scope_path):
        Sdf.CreatePrimInLayer(layer, scope_path)
        scope = layer.GetPrimAtPath(scope_path)
        scope.specifier = Sdf.SpecifierDef
        scope.typeName = scope_type


def ensure_root_reference(asset_dir: Path, layer_file: str) -> None:
    """Ensure the asset's root file references *layer_file*.

    Adds the layer as a prepended reference on the root prim if not
    already present.
    """
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return

    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        return

    ref_path = f"./{layer_file}"
    if _has_reference(root_prim, ref_path):
        return

    root_prim.GetReferences().AddReference(
        ref_path, position=Usd.ListPositionFrontOfPrependList,
    )
    stage.Save()


def remove_empty_layer(
    layer_path: Path,
    asset_dir: Path,
    has_content,  # noqa: ANN001 — callable(Usd.Prim) -> bool
) -> None:
    """Remove a layer file if no prim in it satisfies *has_content*."""
    stage = Usd.Stage.Open(str(layer_path))
    if stage:
        for prim in stage.Traverse():
            if has_content(prim):
                return

    layer_path.unlink()
    _rebuild_root_references(asset_dir)
    logger.info("Removed empty %s from %s", layer_path.name, asset_dir.name)


def _rebuild_root_references(asset_dir: Path) -> None:
    """Rebuild the root file's references from existing layers."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return

    root_prim = stage.GetDefaultPrim()
    if root_prim is None:
        return

    root_prim.GetReferences().ClearReferences()

    for layer_file in (
        ASWFLayerNames.LGT, ASWFLayerNames.MTL, ASWFLayerNames.GEO,
    ):
        if (asset_dir / layer_file).exists():
            root_prim.GetReferences().AddReference(f"./{layer_file}")

    stage.Save()


def _has_reference(root_prim: Usd.Prim, asset_path: str) -> bool:
    """Check if a root prim already references a given asset."""
    return asset_path in get_prim_ref_paths(root_prim)


def _get_default_prim_name(asset_dir: Path) -> str | None:
    """Return the ``defaultPrim`` recorded in ``geo.usda``, if any."""
    geo_path = asset_dir / ASWFLayerNames.GEO
    if geo_path.exists():
        layer = Sdf.Layer.FindOrOpen(str(geo_path))
        if layer and layer.defaultPrim:
            return layer.defaultPrim
    return None


def _create_geo_layer(geo_dest: Path, geometry_source: Path) -> None:
    """Copy geometry into ``geo.usda`` using Sdf layer copy."""
    source_layer = Sdf.Layer.FindOrOpen(str(geometry_source))
    if source_layer is None:
        msg = f"Cannot open geometry source: {geometry_source}"
        raise RuntimeError(msg)

    dest_layer = Sdf.Layer.CreateNew(str(geo_dest))
    for prim_spec in source_layer.rootPrims:
        Sdf.CopySpec(
            source_layer, prim_spec.path, dest_layer, prim_spec.path,
        )
    dest_layer.defaultPrim = source_layer.defaultPrim
    dest_layer.Save()


def _create_root_file(
    root_path: Path,
    meters_per_unit: float,
    up_axis: str,
    has_mtl: bool,
) -> None:
    """Write the root .usd that references ``geo.usda`` (and ``mtl.usda``)."""
    geo_path = root_path.parent / ASWFLayerNames.GEO
    default_prim_name = root_path.parent.name
    if geo_path.exists():
        geo_layer = Sdf.Layer.FindOrOpen(str(geo_path))
        if geo_layer and geo_layer.defaultPrim:
            default_prim_name = geo_layer.defaultPrim

    stage = Usd.Stage.CreateNew(str(root_path))
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    UsdGeom.SetStageUpAxis(
        stage, UsdGeom.Tokens.y if up_axis == "Y" else UsdGeom.Tokens.z,
    )

    root_prim = stage.DefinePrim(f"/{default_prim_name}", "Xform")
    stage.SetDefaultPrim(root_prim)

    refs = root_prim.GetReferences()
    if has_mtl:
        refs.AddReference(f"./{ASWFLayerNames.MTL}")
    refs.AddReference(f"./{ASWFLayerNames.GEO}")

    stage.Save()


def _wrap_root_prim(geometry_file: Path) -> None:
    """Wrap a non-Xform root prim under an Xform parent in place."""
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

    with tempfile.NamedTemporaryFile(suffix=".usda", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        dest_layer = Sdf.Layer.CreateNew(str(tmp_path))

        Sdf.CreatePrimInLayer(dest_layer, root_path)
        wrapper = dest_layer.GetPrimAtPath(root_path)
        wrapper.specifier = Sdf.SpecifierDef
        wrapper.typeName = "Xform"

        child_path = Sdf.Path(f"/{default_prim_name}/mesh")
        Sdf.CopySpec(source_layer, root_path, dest_layer, child_path)

        dest_layer.defaultPrim = default_prim_name
        dest_layer.Save()

        shutil.move(str(tmp_path), str(geometry_file))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
