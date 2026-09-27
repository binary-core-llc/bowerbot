# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Asset freeze — moving a root prim's transform onto the asset's parts."""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pxr import Gf, Sdf, Usd, UsdGeom

from bowerbot.schemas import FreezeRules
from bowerbot.utils.core.asset_folder import find_root_file, require_folder_entry
from bowerbot.utils.core.transforms import top_parts


def freeze_one_asset(assets_dir: Path, name: str) -> dict[str, Any]:
    """Move one asset's root transform onto its parts; raise if the folder or root is missing."""
    asset_dir = require_folder_entry(assets_dir, name)
    if not asset_dir.is_dir():
        msg = f"Asset folder not found: {name}"
        raise ValueError(msg)
    root_file = find_root_file(asset_dir)
    if root_file is None:
        msg = f"No root file in asset folder '{name}' (expected {name}.usda)."
        raise ValueError(msg)
    return {"name": name, "baked": freeze_root_transform(root_file)}


def freeze_root_transform(root_file: Path) -> bool:
    """Move the root prim's transform onto the parts below it; the root ends at identity.

    Works on what *root_file* composes: the transform may be authored in the
    root file or in the geometry file it loads, and the parts may sit behind
    variants (an LOD set), each with its own transform. Each top part (looking
    through scopes) gets its root's matrix in front of its own transform, in
    the file that decides its transform, so every part keeps its world
    position, size and orientation: nested pivots, implicit shapes and
    non-uniform scale included. Vertex data is not edited, and a stale
    ``extentsHint`` on the root is dropped.

    Refused, with nothing written: an animated root transform, parts shared
    by variants that move the root differently, and any result where a prim
    would move (checked for every variant combination). Only files inside the
    asset folder are edited. Returns ``False`` when there is nothing to move.
    """
    stage = Usd.Stage.Open(str(root_file))
    root = _xformable_root(stage)
    if root is None:
        return False
    combinations = _variant_combinations(root)
    if combinations is None:
        msg = (
            f"{root.GetName()} has more than {FreezeRules.MAX_VARIANT_COMBINATIONS} variant "
            f"combinations, too many to check the frozen result for. Freeze the "
            f"transforms in your DCC and re-export."
        )
        raise ValueError(msg)
    transforms = _root_transforms(stage, root, combinations)
    if all(_matrix_is_identity(matrix) for matrix, _ in transforms):
        return False
    if any(animated for _, animated in transforms):
        raise ValueError(_animated_message(root_file))

    before: list[dict[Sdf.Path, Gf.Matrix4d]] = []
    # Switching variants releases the layers a selection doesn't use: hold them.
    layers: dict[str, Sdf.Layer] = {}
    root_specs: set[tuple[str, Sdf.Path]] = set()
    part_matrices: dict[tuple[str, Sdf.Path], Gf.Matrix4d] = {}
    for combination, (matrix, _) in zip(combinations, transforms, strict=True):
        with _selected(stage, root, combination):
            before.append(_world_transforms(root))
            for spec in root.GetPrimStack():
                if spec.layer != stage.GetSessionLayer():
                    root_specs.add(_hold(spec, layers))
            for part in top_parts(root):
                if UsdGeom.Xformable(part).GetResetXformStack():
                    continue
                key = _hold(_transform_order_spec(part), layers)
                if key in part_matrices and not _matrices_close(part_matrices[key], matrix):
                    msg = (
                        f"{root_file.name}'s root prim moves differently per variant "
                        f"while {part.GetPath()} is shared by them, so no single frozen "
                        f"transform fits it. Nothing was changed. Freeze the transforms "
                        f"in your DCC and re-export."
                    )
                    raise ValueError(msg)
                part_matrices[key] = matrix

    _require_inside(layers.values(), root_file.parent)
    for identifier, path in root_specs:
        _clear_root_transform(layers[identifier].GetPrimAtPath(path))
    for (identifier, path), matrix in part_matrices.items():
        if not _matrix_is_identity(matrix):
            _prepend_matrix(layers[identifier].GetPrimAtPath(path), matrix)

    moved = _moved_prims(root_file, combinations, before)
    if moved:
        for layer in layers.values():
            layer.Reload(force=True)
        msg = (
            f"Couldn't move {root_file.name}'s root transform onto its parts without "
            f"moving {len(moved)} prim(s) (e.g. {', '.join(moved[:3])}), so nothing was "
            f"changed. Freeze the transforms in your DCC and re-export."
        )
        raise ValueError(msg)
    for layer in layers.values():
        if layer.dirty:
            layer.Save()
    return True


