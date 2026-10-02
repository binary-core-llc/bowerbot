# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Run a golden scenario through the dispatcher and write a readable snapshot per step.

Each snapshot starts with a plain-language summary, then the evidence:

SUMMARY
- the call, and BowerBot's answer in one line;
- what changed: files added, changed or removed; prims that appeared or went;
  every composed value that changed (``old → new``): type, specifier,
  activation, kind, instancing, applied APIs, variant selections, attribute
  values and connections, relationship targets, world position, bounds, the
  material a part shows; stage metadata; validity and its issues;
- what USD printed while the tool ran;
- the project's state: files nothing uses, dangling targets, absolute paths;
- checks: ``⚠`` flags for anything that looks wrong (see ``checks.py``).

EVIDENCE
- the full answer; the file tree (``+`` new, ``~`` changed, ``-`` removed);
  each file's change as a diff (a new file in full); the composed scene's
  change as a diff of the flattened stage; every prim's world placement;
  the validator's findings.

The project is read from a fresh copy on disk after every step, so an edit
that was never saved cannot hide. A snapshot is the same on every machine and
every run:

- temp paths and timestamps are replaced by placeholders;
- numbers are shown to 9 decimals, and float noise below that as 0, because
  the last digits of a computed value can differ between CPUs;
- the size of a listed file that stores absolute paths is replaced by a note,
  because it depends on the length of the test's temp path;
- folders are listed in sorted order while recording, because the disk's own
  order differs between machines. ``test_golden_output`` also records every
  scenario with folders listed in reverse, which shows whether BowerBot's
  output depends on that order.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from string import Template
from typing import Any

from pxr import Sdf
from pxr import Usd
from pxr import UsdGeom
from pxr import UsdShade
from pxr import UsdUtils
from pxr import Vt

from bowerbot import dispatcher
from bowerbot import scene_state
from bowerbot import skills
from bowerbot.utils import validation
from tests.golden import checks
from tests.golden import library
from tests.golden import model

PROJECT_NAME = "golden"
CRASH_MARK = "CRASHED (the exception escaped the dispatcher):"
STAGE_KEY = "(stage)"
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?")
# A memory address USD prints in its warnings, different on every run.
_ADDRESS = re.compile(r"<0x[0-9a-fA-F]+>")
# A decimal or exponent number standing alone (not part of a name, hash or version).
_NUMBER = re.compile(
    r"(?<![\w.])-?(?:\d+\.\d+(?:[eE][-+]?\d+)?|\d+[eE][-+]?\d+)(?![\w.])",
)
_DECIMALS = 9
_PATH_DEPENDENT_SIZE = "<depends on the test's temp path: the file stores absolute paths>"
_TEXT_SUFFIXES = {".usda", ".json", ".txt", ".md", ".mtlx"}
_USD_SUFFIXES = {".usd", ".usda", ".usdc"}
_USD_BINARY_SUFFIXES = {".usd", ".usdc"}
_LIST_LIMIT = 8
_POSITION_KEYS = ("world position", "bounds")
# A material's shaders and node graphs are its internals: listed as a count under it.
_FOLDED_TYPES = frozenset({"Material", "Shader", "NodeGraph"})


@dataclass(frozen=True)
class StepRecord:
    """One step's snapshot: the file it is stored in and its text."""

    file_name: str
    text: str


@dataclass
class _Capture:
    """What the project held after a step."""

    project: str = ""
    files: dict[str, str] = field(default_factory=dict)
    composed: str = ""
    facts: dict[str, dict[str, str]] = field(default_factory=dict)
    world: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    valid: bool | None = None
    composition_errors: list[str] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)
    dangling: list[str] = field(default_factory=list)
    unbound_materials: list[str] = field(default_factory=list)
    absolute_paths: list[str] = field(default_factory=list)


