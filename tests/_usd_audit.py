# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Audit a BowerBot project folder: is every file it wrote clean, resolvable and conventional?

``audit_project(project_dir)`` returns every :class:`Issue` it finds:

- layers: units where they belong, a defaultPrim with a spec, no empty
  layers, no empty ``over``s, no explicit-empty apiSchemas, no empty variant
  sets or bodies, selections that name a variant, valid prim names;
- paths: every reference, payload, sublayer, assetInfo identifier and asset
  attribute is relative, resolves, and stays inside the project;
- the composed scene: no composition errors or unresolved dependencies, no
  relationship targeting a missing prim or property (checked with every
  variant selected in turn), an unbroken model hierarchy, the placement
  convention (references on an ``asset`` child of an Xform wrapper), and
  ``/Scene`` as the defaultPrim, an assembly in the project's axis and units;
- asset folders: a canonical root with defaultPrim, kind and assetInfo, every
  side layer on disk referenced by the root (and none referenced but missing),
  and every layer in the folder reachable from the root.

A project texture nothing references is an ``info``: BowerBot keeps it until
the user deletes it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from pxr import Kind, Sdf, Usd, UsdGeom, UsdUtils

PRIM_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
VARIANT_NAME = re.compile(r"[A-Za-z0-9_|\-]+\Z")
SIDE_LAYERS = ("variants.usda", "contents.usda", "lgt.usda", "mtl.usda", "phy.usda")
LAYER_SUFFIXES = (".usd", ".usda", ".usdc")


@dataclass(frozen=True)
class Issue:
    """One audit finding. ``severity`` is ``error``, ``warn`` or ``info``."""

    severity: str
    code: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code} @ {self.where}: {self.message}"


def audit_project(project_dir: Path, *, sweep_variants: bool = True) -> list[Issue]:
    """Every issue in *project_dir*'s scene, layers and asset folders."""
    project_dir = Path(project_dir)
    out: list[Issue] = []
    meta = json.loads((project_dir / "project.json").read_text())
    scene_path = project_dir / meta.get("scene_file", "scene.usda")
    if not scene_path.exists():
        return out

    assets_dir = project_dir / "assets"
    for path in sorted(project_dir.rglob("*")):
        if path.suffix not in LAYER_SUFFIXES:
            continue
        root_like = path == scene_path or (
            assets_dir in path.parents and path.name == f"{path.parent.name}.usda"
        )
        _audit_layer(path, project_dir, out, expect_units=root_like or path.name == "geo.usda")

    stage = Usd.Stage.Open(str(scene_path))
    _audit_scene(stage, meta, out)
    if sweep_variants:
        _sweep_variants(stage, out, "scene.usda")

    if assets_dir.exists():
        for entry in sorted(assets_dir.iterdir()):
            if entry.is_dir():
                _audit_asset_folder(entry, project_dir, out)
            elif entry.suffix == ".usdz":
                _layers, _assets, unresolved = UsdUtils.ComputeAllDependencies(str(entry))
                for asset_path in unresolved:
                    rel = entry.relative_to(project_dir)
                    _add(out, "error", "usdz-unresolved", rel, asset_path)

    _unused_textures(project_dir, out)
    return out


def problems(issues: list[Issue]) -> list[Issue]:
    """The errors and warnings among *issues* (infos are expected states)."""
    return [issue for issue in issues if issue.severity in ("error", "warn")]


# ── layers ──