def root_transform_is_identity(usd_file: Path) -> bool:
    """Return True if the file's defaultPrim composes an identity transform, in every variant."""
    return all(_matrix_is_identity(matrix) for matrix, _ in _file_root_transforms(usd_file))


def root_transform_is_animated(usd_file: Path) -> bool:
    """Return True if the file's defaultPrim has a time-varying transform, in any variant."""
    return any(animated for _, animated in _file_root_transforms(usd_file))


def _file_root_transforms(usd_file: Path) -> list[tuple[Gf.Matrix4d, bool]]:
    """The defaultPrim's local transform and whether it's animated, per variant combination.

    With too many combinations to try, only the authored selection is read.
    """
    stage = Usd.Stage.Open(str(usd_file))
    root = _xformable_root(stage)
    if root is None:
        return []
    return _root_transforms(stage, root, _variant_combinations(root) or [{}])


def _xformable_root(stage: Usd.Stage | None) -> Usd.Prim | None:
    """The stage's defaultPrim when it's transformable, else ``None``."""
    root = stage.GetDefaultPrim() if stage is not None else None
    if root is None or not root.IsValid() or not root.IsA(UsdGeom.Xformable):
        return None
    return root


def _root_transforms(
    stage: Usd.Stage, root: Usd.Prim, combinations: list[dict[str, str]],
) -> list[tuple[Gf.Matrix4d, bool]]:
    """*root*'s local transform and whether it's animated, for each variant combination."""
    xformable = UsdGeom.Xformable(root)
    transforms = []
    for combination in combinations:
        with _selected(stage, root, combination):
            transforms.append(
                (xformable.GetLocalTransformation(), xformable.TransformMightBeTimeVarying()),
            )
    return transforms


def _animated_message(usd_file: Path) -> str:
    return (
        f"{usd_file.name}: the root prim's transform is animated, so it can't be "
        f"moved onto the parts. Re-export with a static root."
    )


def _variant_combinations(root: Usd.Prim) -> list[dict[str, str]] | None:
    """Every combination of the root's variant selections; ``None`` when there are too many."""
    sets = root.GetVariantSets()
    choices = [
        [(name, variant) for variant in sets.GetVariantSet(name).GetVariantNames()]
        for name in sets.GetNames()
    ]
    choices = [options for options in choices if options]
    count = 1
    for options in choices:
        count *= len(options)
    if count > FreezeRules.MAX_VARIANT_COMBINATIONS:
        return None
    return [dict(combination) for combination in itertools.product(*choices)]


@contextmanager
def _selected(stage: Usd.Stage, root: Usd.Prim, combination: dict[str, str]) -> Iterator[None]:
    """Compose *combination* through the session layer, so no file records it."""
    session = stage.GetSessionLayer()
    with Usd.EditContext(stage, session):
        for name, variant in combination.items():
            root.GetVariantSet(name).SetVariantSelection(variant)
    try:
        yield
    finally:
        session.Clear()


def _world_transforms(root: Usd.Prim) -> dict[Sdf.Path, Gf.Matrix4d]:
    """World transform of every transformable prim below *root*, instance proxies included."""
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    predicate = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)
    return {
        prim.GetPath(): cache.GetLocalToWorldTransform(prim)
        for prim in Usd.PrimRange(root, predicate)
        if prim != root and prim.IsA(UsdGeom.Xformable)
    }