class _Normalizer:
    """Replaces this run's temp paths, timestamps and memory addresses with placeholders."""

    def __init__(self, workdir: Path, library: Path, projects: Path) -> None:
        pairs: list[tuple[str, str]] = []
        for path, label in (
            (projects / PROJECT_NAME, "<PROJECT>"),
            (projects, "<PROJECTS>"),
            (library, "<LIBRARY>"),
            (workdir, "<TMP>"),
        ):
            for spelling in {str(path), str(path.resolve())}:
                pairs.append((spelling, label))
        self._pairs = sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)
        self.snapshot_roots: list[tuple[str, str]] = []

    def __call__(self, text: str) -> str:
        for spelling, label in [*self.snapshot_roots, *self._pairs]:
            text = text.replace(spelling, label)
        return _ADDRESS.sub("<ADDRESS>", _TIME.sub("<TIME>", text))

    def has_temp_path(self, text: str) -> bool:
        return any(spelling in text for spelling, _ in self._pairs)


class _OrderedScan:
    """An ``os.scandir`` result in a fixed order, usable as a context manager."""

    def __init__(self, entries: list[os.DirEntry[str]]) -> None:
        self._entries = iter(entries)

    def __iter__(self) -> Iterator[os.DirEntry[str]]:
        return self._entries

    def __next__(self) -> os.DirEntry[str]:
        return next(self._entries)

    def __enter__(self) -> _OrderedScan:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def close(self) -> None:
        return None


@contextmanager
def listing_order(*, reverse: bool) -> Iterator[None]:
    """List every folder in sorted order (or reversed) instead of the disk's order."""
    listdir, scandir = os.listdir, os.scandir

    def ordered_listdir(path: Any = ".") -> list[Any]:
        return sorted(listdir(path), reverse=reverse)

    def ordered_scandir(path: Any = ".") -> _OrderedScan:
        with scandir(path) as entries:
            return _OrderedScan(sorted(entries, key=lambda entry: entry.name, reverse=reverse))

    os.listdir, os.scandir = ordered_listdir, ordered_scandir  # type: ignore[assignment]
    try:
        yield
    finally:
        os.listdir, os.scandir = listdir, scandir


def record(
    scenario: model.Scenario,
    convention: model.Convention,
    workdir: Path,
    *,
    reverse_listings: bool = False,
) -> list[StepRecord]:
    """Run *scenario* in *convention* under *workdir*; return one snapshot per step.

    Unless the scenario starts with no project, step 0 is ``create_project``,
    so the project's creation is recorded too. Folders are listed in sorted
    order, or in reverse with *reverse_listings*.
    """
    with listing_order(reverse=reverse_listings):
        return _record(scenario, convention, workdir)


def _record(
    scenario: model.Scenario, convention: model.Convention, workdir: Path,
) -> list[StepRecord]:
    library_dir = library.build_library(workdir / "library")
    projects = workdir / "projects"
    normalize = _Normalizer(workdir, library_dir, projects)
    state = scene_state.SceneState(
        library_dir=library_dir if scenario.library else None, projects_dir=projects,
    )
    saved: dict[str, str] = {"lib": str(library_dir)}
    opening = (
        model.Step(
            "create_project",
            {"name": PROJECT_NAME, "up_axis": convention.up_axis,
             "meters_per_unit": convention.meters_per_unit},
            note=(
                f"a new {convention.up_axis}-up project, "
                f"{convention.meters_per_unit} meters per unit"
            ),
        ),
    ) if scenario.open_project else ()
    steps = (*opening, *scenario.steps)
    library_before = _tree_hash(library_dir)
    previous = _Capture()
    records: list[StepRecord] = []
    for index, step in enumerate(steps):
        params = _resolve(step.params, saved, convention)
        result, printed = _run(state, step.tool, params)
        if step.save and result.success and result.data is not None:
            saved[step.save] = str(result.data[step.save_key])
        copy = workdir / f"snapshot_{index:02d}"
        current = state.project.path if state.project is not None else None
        units = model.Convention("current", state.up_axis.value, state.meters_per_unit)
        capture = _capture(current, copy, units, normalize)
        library_after = _tree_hash(library_dir)
        text = _render(
            index, step, params, result, [normalize(line) for line in printed],
            previous, capture, library_before != library_after, normalize,
        )
        library_before = library_after
        records.append(StepRecord(f"{index:02d}_{step.tool}.txt", text))
        previous = capture
    return records