def _audit_layer(path: Path, project_dir: Path, out: list[Issue], *, expect_units: bool) -> None:
    rel = path.relative_to(project_dir)
    layer = Sdf.Layer.FindOrOpen(str(path))
    if layer is None:
        _add(out, "error", "layer-unopenable", rel, "layer does not open")
        return
    layer.Reload()
    if expect_units:
        for key in ("metersPerUnit", "upAxis"):
            if not layer.pseudoRoot.HasInfo(key):
                _add(out, "error", f"no-{key}", rel, f"layer has no {key}")
    if layer.defaultPrim and not layer.GetPrimAtPath(
        Sdf.Path.absoluteRootPath.AppendChild(layer.defaultPrim),
    ):
        _add(out, "error", "defaultPrim-missing", rel,
             f"defaultPrim {layer.defaultPrim} has no spec")
    if not list(layer.rootPrims):
        _add(out, "error", "empty-layer", rel, "layer has no prims (stale file?)")

    for spec_path, arc, asset_path in _asset_paths(layer):
        where = f"{rel}:{spec_path}"
        if os.path.isabs(asset_path) or re.match(r"^[A-Za-z]:[\\/]", asset_path):
            _add(out, "error", "absolute-path", where, f"{arc} uses absolute path {asset_path}")
            continue
        if "[" in asset_path:  # a path inside a usdz package
            continue
        resolved = layer.ComputeAbsolutePath(asset_path)
        if not os.path.exists(resolved):
            _add(out, "error", "unresolved-path", where, f"{arc} {asset_path} does not resolve")
            continue
        try:
            Path(resolved).resolve().relative_to(project_dir.resolve())
        except ValueError:
            _add(out, "error", "path-outside-project", where, f"{arc} {asset_path} -> {resolved}")

    layer.Traverse(Sdf.Path.absoluteRootPath, lambda p: _audit_spec(layer, p, rel, out))


def _audit_spec(layer: Sdf.Layer, path: Sdf.Path, rel: Path, out: list[Issue]) -> None:
    spec = layer.GetObjectAtPath(path)
    where = f"{rel}:{path}"
    if isinstance(spec, Sdf.VariantSpec):
        if spec.primSpec is not None and _is_empty_prim_spec(spec.primSpec):
            _add(out, "error", "empty-variant-body", where, "variant body is empty")
        return
    if not isinstance(spec, Sdf.PrimSpec) or path == Sdf.Path.absoluteRootPath:
        return
    if not PRIM_NAME.match(spec.name):
        _add(out, "error", "bad-prim-name", where, f"prim name {spec.name!r}")
    if spec.specifier == Sdf.SpecifierOver and _is_empty_prim_spec(spec):
        _add(out, "error", "empty-over", where, "empty over spec")
    if spec.HasInfo("apiSchemas"):
        op = spec.GetInfo("apiSchemas")
        if op.isExplicit and not op.explicitItems:
            _add(out, "error", "explicit-empty-apiSchemas", where,
                 "apiSchemas = None wipes the API schemas weaker layers apply")
        elif not op.isExplicit and not (op.prependedItems or op.appendedItems or op.deletedItems):
            _add(out, "warn", "empty-apiSchemas-op", where, "empty apiSchemas list op")
    for set_name, vset in spec.variantSets.items():
        if not vset.variants:
            _add(out, "error", "empty-variant-set", where,
                 f"variant set {set_name} has no variants")
        for name in vset.variants.keys():
            if not VARIANT_NAME.match(name):
                _add(out, "warn", "odd-variant-name", where, f"{set_name}={name!r}")
    selections = dict(spec.GetInfo("variantSelection")) if spec.HasInfo("variantSelection") else {}
    for set_name, name in selections.items():
        variants = spec.variantSets[set_name].variants if set_name in spec.variantSets else None
        if variants is not None and name and name not in variants:
            _add(out, "error", "selection-missing-variant", where,
                 f"{set_name}={name} names no variant in this layer")


