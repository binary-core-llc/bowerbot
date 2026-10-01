# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The ASWF asset folder on disk: its root file and defaultPrim, its layers, building one.

An asset folder holds a root file that references its layers (``geo.usda`` as a
payload; ``mtl``, ``lgt``, ``phy``, ``variants`` and ``contents`` as references).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from pxr import Gf
from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import usd

logger = logging.getLogger(__name__)

# ── The root file and defaultPrim ──


def find_root_file(asset_dir: Path) -> Path | None:
    """Return the canonical ASWF root file in *asset_dir*, or ``None``."""
    for ext in (".usd", ".usda", ".usdc"):
        candidate = asset_dir / f"{asset_dir.name}{ext}"
        if candidate.exists():
            return candidate
    return None


def resolve_default_prim_name(asset_dir: Path) -> str:
    """Return the asset's ``defaultPrim`` name, falling back to folder name."""
    name = _get_default_prim_name(asset_dir)
    return name if name else asset_dir.name


def detect_folder_root(folder: Path) -> schemas.FolderDetection:
    """Classify *folder* and identify its root USD file when possible.

    USD composition is the source of truth: the file no sibling depends
    on is the root. With multiple candidates, naming heuristics
    (``<folder>``, ``root``, ``main``, ``asset``) break the tie.
    """
    folder = folder.resolve()
    if not folder.is_dir():
        return schemas.FolderDetection(
            outcome=schemas.DetectionOutcome.EMPTY,
            folder=str(folder),
            reason="not a directory",
        )

    usd_files = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in constants.AssetFolderRules.USD_LAYER_EXTENSIONS
    )
    if not usd_files:
        return schemas.FolderDetection(
            outcome=schemas.DetectionOutcome.EMPTY,
            folder=str(folder),
            reason="no USD files at the top level",
        )

    if len(usd_files) == 1:
        return schemas.FolderDetection(
            outcome=schemas.DetectionOutcome.UNAMBIGUOUS,
            folder=str(folder),
            root=str(usd_files[0]),
            reason="only USD file in the folder",
        )

    candidates = _candidate_roots_by_dep_graph(usd_files)

    if len(candidates) == 1:
        return schemas.FolderDetection(
            outcome=schemas.DetectionOutcome.UNAMBIGUOUS,
            folder=str(folder),
            root=str(candidates[0]),
            reason="only USD file in the folder not referenced by a sibling",
        )

    if not candidates:
        return schemas.FolderDetection(
            outcome=schemas.DetectionOutcome.AMBIGUOUS,
            folder=str(folder),
            candidates=[str(p) for p in usd_files],
            reason="circular references between siblings",
        )

    tiebreak = _name_tiebreak(candidates, folder.name)
    if tiebreak is not None:
        return schemas.FolderDetection(
            outcome=schemas.DetectionOutcome.UNAMBIGUOUS,
            folder=str(folder),
            root=str(tiebreak),
            reason=f"multiple candidates; picked by naming convention '{tiebreak.stem}'",
        )

    return schemas.FolderDetection(
        outcome=schemas.DetectionOutcome.AMBIGUOUS,
        folder=str(folder),
        candidates=[str(p) for p in candidates],
        reason="multiple independent USD files with no cross-references",
    )


def asset_has_root_payload(asset_dir: Path) -> bool:
    """Return whether the asset's root prim has a directly authored payload."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return False
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return False
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return False
    plist = prim_spec.payloadList
    return bool(
        plist.prependedItems
        or plist.appendedItems
        or plist.addedItems
        or plist.explicitItems,
    )


def clear_root_payload(asset_dir: Path) -> None:
    """Strip every payload list-op slot from the asset's root prim."""
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return
    layer = Sdf.Layer.FindOrOpen(str(root_file))
    if layer is None:
        return
    default_prim_name = resolve_default_prim_name(asset_dir)
    prim_spec = layer.GetPrimAtPath(f"/{default_prim_name}")
    if prim_spec is None:
        return
    plist = prim_spec.payloadList
    plist.ClearEdits()
    layer.Save()


def normalize_root_metadata(root_file: Path, asset_name: str) -> None:
    """Ensure the intaken asset's root prim has Kind + assetInfo + class inherit."""
    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return
    root_prim = stage.GetDefaultPrim()
    if not root_prim or not root_prim.IsValid():
        return

    apply_aswf_root_metadata(
        root_prim,
        asset_name=asset_name,
        asset_identifier=f"./{root_file.name}",
    )
    _apply_aswf_class_inherits(stage, root_prim.GetName())
    stage.Save()