# ── Running a step ──


def _run(
    state: scene_state.SceneState, tool: str, params: dict[str, Any],
) -> tuple[skills.ToolResult, list[str]]:
    """Call *tool* through the dispatcher; return its result and what USD printed meanwhile.

    An exception that escapes the dispatcher is recorded as a crash, not raised.

    USD writes its warnings to the process's stderr from C++, so the file
    descriptor itself is redirected for the duration of the call.
    """
    sys.stderr.flush()
    saved_fd = os.dup(2)
    with tempfile.TemporaryFile(mode="w+b") as sink:
        os.dup2(sink.fileno(), 2)
        try:
            result = asyncio.run(dispatcher.execute(state, tool, params))
        except Exception as exc:  # noqa: BLE001 - a crash is an outcome to record
            result = skills.ToolResult(
                success=False, error=f"{CRASH_MARK} {type(exc).__name__}: {exc}",
            )
        finally:
            sys.stderr.flush()
            os.dup2(saved_fd, 2)
            os.close(saved_fd)
        sink.seek(0)
        printed = sink.read().decode("utf-8", errors="replace")
    lines = [line.rstrip() for line in printed.splitlines() if line.strip()]
    return result, lines


def _resolve(
    value: Any, saved: dict[str, str], convention: model.Convention, *, top: bool = True,
) -> Any:
    """Turn a step's params into what is sent: names filled in, points and lengths converted.

    Only a top-level ``translate`` point becomes ``translate_x/y/z``; a nested
    one (a layout transform's) stays a point, sent as ``[x, y, z]``.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if top and key == "translate" and isinstance(item, model.Point):
                x, y, z = model.in_convention(item, convention)
                out.update(translate_x=x, translate_y=y, translate_z=z)
            else:
                out[Template(key).safe_substitute(saved)] = _resolve(
                    item, saved, convention, top=False,
                )
        return out
    if isinstance(value, list | tuple):
        return [_resolve(item, saved, convention, top=False) for item in value]
    if isinstance(value, model.Point):
        return list(model.in_convention(value, convention))
    if isinstance(value, model.Meters):
        return round(value.value / convention.meters_per_unit, 9) + 0.0
    if isinstance(value, str):
        return Template(value).safe_substitute(saved)
    return value


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


# ── Capture ──


def _capture(
    project: Path | None, copy: Path, convention: model.Convention, normalize: _Normalizer,
) -> _Capture:
    """Read the current project as it is on disk, through a fresh copy."""
    if project is None or not project.is_dir():
        return _Capture()
    shutil.copytree(project, copy)
    normalize.snapshot_roots = [
        (spelling, "<PROJECT>") for spelling in {str(copy), str(copy.resolve())}
    ]
    capture = _Capture(project=project.name)
    capture.files = {
        path.relative_to(copy).as_posix(): normalize(_file_text(path))
        for path in sorted(copy.rglob("*")) if path.is_file()
    }
    capture.absolute_paths = _absolute_paths(copy, normalize)
    scene = copy / "scene.usda"
    stage = Usd.Stage.Open(str(scene)) if scene.is_file() else None
    if stage is None:
        return capture
    capture.composed = normalize(stage.Flatten().ExportToString())
    capture.facts = _facts(stage, normalize)
    capture.world = _world(stage, normalize)
    capture.composition_errors = sorted(
        normalize(str(error)) for error in stage.GetCompositionErrors()
    )
    capture.dangling = _dangling(capture.facts)
    capture.unbound_materials = _unbound_materials(capture.facts, capture.files)
    capture.unused = _unused(copy)
    result = validation.stage.validate(
        scene,
        expected_meters_per_unit=convention.meters_per_unit,
        expected_up_axis=convention.up_axis,
    )
    capture.valid = result.is_valid
    # The validator lists issues in a different order from run to run; the order
    # means nothing, so they are sorted to keep the snapshot stable.
    capture.issues = sorted(
        normalize(f"[{issue.severity.value}] {issue.prim_path or '-'}: {issue.message}")
        for issue in result.issues
    )
    return capture


def _file_text(path: Path) -> str:
    """A file's content as text: USD text, JSON text, or a size and hash for binary data."""
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix in _USD_BINARY_SUFFIXES:
        layer = Sdf.Layer.FindOrOpen(str(path))
        return layer.ExportToString() if layer else "<layer does not open>"
    if suffix == ".usdz":
        with zipfile.ZipFile(path) as package:
            return "\n".join(
                f"{info.filename}  {info.file_size} bytes  "
                f"sha256:{hashlib.sha256(package.read(info)).hexdigest()[:16]}"
                for info in package.infolist()
            ) + "\n"
    data = path.read_bytes()
    return f"<binary: {len(data)} bytes, sha256:{hashlib.sha256(data).hexdigest()[:16]}>\n"


