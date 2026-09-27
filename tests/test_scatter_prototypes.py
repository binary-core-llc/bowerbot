# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""A scatter's prototypes: removing one takes its pieces, and the scatter stays consistent."""

import asyncio
import hashlib
import tempfile
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, Vt

from tests._helpers import exec_tool, library_state
from tests._usd_audit import audit_project, problems

SCATTER = "/Scene/Nature/Mix"
STONE = f"{SCATTER}/Prototypes/stone"
CRATE = f"{SCATTER}/Prototypes/crate"


def _run(state, tool, **params):
    return asyncio.run(exec_tool(state, tool, params))


def _mixed_scatter(state) -> str:
    ground = _run(state, "place_asset", asset="ground", asset_name="Ground",
                  group="Architecture", translate_x=0.0, translate_y=0.0,
                  translate_z=0.0).data["prim_path"]
    r = _run(state, "scatter_on_surface", name="Mix", group="Nature",
             assets=[{"asset": "stone"}, {"asset": "crate"}], surfaces=[ground], count=12,
             seed=4)
    assert r.success, r.error
    return ground


def _pieces(state, proto: str | None = None) -> list[tuple[float, ...]]:
    """World bounds of the scatter's pieces (of one prototype), sorted."""
    stage = state.require_stage()
    instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(SCATTER))
    targets = instancer.GetPrototypesRel().GetTargets()
    indices = list(instancer.GetProtoIndicesAttr().Get())
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default"])
    boxes = cache.ComputePointInstanceWorldBounds(instancer, list(range(len(indices))))
    return sorted(
        tuple(round(v, 5) for r in (box.ComputeAlignedRange(),) for v in (*r.GetMin(), *r.GetMax()))
        for box, index in zip(boxes, indices, strict=True)
        if proto is None or targets[index] == Sdf.Path(proto)
    )