def apply_aswf_root_metadata(
    prim: Usd.Prim,
    *,
    asset_name: str,
    asset_identifier: str,
    kind: str = "component",
    version: str = "1.0",
    force: bool = False,
) -> None:
    """Apply ASWF-canonical Kind + assetInfo to an asset root prim.

    When *force* is False, only fills missing fields, preserving any
    metadata already authored upstream (DCC, asset-management system).
    """
    model_api = Usd.ModelAPI(prim)
    if force or not model_api.GetKind():
        model_api.SetKind(kind)

    existing = prim.GetAssetInfo() or {}
    info = dict(existing) if not force else {}
    info.setdefault("identifier", Sdf.AssetPath(asset_identifier))
    info.setdefault("name", asset_name)
    info.setdefault("version", version)
    if force:
        info["identifier"] = Sdf.AssetPath(asset_identifier)
        info["name"] = asset_name
        info["version"] = version
    prim.SetAssetInfo(info)


# ── The asset's layers ──


def list_alternate_geo_files(asset_dir: Path) -> list[str]:
    """USD files in the asset folder that aren't canonical ASWF layers or root."""
    if not asset_dir.is_dir():
        return []
    canonical = {
        constants.ASWFLayerNames.GEO,
        constants.ASWFLayerNames.MTL,
        constants.ASWFLayerNames.LGT,
        constants.ASWFLayerNames.PHY,
        constants.ASWFLayerNames.CONTENTS,
        constants.ASWFLayerNames.VARIANTS,
    }
    canonical |= {
        f"{asset_dir.name}{ext}" for ext in constants.AssetFolderRules.USD_LAYER_EXTENSIONS
    }
    return sorted(
        p.name for p in asset_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in constants.AssetFolderRules.USD_LAYER_EXTENSIONS
        and p.name not in canonical
    )


def to_layer_local_path(prim_path: str, default_prim_name: str) -> str:
    """Convert a composed prim path to a layer-local path under defaultPrim."""
    prefix = f"/{default_prim_name}"
    if prim_path in ("", "/", prefix):
        return prefix
    if prim_path.startswith(f"{prefix}/"):
        return prim_path
    if not prim_path.startswith("/"):
        prim_path = f"/{prim_path}"
    return f"{prefix}{prim_path}"


def ensure_layer_scope(
    layer: Sdf.Layer,
    default_prim_name: str,
    scope_name: str,
    scope_type: str,
) -> None:
    """Ensure ``/{default_prim_name}/{scope_name}`` exists in *layer*."""
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
    """Ensure the asset's root file references *layer_file*."""
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
    if ref_path in usd.references.get_prim_ref_paths(root_prim):
        return

    del stage
    rebuild_root_references(asset_dir)


def rebuild_root_references(asset_dir: Path) -> None:
    """Rebuild the root's arcs to BowerBot's layers: geo via payload, the others via references.

    Arcs to any other file (a package's own model, look or part files) are
    kept, with their prim path and layer offset. The references among them
    come after BowerBot's layers, so an edit made through BowerBot stays the
    stronger opinion.
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

    geo_file = constants.ASWFLayerNames.GEO
    side_layers = constants.AssetFolderRules.CANONICAL_REFERENCE_ORDER
    root_spec = stage.GetRootLayer().GetPrimAtPath(root_prim.GetPath())
    payloads = list(root_spec.payloadList.GetAddedOrExplicitItems())
    references = list(root_spec.referenceList.GetAddedOrExplicitItems())
    own_payloads = [arc for arc in payloads if _sibling_file(arc.assetPath) != geo_file]
    own_references = [
        arc for arc in references
        if _sibling_file(arc.assetPath) not in (geo_file, *side_layers)
    ]

    root_prim.GetReferences().ClearReferences()
    root_prim.GetPayloads().ClearPayloads()

    if (asset_dir / geo_file).exists():
        root_prim.GetPayloads().AddPayload(f"./{geo_file}")
    for payload in own_payloads:
        root_prim.GetPayloads().AddPayload(payload)

    for layer_file in side_layers:
        if (asset_dir / layer_file).exists():
            root_prim.GetReferences().AddReference(f"./{layer_file}")
    for reference in own_references:
        root_prim.GetReferences().AddReference(reference)

    stage.Save()


def remove_empty_layer(
    layer_path: Path,
    asset_dir: Path,
    has_content: Callable[[Usd.Prim], bool],
) -> None:
    """Remove *layer_path* when no prim in it satisfies *has_content*."""
    stage = Usd.Stage.Open(str(layer_path))
    if stage:
        for prim in stage.Traverse():
            if has_content(prim):
                return

    layer_path.unlink()
    rebuild_root_references(asset_dir)
    logger.info("Removed empty %s from %s", layer_path.name, asset_dir.name)


# ── Units and bounds of the geometry ──


def asset_metrics(
    asset_dir: Path, *, project_mpu: float, project_up_axis: str,
) -> tuple[float, str]:
    """``(metersPerUnit, upAxis)`` the asset's root file declares; the project's for the rest.

    A metersPerUnit that is zero or negative counts as 1.0.
    """
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return usd.metrics.usable_mpu(project_mpu), project_up_axis
    mpu, up_axis = usd.metrics.file_metrics(
        root_file, default_mpu=project_mpu, default_up_axis=project_up_axis,
    )
    return usd.metrics.usable_mpu(mpu), up_axis


def declare_missing_metrics(
    root_file: Path, *, project_mpu: float, project_up_axis: str,
) -> None:
    """Write the project's metersPerUnit and upAxis into *root_file* where it declares none."""
    stage = Usd.Stage.Open(str(root_file), Usd.Stage.LoadNone)
    if stage is None:
        return
    changed = False
    if not UsdGeom.StageHasAuthoredMetersPerUnit(stage):
        UsdGeom.SetStageMetersPerUnit(stage, project_mpu)
        changed = True
    if not stage.HasAuthoredMetadata(UsdGeom.Tokens.upAxis):
        UsdGeom.SetStageUpAxis(stage, usd.metrics.up_axis_token(project_up_axis))
        changed = True
    if changed:
        stage.GetRootLayer().Save()