def _fmt(value: Any) -> str:
    """A composed value as short, stable text."""
    if value is None:
        return "(no value)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        text = f"{value:.6g}"
        return "0" if text == "-0" else text
    if isinstance(value, int | str):
        return repr(value) if isinstance(value, str) else str(value)
    if isinstance(value, Sdf.AssetPath):
        return f"@{value.path}@"
    if isinstance(value, Sdf.Path):
        return f"<{value}>"
    if hasattr(value, "__len__") and hasattr(value, "__getitem__"):
        items = list(value)
        if isinstance(value, Vt.Vec3fArray | Vt.Vec3dArray | Vt.FloatArray | Vt.DoubleArray
                      | Vt.IntArray | Vt.QuatfArray | Vt.QuathArray | Vt.Vec2fArray
                      | Vt.TokenArray | Vt.StringArray) and len(items) > _LIST_LIMIT:
            digest = hashlib.sha256(repr(items).encode()).hexdigest()[:12]
            return f"<{len(items)} items, sha256:{digest}>"
        return "(" + ", ".join(_fmt(item) for item in items) + ")"
    return str(value)


def _num(value: float) -> str:
    text = f"{value:.4f}"
    return "0.0000" if text == "-0.0000" else text


def _vec(values: Any) -> str:
    return "(" + ", ".join(_num(v) for v in values) + ")"


def _bbox_cache() -> UsdGeom.BBoxCache:
    return UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render],
    )


def _facts(stage: Usd.Stage, normalize: _Normalizer) -> dict[str, dict[str, str]]:
    """Every composed fact about every prim (and the stage), as text keyed by prim path."""
    facts: dict[str, dict[str, str]] = {}
    root_layer = stage.GetRootLayer()
    facts[STAGE_KEY] = {
        "upAxis": str(UsdGeom.GetStageUpAxis(stage)),
        "metersPerUnit": _fmt(UsdGeom.GetStageMetersPerUnit(stage)),
        "defaultPrim": (
            str(stage.GetDefaultPrim().GetPath()) if stage.GetDefaultPrim() else "(none)"
        ),
        "sublayers": _fmt(list(root_layer.subLayerPaths)) if root_layer.subLayerPaths else "(none)",
    }
    cache = _bbox_cache()
    predicate = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), predicate):
        if prim.IsPseudoRoot():
            continue
        info: dict[str, str] = {"type": prim.GetTypeName() or "typeless"}
        specifier = prim.GetSpecifier()
        if specifier != Sdf.SpecifierDef:
            info["specifier"] = str(specifier).rsplit(".", 1)[-1].lower().replace("specifier", "")
        if not prim.IsActive():
            info["active"] = "false"
        kind = Usd.ModelAPI(prim).GetKind()
        if kind:
            info["kind"] = kind
        if prim.IsInstanceable():
            info["instanceable"] = "true"
        if prim.IsInstanceProxy():
            info["instance proxy"] = "true"
        applied = prim.GetAppliedSchemas()
        if applied:
            info["applied APIs"] = ", ".join(applied)
        variant_sets = prim.GetVariantSets()
        for set_name in variant_sets.GetNames():
            variant_set = variant_sets.GetVariantSet(set_name)
            info[f"variant set {set_name}"] = (
                f"{variant_set.GetVariantSelection() or '(none)'} of "
                f"{', '.join(variant_set.GetVariantNames())}"
            )
        for attr in prim.GetAuthoredAttributes():
            key = f"attr {attr.GetName()}"
            info[key] = _fmt(attr.Get(Usd.TimeCode.Default()))
            if attr.GetNumTimeSamples():
                info[key] += f"  (+{attr.GetNumTimeSamples()} time samples)"
            connections = attr.GetConnections()
            if connections:
                info[f"connect {attr.GetName()}"] = ", ".join(str(c) for c in connections)
        for rel in prim.GetAuthoredRelationships():
            targets = rel.GetTargets()
            info[f"rel {rel.GetName()}"] = ", ".join(str(t) for t in targets) or "(no targets)"
        if prim.IsA(UsdGeom.Xformable):
            world = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            info["world position"] = _vec(world.ExtractTranslation())
        if prim.IsA(UsdGeom.Imageable) and (
            prim.IsA(UsdGeom.Boundable) or Usd.ModelAPI(prim).GetKind()
        ):
            box = cache.ComputeWorldBound(prim).ComputeAlignedRange()
            if not box.IsEmpty():
                info["bounds"] = f"{_vec(box.GetMin())}..{_vec(box.GetMax())}"
        if prim.IsA(UsdGeom.Gprim) or prim.IsA(UsdGeom.Subset):
            material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
            info["material shown"] = str(material.GetPath()) if material else "(none)"
        facts[str(prim.GetPath())] = {key: normalize(value) for key, value in info.items()}
    return facts


