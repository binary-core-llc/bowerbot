# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""The shapes a library asset may have, and what stops one from being used.

BowerBot takes an asset from the library in one of three shapes: a geometry
file (nothing but geometry in it), an asset folder (a root file named like the
folder, ``geo.usda``, and the side layers BowerBot knows), or a ``.usdz``
package, placed as it is. Anything else is refused before it is copied, so a
project only ever holds the one layout the tools work on.
"""

from __future__ import annotations

import os
from pathlib import Path

from pxr import Sdf
from pxr import Tf
from pxr import Usd
from pxr import UsdLux
from pxr import UsdShade

from bowerbot import constants
from bowerbot import schemas
from bowerbot.utils import usd

# ── Which shape an asset has ──


def asset_folder_for(file_path: Path, library_dir: Path) -> Path | None:
    """The library's asset folder *file_path* belongs to, or None for a single file.

    An asset folder sits directly in the library and holds a root file named
    like itself. Files in any other folder are single files.
    """
    try:
        relative = file_path.resolve().relative_to(library_dir.resolve())
    except ValueError:
        return None
    if len(relative.parts) < 2:
        return None
    folder = library_dir.resolve() / relative.parts[0]
    if folder.name in constants.LibraryRules.NON_ASSET_DIRS:
        return None
    return folder if folder_root_file(folder) is not None else None


def folder_root_file(folder: Path) -> Path | None:
    """The file in *folder* named like the folder, or None when there is none."""
    for extension in sorted(constants.AssetFolderRules.USD_LAYER_EXTENSIONS):
        candidate = folder / f"{folder.name}{extension}"
        if candidate.is_file():
            return candidate
    return None


# ── What stops an asset from being used ──


def require(asset_path: Path, library_dir: Path | None) -> None:
    """Refuse *asset_path* unless it has one of the accepted shapes."""
    if not asset_path.exists():
        raise ValueError(f"Asset file not found: {asset_path}")
    found = problems(asset_path, library_dir)
    if not found:
        return
    folder = asset_folder_for(asset_path, library_dir) if library_dir is not None else None
    name = f"{folder.name}/" if folder is not None else asset_path.name
    raise ValueError(
        f"{name} cannot be used as it is: {'; '.join(found)}. "
        "BowerBot accepts a geometry file (one root prim, nothing but geometry), "
        "an asset folder (<name>/<name>.usda, geo.usda, and optionally mtl.usda, "
        "lgt.usda, phy.usda, variants.usda and extra geometry files, with its "
        "textures inside the folder), or a .usdz.",
    )


def problems(asset_path: Path, library_dir: Path | None) -> list[str]:
    """Why *asset_path* cannot be used as it is; empty when it has an accepted shape."""
    if asset_path.suffix.lower() == ".usdz":
        return []
    if asset_path.suffix.lower() not in constants.AssetFolderRules.USD_LAYER_EXTENSIONS:
        return ["it is not a USD file"]
    folder = asset_folder_for(asset_path, library_dir) if library_dir is not None else None
    if folder is not None:
        return _folder_problems(folder)
    return _geometry_file_problems(asset_path, subject="it")


def mark_refused(entries: list[dict[str, str]], library_dir: Path) -> None:
    """Add ``cannot_be_used`` (the reasons) to the listed assets that would be refused.

    Material files are left alone: they are not placed, ``bind_material`` reads them.
    """
    for entry in entries:
        if entry["category"] == schemas.AssetCategory.MTL.value:
            continue
        found = problems(Path(entry["path"]), library_dir)
        if found:
            entry["cannot_be_used"] = "; ".join(found)


# ── Helpers ──


def _folder_problems(folder: Path) -> list[str]:
    """What stops an asset folder from being used."""
    found: list[str] = []
    root_file = folder_root_file(folder)
    usd_extensions = constants.AssetFolderRules.USD_LAYER_EXTENSIONS
    side_layers = constants.AssetFolderRules.LIBRARY_SIDE_LAYERS

    nested = sorted(
        str(path.relative_to(folder)) for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in usd_extensions and path.parent != folder
    )
    if nested:
        found.append(f"it has USD files in sub-folders ({_some(nested)})")

    if not (folder / constants.ASWFLayerNames.GEO).is_file():
        found.append(f"it has no {constants.ASWFLayerNames.GEO}")

    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in usd_extensions:
            continue
        layer = _open(path)
        if layer is None:
            found.append(f"{path.name} cannot be read as USD")
            continue
        if path == root_file:
            found.extend(_root_file_problems(layer, path.name))
        elif path.name not in side_layers:
            found.extend(_geometry_file_problems(path, subject=path.name))
        if layer.subLayerPaths and path.name in side_layers:
            found.append(f"{path.name} uses sublayers")
        outside = [
            os.path.relpath(target, folder)
            for target in usd.references.layer_file_targets(layer)
            if folder.resolve() not in target.parents
        ]
        if outside:
            found.append(f"{path.name} points outside the folder ({_some(outside)})")
    return found


def _root_file_problems(layer: Sdf.Layer, name: str) -> list[str]:
    """What stops a folder's root file from being used."""
    found: list[str] = []
    if not layer.defaultPrim or layer.GetPrimAtPath(f"/{layer.defaultPrim}") is None:
        found.append(f"{name} has no default prim")
    if _defined_roots(layer) > 1:
        found.append(f"{name} has {_defined_roots(layer)} root prims")
    if layer.subLayerPaths:
        found.append(f"{name} uses sublayers")
    root_spec = layer.GetPrimAtPath(f"/{layer.defaultPrim}") if layer.defaultPrim else None
    if root_spec is not None:
        allowed = {constants.ASWFLayerNames.GEO, *constants.AssetFolderRules.LIBRARY_SIDE_LAYERS}
        others = [
            asset_path for asset_path in (
                *usd.references.reference_paths(root_spec),
                *usd.references.payload_paths(root_spec),
            )
            if asset_path.removeprefix("./") not in allowed
        ]
        if others:
            found.append(
                f"{name} points to {_some(others)}: the root prim may only point to "
                f"{constants.ASWFLayerNames.GEO} and the side layers (other geometry "
                "files belong in a variant)",
            )
    content = _content(layer)
    if content["materials"]:
        found.append(
            f"{name} holds materials ({_some(content['materials'])}): "
            f"keep them in {constants.ASWFLayerNames.MTL}",
        )
    if content["lights"]:
        found.append(
            f"{name} holds lights ({_some(content['lights'])}): "
            f"keep them in {constants.ASWFLayerNames.LGT}",
        )
    return found