def _asset_paths(layer: Sdf.Layer) -> list[tuple[str, str, str]]:
    """``(spec path, arc, asset path)`` for every asset path *layer* authors."""
    found = [("<layer>", "sublayer", sub) for sub in layer.subLayerPaths]

    def visit(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if isinstance(spec, Sdf.PrimSpec):
            for arc, list_op in (("reference", spec.referenceList), ("payload", spec.payloadList)):
                found.extend(
                    (str(path), arc, item.assetPath)
                    for item in list_op.GetAddedOrExplicitItems() if item.assetPath
                )
            info = spec.GetInfo("assetInfo") if spec.HasInfo("assetInfo") else None
            if info and isinstance(info.get("identifier"), Sdf.AssetPath):
                found.append((str(path), "assetInfo", info["identifier"].path))
        elif isinstance(spec, Sdf.AttributeSpec):
            values = [spec.default] if spec.HasDefaultValue() else []
            values += [layer.QueryTimeSample(path, t) for t in layer.ListTimeSamplesForPath(path)]
            for value in values:
                if isinstance(value, Sdf.AssetPath) and value.path:
                    found.append((str(path), "attr", value.path))
                elif isinstance(value, Sdf.AssetPathArray):
                    found.extend((str(path), "attr", a.path) for a in value if a.path)

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return found


def _is_empty_prim_spec(spec: Sdf.PrimSpec) -> bool:
    authored = set(spec.ListInfoKeys()) - {"specifier", "typeName"}
    return not (
        authored or spec.properties or spec.nameChildren or spec.variantSets or spec.typeName
    )


# ── the composed scene ──


def _audit_scene(stage: Usd.Stage, meta: dict, out: list[Issue]) -> None:
    default = stage.GetDefaultPrim()
    if not default or default.GetPath() != Sdf.Path("/Scene"):
        _add(out, "error", "scene-defaultPrim", "scene.usda",
             f"defaultPrim is {default.GetPath() if default else None}")
    elif Usd.ModelAPI(default).GetKind() != "assembly":
        _add(out, "error", "scene-kind", "scene.usda",
             f"/Scene kind is {Usd.ModelAPI(default).GetKind()!r}")
    if UsdGeom.GetStageUpAxis(stage) != meta.get("up_axis", "Y"):
        _add(out, "error", "scene-upAxis", "scene.usda",
             f"{UsdGeom.GetStageUpAxis(stage)} vs project {meta.get('up_axis')}")
    if abs(UsdGeom.GetStageMetersPerUnit(stage) - float(meta.get("meters_per_unit", 1.0))) > 1e-9:
        _add(out, "error", "scene-mpu", "scene.usda",
             f"{UsdGeom.GetStageMetersPerUnit(stage)} vs project {meta.get('meters_per_unit')}")
    _composition(stage, out, "scene.usda")
    _relationships(stage, out, "scene.usda")
    for prim in stage.Traverse():
        kind = Usd.ModelAPI(prim).GetKind()
        if kind and Kind.Registry.IsA(kind, Kind.Tokens.model) and not prim.IsModel():
            _add(out, "warn", "broken-model-hierarchy", f"scene.usda:{prim.GetPath()}",
                 f"kind={kind} but an ancestor is not a group or assembly")

    layer = stage.GetRootLayer()

    def placement(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if not isinstance(spec, Sdf.PrimSpec) or path.ContainsPrimVariantSelection():
            return
        arcs = [
            *spec.referenceList.GetAddedOrExplicitItems(),
            *spec.payloadList.GetAddedOrExplicitItems(),
        ]
        if not any(arc.assetPath for arc in arcs):
            return
        if spec.name != "asset":
            _add(out, "error", "ref-not-on-asset-child", f"scene.usda:{path}",
                 "reference is not on an `asset` child")
        parent = stage.GetPrimAtPath(path.GetParentPath())
        if parent and parent.GetTypeName() != "Xform":
            _add(out, "warn", "wrapper-not-xform", f"scene.usda:{path.GetParentPath()}",
                 parent.GetTypeName())

    layer.Traverse(Sdf.Path.absoluteRootPath, placement)


def _composition(stage: Usd.Stage, out: list[Issue], label: str) -> None:
    for error in stage.GetCompositionErrors():
        _add(out, "error", "composition-error", label, str(error)[:300])
    _layers, _assets, unresolved = UsdUtils.ComputeAllDependencies(stage.GetRootLayer().identifier)
    for asset_path in unresolved:
        _add(out, "error", "unresolved-dependency", label, asset_path)


def _relationships(stage: Usd.Stage, out: list[Issue], label: str) -> None:
    predicate = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), predicate):
        for rel in prim.GetRelationships():
            for target in rel.GetTargets():
                target_prim = stage.GetPrimAtPath(target.GetPrimPath())
                if not target_prim.IsValid():
                    _add(out, "error", "dangling-rel", f"{label}:{rel.GetPath()}", f"-> {target}")
                elif target.IsPropertyPath() and not target_prim.GetProperty(target.name):
                    _add(out, "error", "dangling-rel", f"{label}:{rel.GetPath()}",
                         f"-> {target} (no such property)")