def _world(stage: Usd.Stage, normalize: _Normalizer) -> list[str]:
    cache = _bbox_cache()
    lines = []
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        if prim.IsPseudoRoot() or not prim.IsA(UsdGeom.Imageable):
            continue
        line = f"  {prim.GetPath()}  [{prim.GetTypeName() or 'typeless'}]"
        if prim.IsA(UsdGeom.Xformable):
            world = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            line += f"  at {_vec(world.ExtractTranslation())}"
        box = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if not box.IsEmpty():
            line += f"  bounds {_vec(box.GetMin())}..{_vec(box.GetMax())}"
        if prim.IsA(UsdGeom.Gprim):
            material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
            line += f"  material {material.GetPath() if material else '(none)'}"
        lines.append(normalize(line))
    return lines or ["  (empty scene)"]


def _dangling(facts: dict[str, dict[str, str]]) -> list[str]:
    """Relationship targets and connections naming a prim the scene does not have."""
    found = []
    for path, info in facts.items():
        for key, value in info.items():
            if not key.startswith(("rel ", "connect ")) or value == "(no targets)":
                continue
            for target in value.split(", "):
                prim_path = target.split(".", 1)[0]
                if prim_path.startswith("/") and prim_path not in facts:
                    found.append(f"{path} {key} -> {target}")
    return sorted(found)


_BINDING_TARGET = re.compile(r"material:binding[\w:]*\s*=\s*\[?\s*<([^>]+)>")


def _unbound_materials(facts: dict[str, dict[str, str]], files: dict[str, str]) -> list[str]:
    """Materials in the scene that no binding names: not the composed ones, and not one
    authored in any project file (a variant that is not selected counts as a use)."""
    bound = {
        target for info in facts.values() for key, value in info.items()
        if key.startswith("rel material:binding") for target in value.split(", ")
    }
    named_tails = {
        "/".join(target.rstrip("/").split("/")[-2:])
        for text in files.values() for target in _BINDING_TARGET.findall(text)
    }
    return sorted(
        path for path, info in facts.items()
        if info.get("type") == "Material" and path not in bound
        and "/".join(path.split("/")[-2:]) not in named_tails
    )


def _unused(copy: Path) -> list[str]:
    """Project files the scene does not use, by USD's own dependency walk (layers, arcs,
    and asset-valued attributes such as textures). Snapshots beside the scene are
    documents of their own, and so is a package written beside the scene."""
    layers, assets, _ = UsdUtils.ComputeAllDependencies(Sdf.AssetPath(str(copy / "scene.usda")))
    used = {Path(layer.realPath).resolve() for layer in layers if layer.realPath}
    used |= {Path(asset).resolve() for asset in assets}
    unused = []
    for path in sorted(copy.rglob("*")):
        if not path.is_file() or path.name == "project.json":
            continue
        if path.parent == copy:
            continue
        if path.resolve() not in used:
            unused.append(path.relative_to(copy).as_posix())
    return unused