def _geometry_file_problems(file_path: Path, *, subject: str) -> list[str]:
    """What stops a file from counting as geometry only; *subject* names it in the message."""
    layer = _open(file_path)
    if layer is None:
        return [f"{subject} cannot be read as USD"]
    found: list[str] = []
    if _defined_roots(layer) != 1:
        found.append(f"{subject} has {_defined_roots(layer)} root prims")
    content = _content(layer)
    if content["materials"]:
        found.append(f"{subject} holds materials ({_some(content['materials'])})")
    if content["bindings"]:
        found.append(f"{subject} binds materials ({_some(content['bindings'])})")
    if content["lights"]:
        found.append(f"{subject} holds lights ({_some(content['lights'])})")
    if layer.subLayerPaths:
        found.append(f"{subject} uses sublayers")
    if content["arcs"]:
        found.append(f"{subject} points to other files ({_some(content['arcs'])})")
    if content["files"]:
        found.append(f"{subject} has file paths such as textures ({_some(content['files'])})")
    return found


def _content(layer: Sdf.Layer) -> dict[str, list[str]]:
    """What a layer holds besides geometry: materials, bindings, lights, arcs, file paths."""
    registry = Usd.SchemaRegistry()
    light_api = registry.GetAPISchemaTypeName(UsdLux.LightAPI)
    content: dict[str, list[str]] = {
        "materials": [], "bindings": [], "lights": [], "arcs": [], "files": [],
    }

    def visit(path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(path)
        if isinstance(spec, Sdf.PrimSpec):
            if spec.typeName == registry.GetConcreteSchemaTypeName(UsdShade.Material):
                content["materials"].append(str(path))
            definition = registry.FindConcretePrimDefinition(spec.typeName)
            if definition is not None and light_api in definition.GetAppliedAPISchemas():
                content["lights"].append(str(path))
            content["arcs"].extend(usd.references.reference_paths(spec))
            content["arcs"].extend(usd.references.payload_paths(spec))
        elif isinstance(spec, Sdf.RelationshipSpec):
            if spec.name.startswith(UsdShade.Tokens.materialBinding):
                content["bindings"].append(str(spec.owner.path))
        elif isinstance(spec, Sdf.AttributeSpec):
            value = spec.default
            if isinstance(value, Sdf.AssetPath) and value.path:
                content["files"].append(value.path)
            elif isinstance(value, Sdf.AssetPathArray):
                content["files"].extend(item.path for item in value if item.path)

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return content


def _open(file_path: Path) -> Sdf.Layer | None:
    """The layer in *file_path*, or None when USD cannot read the file."""
    try:
        return Sdf.Layer.FindOrOpen(str(file_path))
    except Tf.ErrorException:
        return None


def _defined_roots(layer: Sdf.Layer) -> int:
    """How many root prims a layer defines; a ``class`` prim beside the root does not count."""
    return sum(1 for prim in layer.rootPrims if prim.specifier == Sdf.SpecifierDef)


def _some(items: list[str]) -> str:
    """The first few *items*, and how many more there are."""
    items = sorted(set(items))
    shown = ", ".join(items[: constants.LibraryRules.PROBLEM_EXAMPLES])
    extra = len(items) - constants.LibraryRules.PROBLEM_EXAMPLES
    return f"{shown} and {extra} more" if extra > 0 else shown