def _files(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)): hashlib.sha1(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def test_removing_a_prototype_takes_its_pieces_and_keeps_the_others_in_place():
    """The crates stay exactly where they were; hidden pieces and per-piece colors follow."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _mixed_scatter(state)
        stage = state.require_stage()
        instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(SCATTER))
        indices = list(instancer.GetProtoIndicesAttr().Get())
        crate_index = [str(t) for t in instancer.GetPrototypesRel().GetTargets()].index(CRATE)
        crate_slots = [i for i, p in enumerate(indices) if p == crate_index]
        stone_slots = [i for i, p in enumerate(indices) if p != crate_index]
        assert crate_slots and stone_slots
        # A hidden crate and a hidden stone, and a per-piece color that marks the crates.
        instancer.GetInvisibleIdsAttr().Set([crate_slots[0], stone_slots[0]])
        colors = [(1.0, 0.0, 0.0) if p == crate_index else (0.0, 0.0, 1.0) for p in indices]
        UsdGeom.PrimvarsAPI(instancer).CreatePrimvar(
            "displayColor", Sdf.ValueTypeNames.Color3fArray, UsdGeom.Tokens.vertex,
        ).Set(Vt.Vec3fArray(colors))
        stage.GetRootLayer().Save()
        crates = _pieces(state, CRATE)

        r = _run(state, "remove_prim", prim_path=STONE)
        assert r.success, r.error
        assert f"{len(stone_slots)} piece(s)" in r.data["message"]

        stage = state.require_stage()
        instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(SCATTER))
        assert [str(t) for t in instancer.GetPrototypesRel().GetTargets()] == [CRATE]
        assert list(instancer.GetProtoIndicesAttr().Get()) == [0] * len(crate_slots)
        assert _pieces(state) == crates
        assert list(instancer.GetInvisibleIdsAttr().Get()) == [0]
        color = UsdGeom.PrimvarsAPI(instancer).GetPrimvar("displayColor").Get()
        assert [tuple(c) for c in color] == [(1.0, 0.0, 0.0)] * len(crate_slots)
        assert not stage.GetPrimAtPath(STONE)
        assert _run(state, "validate_scene").data["error_count"] == 0
        assert problems(audit_project(state.require_project().path)) == []


def test_removing_the_last_prototype_removes_the_scatter():
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _mixed_scatter(state)
        assert _run(state, "remove_prim", prim_path=STONE).success
        r = _run(state, "remove_prim", prim_path=CRATE)
        assert r.success, r.error
        assert "only prototype" in r.data["message"]
        assert not state.require_stage().GetPrimAtPath(SCATTER)
        assert problems(audit_project(state.require_project().path)) == []


def test_a_prototype_is_moved_only_with_its_scatter():
    """Moving, dropping, nesting into or re-parenting a prototype, or removing the prototype
    scope, is refused and changes nothing; renaming it in place works."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _mixed_scatter(state)
        project = state.require_project().path
        refused = [
            ("remove_prim", {"prim_path": f"{SCATTER}/Prototypes"}),
            ("move_asset", {"prim_path": STONE, "translate_x": 1.0}),
            ("drop_to_surface", {"prim_paths": [STONE]}),
            ("place_asset_inside", {"asset": "crate", "asset_name": "Box",
                                    "container_prim_path": STONE, "group": "Props",
                                    "translate_x": 0.0, "translate_y": 0.0,
                                    "translate_z": 0.0}),
            ("rename_prim", {"old_path": STONE, "new_path": "/Scene/Props/stone"}),
            ("rename_prim", {"old_path": f"{SCATTER}/Prototypes",
                             "new_path": "/Scene/Nature/Protos"}),
        ]
        for tool, params in refused:
            files = _files(project)
            r = _run(state, tool, **params)
            assert not r.success, f"{tool} was accepted"
            assert _files(project) == files, f"{tool} changed files"

        before = _pieces(state)
        r = _run(state, "rename_prim", old_path=STONE, new_path=f"{SCATTER}/Prototypes/pebble")
        assert r.success, r.error
        r = _run(state, "rename_prim", old_path=f"{SCATTER}/Prototypes",
                 new_path=f"{SCATTER}/Protos")
        assert r.success, r.error
        assert _pieces(state) == before
        assert problems(audit_project(project)) == []

        # The scatter itself moves with its prototypes.
        r = _run(state, "rename_prim", old_path=SCATTER, new_path="/Scene/Rocks/Mix")
        assert r.success, r.error
        instancer = UsdGeom.PointInstancer(state.require_stage().GetPrimAtPath("/Scene/Rocks/Mix"))
        assert [str(t) for t in instancer.GetPrototypesRel().GetTargets()] == [
            "/Scene/Rocks/Mix/Protos/pebble", "/Scene/Rocks/Mix/Protos/crate",
        ]
        assert problems(audit_project(project)) == []


def test_validate_scene_reports_a_broken_instancer():
    """An index past the prototypes, a short array and a missing prototype are errors."""
    with tempfile.TemporaryDirectory() as tmp:
        state = library_state(Path(tmp))
        _mixed_scatter(state)
        stage = state.require_stage()
        instancer = UsdGeom.PointInstancer(stage.GetPrimAtPath(SCATTER))
        count = len(instancer.GetProtoIndicesAttr().Get())
        instancer.GetProtoIndicesAttr().Set([5] + [0] * (count - 1))
        instancer.GetScalesAttr().Set(instancer.GetScalesAttr().Get()[:-1])
        instancer.GetPrototypesRel().AddTarget("/Scene/Nature/Mix/Prototypes/gone")
        stage.GetRootLayer().Save()

        messages = [i["message"] for i in _run(state, "validate_scene").data["issues"]
                    if i["severity"] == "error"]
        assert any("protoIndices" in m for m in messages), messages
        assert any("scales has" in m for m in messages), messages
        assert any("does not exist" in m for m in messages), messages
        codes = {i.code for i in problems(audit_project(state.require_project().path))}
        assert {"instancer-bad-index", "instancer-array-length"} <= codes

        # BowerBot won't edit an inconsistent scatter: removing a prototype is refused.
        before = state.require_project().scene_path.read_text()
        r = _run(state, "remove_prim", prim_path=STONE)
        assert not r.success
        assert "inconsistent" in r.error
        assert state.require_project().scene_path.read_text() == before