def _absolute_paths(copy: Path, normalize: _Normalizer) -> list[str]:
    """Asset paths a project layer writes as absolute: they only resolve on this machine."""
    found = []
    for path in sorted(copy.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _USD_SUFFIXES:
            continue
        layer = Sdf.Layer.FindOrOpen(str(path))
        if layer is None:
            continue
        for asset_path in layer.GetExternalReferences():
            windows = re.match(r"^[A-Za-z]:[/\\]", asset_path or "")
            if asset_path and (os.path.isabs(asset_path) or windows):
                found.append(normalize(f"{path.relative_to(copy).as_posix()} -> {asset_path}"))
    return found


# ── Rendering ──


def _render(
    index: int,
    step: model.Step,
    params: dict[str, Any],
    result: skills.ToolResult,
    printed: list[str],
    previous: _Capture,
    capture: _Capture,
    library_changed: bool,
    normalize: _Normalizer,
) -> str:
    data = result.data if result.success and isinstance(result.data, dict) else {}
    files_changed = previous.files != capture.files
    scene_changed = previous.facts != capture.facts
    new_errors = [
        issue for issue in capture.issues
        if issue.startswith("[error]") and issue not in previous.issues
    ]
    facts = checks.StepFacts(
        tool=step.tool, params=params, ok=result.success,
        crashed=(result.error or "").startswith(CRASH_MARK), data=data,
        files_changed=files_changed, scene_changed=scene_changed,
        before=previous.facts, after=capture.facts,
        valid_before=previous.valid, valid_after=capture.valid, new_errors=new_errors,
    )
    flags = checks.run_checks(facts)
    if library_changed:
        flags.insert(0, "⚠ CRITICAL: the asset library changed on disk")
    flags += _answer_flags(data, capture.facts)
    # Files the scene stops using are not flagged: the project keeps its asset
    # copies and textures until delete_project_asset or delete_project_texture.
    # An unbound material is flagged only after a removal: binding another one
    # keeps the replaced material for variants, and an asset may ship a spare.
    leftovers = [
        ("a dangling target", previous.dangling, capture.dangling),
        ("an absolute path", previous.absolute_paths, capture.absolute_paths),
        ("a composition error", previous.composition_errors, capture.composition_errors),
    ]
    if step.tool.startswith(checks.REMOVING_PREFIXES):
        leftovers.append(
            ("a material nothing binds", previous.unbound_materials, capture.unbound_materials),
        )
    for label, before_items, after_items in leftovers:
        flags += [f"⚠ left behind {label}: {item}" for item in after_items
                  if item not in before_items]
    if printed:
        flags.append(
            f"⚠ USD printed {len(printed)} line(s) while the tool ran "
            f"(see EVIDENCE): {printed[0][:140]}",
        )

    lines = [f"=== step {index:02d}: {step.tool}"]
    if step.note:
        lines.append(f"intent: {step.note}")
    lines += [
        "",
        "SUMMARY",
        f"  call: {step.tool}({_call_args(params, normalize)})",
        f"  current project: {capture.project or '(none)'}"
        + (f" (was {previous.project})" if previous.project and previous.project != capture.project
           else ""),
        "  said: " + (
            f"ok: {normalize(str(data.get('message', '')))}".rstrip(": ") if result.success
            else f"REFUSED: {' '.join(normalize(result.error or '').split())}"
        ),
        "",
        "  what changed:",
    ]
    lines += _indent_lines(_changed_files(previous.files, capture.files), 4)
    lines += _indent_lines(_changed_facts(previous.facts, capture.facts), 4)
    lines += _indent_lines(_changed_validity(previous, capture), 4)
    if not files_changed and not scene_changed and previous.issues == capture.issues:
        lines.append("    nothing")
    lines += ["", "  project state after the step:"]
    state_lines = [
        *(f"not used by the scene: {name}" for name in capture.unused),
        *(f"dangling target: {item}" for item in capture.dangling),
        *(f"material nothing binds: {item}" for item in capture.unbound_materials),
        *(f"absolute path: {item}" for item in capture.absolute_paths),
        *(f"composition error: {item}" for item in capture.composition_errors),
    ]
    lines += _indent_lines(state_lines or [
        "clean: every file used, every material bound, no dangling targets, "
        "no absolute paths, no composition errors",
    ], 4)
    lines += ["", "  checks:"]
    lines += _indent_lines(flags or ["no problems spotted by the automatic checks"], 4)

    lines += ["", "EVIDENCE", "", "what USD printed while the tool ran:"]
    lines += [f"  {line}" for line in printed] or ["  (nothing)"]
    lines += ["", "full answer:"]
    answer = _path_dependent_sizes(data, normalize) if result.success else {"error": result.error}
    lines.append(_indent(normalize(_json(answer))))
    lines += ["", "files:"]
    lines += _file_tree(previous.files, capture.files)
    lines += ["", "file changes:"]
    lines += _file_changes(previous.files, capture.files)
    lines += ["", "composed scene changes:"]
    lines += _diff(previous.composed, capture.composed, "composed scene") or ["  (none)"]
    lines += ["", "world (position, bounds min..max, material shown):"]
    lines += capture.world or ["  (no scene)"]
    lines += ["", "validation:"]
    if capture.valid is None:
        lines.append("  (no scene)")
    elif not capture.issues:
        lines.append("  valid, no issues")
    else:
        lines.append(
            f"  {'valid' if capture.valid else 'INVALID'}, {len(capture.issues)} issue(s):",
        )
        lines += [f"  - {issue}" for issue in capture.issues]
    return _steady_numbers("\n".join(lines).rstrip() + "\n")


def _steady_numbers(text: str) -> str:
    """Show long numbers to 9 decimals, and float noise below that as 0."""

    def steady(match: re.Match[str]) -> str:
        literal = match.group(0)
        mantissa = literal.lower().split("e")[0]
        exponent = "e" in literal.lower()
        if not exponent and len(mantissa.partition(".")[2]) <= _DECIMALS:
            return literal
        value = float(literal)
        if exponent and abs(value) >= 1e15:
            return literal
        rounded = f"{round(value, _DECIMALS):.{_DECIMALS}f}".rstrip("0")
        if float(rounded) == 0:
            return "0" if exponent else "0.0"
        return rounded + "0" if rounded.endswith(".") else rounded

    return _NUMBER.sub(steady, text)


def _path_dependent_sizes(value: Any, normalize: _Normalizer) -> Any:
    """*value* with the size of any listed file that stores absolute paths replaced by a note."""
    if isinstance(value, list):
        return [_path_dependent_sizes(item, normalize) for item in value]
    if not isinstance(value, dict):
        return value
    out = {key: _path_dependent_sizes(item, normalize) for key, item in value.items()}
    path, size = value.get("path"), value.get("size_bytes")
    if isinstance(path, str) and isinstance(size, int) and Path(path).is_file():
        if normalize.has_temp_path(Path(path).read_bytes().decode("utf-8", errors="replace")):
            out["size_bytes"] = _PATH_DEPENDENT_SIZE
    return out


def _answer_flags(data: dict[str, Any], facts: dict[str, dict[str, str]]) -> list[str]:
    """Does the answer's reported position match where the prim really is?"""
    prim_path = data.get("prim_path")
    position = data.get("position")
    if not isinstance(prim_path, str) or not isinstance(position, dict) or prim_path not in facts:
        return []
    actual = facts[prim_path].get("world position")
    reported = _vec((position.get("x", 0.0), position.get("y", 0.0), position.get("z", 0.0)))
    if actual and actual != reported:
        return [f"⚠ the answer says {prim_path} is at {reported}, but it is at {actual}"]
    return []


def _call_args(params: dict[str, Any], normalize: _Normalizer) -> str:
    return normalize(", ".join(
        f"{key}={json.dumps(value, ensure_ascii=False, default=str)}"
        for key, value in params.items()
    ))


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str, ensure_ascii=False)