def _sweep_variants(stage: Usd.Stage, out: list[Issue], label: str) -> None:
    """Select every variant of every set in turn (session layer) and check that state."""
    carriers = [
        prim.GetPath()
        for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.PrimAllPrimsPredicate)
        if prim.GetVariantSets().GetNames()
    ]
    session = stage.GetSessionLayer()
    for path in carriers:
        for set_name in stage.GetPrimAtPath(path).GetVariantSets().GetNames():
            vsets = stage.GetPrimAtPath(path).GetVariantSets()
            for name in vsets.GetVariantSet(set_name).GetVariantNames():
                with Usd.EditContext(stage, session):
                    vset = stage.GetPrimAtPath(path).GetVariantSets().GetVariantSet(set_name)
                    vset.SetVariantSelection(name)
                state = f"{label} [{path}{{{set_name}={name}}}]"
                for error in stage.GetCompositionErrors():
                    _add(out, "error", "composition-error", state, str(error)[:300])
                _relationships(stage, out, state)
                session.Clear()


# ── asset folders ──


def _audit_asset_folder(folder: Path, project_dir: Path, out: list[Issue]) -> None:
    rel = folder.relative_to(project_dir)
    root = folder / f"{folder.name}.usda"
    if not root.exists():
        _add(out, "error", "no-canonical-root", rel, f"no {folder.name}.usda root")
        return
    layer = Sdf.Layer.FindOrOpen(str(root))
    layer.Reload()
    if not layer.defaultPrim:
        _add(out, "error", "root-no-defaultPrim", rel, "root has no defaultPrim")
        return
    stage = Usd.Stage.Open(str(root))
    default = stage.GetDefaultPrim()
    if Usd.ModelAPI(default).GetKind() not in ("component", "assembly"):
        _add(out, "warn", "root-kind", rel, f"root kind is {Usd.ModelAPI(default).GetKind()!r}")
    info = default.GetAssetInfo() or {}
    for key in ("identifier", "name", "version"):
        if key not in info:
            _add(out, "warn", "assetInfo-missing", rel, f"assetInfo lacks {key}")
    if default.GetTypeName() != "Xform":
        _add(out, "warn", "root-not-xform", rel, f"root prim type {default.GetTypeName()!r}")

    spec = layer.GetPrimAtPath(f"/{layer.defaultPrim}")
    referenced = {Path(r.assetPath).name for r in spec.referenceList.GetAddedOrExplicitItems()}
    payloads = {Path(p.assetPath).name for p in spec.payloadList.GetAddedOrExplicitItems()}
    for side in SIDE_LAYERS:
        exists = (folder / side).exists()
        if exists and side not in referenced:
            _add(out, "error", "side-layer-unreferenced", rel,
                 f"{side} exists but the root does not reference it")
        if side in referenced and not exists:
            _add(out, "error", "side-layer-missing", rel,
                 f"root references {side} but the file is gone")
    layers, _assets, unresolved = UsdUtils.ComputeAllDependencies(str(root))
    reachable = {os.path.realpath(lyr.realPath) for lyr in layers if lyr.realPath}
    geo = folder / "geo.usda"
    if geo.exists() and "geo.usda" not in payloads | referenced and (
        os.path.realpath(str(geo)) not in reachable
    ):  # an LOD set loads it from a variant body instead of the root
        _add(out, "warn", "geo-not-composed", rel,
             "geo.usda is not a payload or reference of the root, nor of a variant")
    for asset_path in unresolved:
        _add(out, "error", "asset-unresolved", rel, asset_path)
    for path in folder.rglob("*"):
        if path.suffix in LAYER_SUFFIXES and os.path.realpath(str(path)) not in reachable:
            _add(out, "warn", "unreachable-layer", path.relative_to(project_dir),
                 "file is not reachable from the asset root")
    _composition(stage, out, str(rel))
    _relationships(stage, out, str(rel))


def _unused_textures(project_dir: Path, out: list[Issue]) -> None:
    textures = project_dir / "textures"
    if not textures.exists():
        return
    used: set[str] = set()
    for path in project_dir.rglob("*.usda"):
        layer = Sdf.Layer.FindOrOpen(str(path))
        for _spec, _arc, asset_path in _asset_paths(layer):
            if "[" not in asset_path and not os.path.isabs(asset_path):
                used.add(os.path.realpath(layer.ComputeAbsolutePath(asset_path)))
    for texture in textures.iterdir():
        if os.path.realpath(str(texture)) not in used:
            _add(out, "info", "unused-texture", texture.relative_to(project_dir),
                 "no layer references it")


def _add(out: list[Issue], severity: str, code: str, where: object, message: str) -> None:
    out.append(Issue(severity, code, str(where), message))