def unit_factor(asset_dir: Path, *, project_mpu: float) -> float:
    """Return the factor that converts a length in project units into the asset's units."""
    mpu, _ = asset_metrics(asset_dir, project_mpu=project_mpu, project_up_axis="Y")
    return project_mpu / mpu


def conform_matrix(
    asset_dir: Path, *, project_mpu: float, project_up_axis: str,
) -> Gf.Matrix4d:
    """The matrix a scene placement applies to the asset: into the project's units and up axis."""
    mpu, up_axis = asset_metrics(
        asset_dir, project_mpu=project_mpu, project_up_axis=project_up_axis,
    )
    unit_scale, correction = usd.metrics.conform(
        mpu, up_axis, parent_mpu=project_mpu, parent_up_axis=project_up_axis,
    )
    return usd.metrics.conform_matrix(unit_scale, correction)


def get_geometry_bounds(asset_dir: Path) -> dict[str, dict[str, float]] | None:
    """Return the bounds of the asset's own geometry in its own units and axes, or ``None``.

    Measured on the asset's root file, so geometry from every file the root
    composes counts. The asset's lights and the assets added to it do not.
    """
    root_file = find_root_file(asset_dir)
    if root_file is None:
        return None

    stage = Usd.Stage.Open(str(root_file))
    if stage is None:
        return None

    root = stage.GetDefaultPrim()
    if not root:
        return None

    # Switched off in the session layer only: nothing is written to the asset.
    stage.SetEditTarget(stage.GetSessionLayer())
    for scope in (
        constants.AssetFolderNamespace.CONTENTS_SCOPE,
        constants.AssetFolderNamespace.LIGHTS_SCOPE,
    ):
        child = root.GetChild(scope)
        if child:
            child.SetActive(False)

    bbox = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_],
    )
    rng = bbox.ComputeWorldBound(root).ComputeAlignedRange()
    if rng.IsEmpty():
        return None

    mn = rng.GetMin()
    mx = rng.GetMax()

    return {
        "min": {"x": mn[0], "y": mn[1], "z": mn[2]},
        "max": {"x": mx[0], "y": mx[1], "z": mx[2]},
        "center": {
            "x": (mn[0] + mx[0]) / 2,
            "y": (mn[1] + mx[1]) / 2,
            "z": (mn[2] + mx[2]) / 2,
        },
        "size": {
            "x": mx[0] - mn[0],
            "y": mx[1] - mn[1],
            "z": mx[2] - mn[2],
        },
    }


# ── Building an asset folder ──


def create_asset_folder(
    output_dir: Path,
    asset_name: str,
    geometry_file: Path,
    *,
    project_mpu: float,
    project_up_axis: str,
) -> Path:
    """Create an ASWF asset folder with root + ``geo.usda``.

    The root declares the units and up axis the source file declares, or the
    project's where the source declares none.
    """
    asset_dir = output_dir / asset_name
    asset_dir.mkdir(parents=True, exist_ok=True)

    mpu, up = usd.metrics.file_metrics(
        geometry_file, default_mpu=project_mpu, default_up_axis=project_up_axis,
    )

    geo_path = asset_dir / constants.ASWFLayerNames.GEO
    if not geo_path.exists():
        _create_geo_layer(geo_path, geometry_file)

    root_path = asset_dir / f"{asset_name}.usda"
    if not root_path.exists():
        _create_root_file(root_path, mpu, up)

    logger.info("Created ASWF asset folder: %s", asset_dir)
    return root_path