def _indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line if line else line for line in text.splitlines())


def _indent_lines(lines: list[str], width: int) -> list[str]:
    return [" " * width + line for line in lines]


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    lines = []
    for name in sorted(set(before) | set(after)):
        if name not in before:
            lines.append(f"+ file {name}")
        elif name not in after:
            lines.append(f"- file {name}")
        elif before[name] != after[name]:
            lines.append(f"~ file {name}")
    return lines


def _is_under(path: str, roots: set[str]) -> bool:
    return any(path.startswith(root + "/") for root in roots)


def _changed_facts(
    before: dict[str, dict[str, str]], after: dict[str, dict[str, str]],
) -> list[str]:
    """Prims that appeared or went, and every composed value that changed."""
    lines: list[str] = []
    old_stage, new_stage = before.get(STAGE_KEY, {}), after.get(STAGE_KEY, {})
    for key in sorted(old_stage.keys() | new_stage.keys()):
        if old_stage.get(key) != new_stage.get(key):
            lines.append(
                f"~ stage  {key}: {old_stage.get(key, '(none)')} → {new_stage.get(key, '(none)')}",
            )
    added = {path for path in after if path not in before and path != STAGE_KEY}
    removed = {path for path in before if path not in after and path != STAGE_KEY}
    for sign, paths, facts, word in (("+", added, after, "+"), ("-", removed, before, "and ")):
        folded = {path for path in paths if facts[path]["type"] in _FOLDED_TYPES}
        for path in sorted(paths):
            if _is_under(path, folded):
                continue
            inside = sum(1 for other in paths if other.startswith(path + "/"))
            extra = f" ({word}{inside} prims inside)" if path in folded and inside else ""
            lines.append(f"{sign} prim {path} [{facts[path]['type']}]{extra}")
            if sign == "+":
                lines += [
                    f"      {key}: {value}" for key, value in sorted(facts[path].items())
                    if key != "type"
                ]
    moved = {
        path for path in before.keys() & after.keys()
        if any(before[path].get(key) != after[path].get(key) for key in _POSITION_KEYS)
    }
    for path in sorted((before.keys() & after.keys()) - {STAGE_KEY}):
        old, new = before[path], after[path]
        for key in sorted(old.keys() | new.keys()):
            if old.get(key) == new.get(key):
                continue
            if key in _POSITION_KEYS and _is_under(path, moved):
                continue
            lines.append(f"~ {path}  {key}: {old.get(key, '(none)')} → {new.get(key, '(none)')}")
    return lines