def _hold(spec: Sdf.PrimSpec, layers: dict[str, Sdf.Layer]) -> tuple[str, Sdf.Path]:
    """Keep *spec*'s layer alive in *layers* (``spec.layer`` is a weak handle); return its key."""
    identifier = spec.layer.identifier
    layers.setdefault(identifier, Sdf.Layer.FindOrOpen(identifier))
    return identifier, spec.path


def _transform_order_spec(part: Usd.Prim) -> Sdf.PrimSpec:
    """The spec that decides *part*'s op order: the strongest one authoring it, else its def."""
    order = part.GetAttribute("xformOpOrder")
    if order:
        for prop in order.GetPropertyStack(Usd.TimeCode.Default()):
            if prop.HasDefaultValue():
                return prop.owner
    stack = part.GetPrimStack()
    defining = [spec for spec in stack if spec.specifier == Sdf.SpecifierDef]
    return (defining or stack)[-1]


def _require_inside(layers: Iterable[Sdf.Layer], asset_dir: Path) -> None:
    """Refuse to edit a file outside the asset folder (or one that isn't a file)."""
    folder = asset_dir.resolve()
    for layer in layers:
        path = Path(layer.realPath).resolve() if layer.realPath else None
        if path is None or not path.is_relative_to(folder):
            msg = (
                f"Freezing {asset_dir.name} would edit {layer.identifier}, which is "
                f"outside the asset folder. Freeze the transforms in your DCC and re-export."
            )
            raise ValueError(msg)


def _clear_root_transform(spec: Sdf.PrimSpec) -> None:
    """Remove the root's own transform opinions, and its extentsHint that no longer fits."""
    for name in list(spec.properties.keys()):
        if name.startswith("xformOp:") or name in ("xformOpOrder", "extentsHint"):
            spec.RemoveProperty(spec.properties[name])


def _prepend_matrix(spec: Sdf.PrimSpec, matrix: Gf.Matrix4d) -> None:
    """Put *matrix* in front of the part's op order (outermost), merging an earlier freeze."""
    name = f"xformOp:transform:{FreezeRules.OP_SUFFIX}"
    order_spec = spec.attributes.get("xformOpOrder")
    order = list(order_spec.default) if order_spec is not None and order_spec.default else []
    if UsdGeom.XformOpTypes.resetXformStack in order:
        return
    frozen = spec.attributes.get(name)
    if order and order[0] == name and frozen is not None:
        frozen.default = frozen.default * matrix
        return
    if frozen is None:
        frozen = Sdf.AttributeSpec(spec, name, Sdf.ValueTypeNames.Matrix4d)
    frozen.default = matrix
    if order_spec is None:
        order_spec = Sdf.AttributeSpec(
            spec, "xformOpOrder", Sdf.ValueTypeNames.TokenArray, Sdf.VariabilityUniform,
        )
    order_spec.default = [name, *(op for op in order if op != name)]


def _moved_prims(
    root_file: Path,
    combinations: list[dict[str, str]],
    before: list[dict[Sdf.Path, Gf.Matrix4d]],
) -> list[str]:
    """Paths of the prims whose world transform changed, in any variant combination."""
    stage = Usd.Stage.Open(str(root_file))
    root = stage.GetDefaultPrim()
    moved: list[str] = []
    for combination, expected in zip(combinations, before, strict=True):
        with _selected(stage, root, combination):
            after = _world_transforms(root)
        for path, matrix in expected.items():
            if path not in after or not _matrices_close(after[path], matrix):
                moved.append(str(path))
    return sorted(set(moved))


def _matrices_close(a: Gf.Matrix4d, b: Gf.Matrix4d) -> bool:
    return all(
        abs(a[i, j] - b[i, j]) <= 1e-6 * max(1.0, abs(a[i, j]), abs(b[i, j]))
        for i in range(4) for j in range(4)
    )


def _matrix_is_identity(matrix: Gf.Matrix4d, epsilon: float = 1e-5) -> bool:
    """Return True if *matrix* is the identity matrix within *epsilon*."""
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            if abs(matrix[i, j] - expected) > epsilon:
                return False
    return True