# ── Which files reference an asset folder ──


def find_asset_references(
    project_dir: Path,
    folder_name: str,
    skip_dir: Path | None = None,
) -> list[str]:
    """Scan *project_dir* for USD files referencing *folder_name* in any variant body or payload."""
    referencing: list[str] = []
    for usd_file in sorted(project_dir.rglob("*")):
        if usd_file.suffix not in (".usd", ".usda", ".usdc"):
            continue
        if skip_dir is not None:
            try:
                usd_file.relative_to(skip_dir)
                continue
            except ValueError:
                pass
        layer = Sdf.Layer.FindOrOpen(str(usd_file))
        if layer is None:
            continue
        if usd.references.layer_references_folder(layer, folder_name):
            referencing.append(str(usd_file.relative_to(project_dir)))
    return referencing


# ── Helpers ──


def _get_default_prim_name(asset_dir: Path) -> str | None:
    """Return the ``defaultPrim`` recorded in ``geo.usda``, if any."""
    geo_path = asset_dir / constants.ASWFLayerNames.GEO
    if geo_path.exists():
        layer = Sdf.Layer.FindOrOpen(str(geo_path))
        if layer and layer.defaultPrim:
            return layer.defaultPrim
    return None


def _sibling_file(asset_path: str) -> str | None:
    """The file name when *asset_path* names a file beside the root (``./geo.usda``), else None."""
    if not asset_path:
        return None
    path = Path(asset_path)
    return path.name if path.parent == Path() else None


def _candidate_roots_by_dep_graph(usd_files: list[Path]) -> list[Path]:
    """Return files no sibling depends on (so they can't be sub-layers)."""
    usd_set = {p.resolve() for p in usd_files}
    referenced: set[Path] = set()
    for candidate in usd_files:
        found, _missing = usd.references.resolve_dependencies(candidate)
        for dep in found:
            dep_resolved = dep.resolve()
            if dep_resolved == candidate.resolve():
                continue
            if dep_resolved in usd_set:
                referenced.add(dep_resolved)
    return [p for p in usd_files if p.resolve() not in referenced]


def _name_tiebreak(candidates: list[Path], folder_name: str) -> Path | None:
    """Pick the preferred candidate by filename convention, or ``None``."""
    for stem in (folder_name, *constants.IntakeRules.ROOT_NAME_HINTS):
        matches = [p for p in candidates if p.stem == stem]
        if len(matches) == 1:
            return matches[0]
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
) -> None:
    """Write the root .usd that references ``geo.usda``."""
    geo_path = root_path.parent / constants.ASWFLayerNames.GEO
    default_prim_name = root_path.parent.name
    if geo_path.exists():
        geo_layer = Sdf.Layer.FindOrOpen(str(geo_path))
        if geo_layer and geo_layer.defaultPrim:
            default_prim_name = geo_layer.defaultPrim

    stage = Usd.Stage.CreateNew(str(root_path))
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    UsdGeom.SetStageUpAxis(stage, usd.metrics.up_axis_token(up_axis))

    root_prim = stage.DefinePrim(f"/{default_prim_name}", "Xform")
    stage.SetDefaultPrim(root_prim)
    root_prim.GetPayloads().AddPayload(f"./{constants.ASWFLayerNames.GEO}")

    apply_aswf_root_metadata(
        root_prim,
        asset_name=root_path.parent.name,
        asset_identifier=f"./{root_path.name}",
        force=True,
    )
    _apply_aswf_class_inherits(stage, default_prim_name)

    stage.Save()


def _apply_aswf_class_inherits(
    stage: Usd.Stage, default_prim_name: str,
) -> bool:
    """Add a sibling ``class _class_<name>`` and inherit it from the root."""
    class_path = f"/_class_{default_prim_name}"
    class_prim = stage.GetPrimAtPath(class_path)
    if not class_prim or not class_prim.IsValid():
        class_prim = stage.OverridePrim(class_path)
        class_prim.SetSpecifier(Sdf.SpecifierClass)
        class_prim.SetTypeName("Xform")

    root_prim = stage.GetDefaultPrim()
    if not root_prim or not root_prim.IsValid():
        return False
    inherits = root_prim.GetInherits()
    existing = inherits.GetAllDirectInherits()
    if Sdf.Path(class_path) in existing:
        return False
    inherits.AddInherit(class_path)
    return True