def _changed_validity(previous: _Capture, capture: _Capture) -> list[str]:
    def label(valid: bool | None) -> str:
        return "no scene" if valid is None else "valid" if valid else "INVALID"

    lines = []
    if previous.valid != capture.valid:
        lines.append(f"~ validity: {label(previous.valid)} → {label(capture.valid)}")
    lines += [f"+ issue {issue}" for issue in capture.issues if issue not in previous.issues]
    lines += [f"- issue {issue}" for issue in previous.issues if issue not in capture.issues]
    return lines


def _file_tree(before: dict[str, str], after: dict[str, str]) -> list[str]:
    names = sorted(set(before) | set(after))
    if not names:
        return ["  (no project)"]
    lines = []
    for name in names:
        mark = (
            "+" if name not in before else "-" if name not in after
            else "~" if before[name] != after[name] else " "
        )
        lines.append(f"  {mark} {name}")
    return lines


def _file_changes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for name in sorted(set(before) | set(after)):
        if name not in before:
            lines += [f"  + {name} (new):", _indent(after[name], "      ")]
        elif name not in after:
            lines.append(f"  - {name} (removed)")
        elif before[name] != after[name]:
            lines += [f"  ~ {name}:", *_diff(before[name], after[name], name, prefix="      ")]
    return lines or ["  (none)"]


def _diff(before: str, after: str, name: str, prefix: str = "  ") -> list[str]:
    if before == after:
        return []
    diff = difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile=f"{name} (before)", tofile=f"{name} (after)", lineterm="", n=2,
    )
    return [prefix + line for line in diff]
