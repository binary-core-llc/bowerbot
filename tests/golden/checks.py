# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Automatic checks on each golden step: does the tool do what it says?

Each check reads the step (its call and answer) and the project before and
after, and returns ``⚠`` lines for what looks wrong. They flag, they don't
fail: the snapshot records them, and the reviewer decides.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

READ_ONLY_PREFIXES = ("list_", "search_", "get_", "compute_", "validate_")
REMOVING_PREFIXES = ("remove_", "delete_")
# Tools whose job may legitimately need no change: reopening, freezing what is
# already frozen, cleaning up when nothing is unused, dropping what already rests
# on the surface, packaging the same scene again.
MAY_CHANGE_NOTHING = frozenset({
    "create_stage", "freeze_asset", "cleanup_unused_contents", "cleanup_unused_materials",
    "open_project", "drop_to_surface", "package_scene",
})
# Words an answer uses to say there was nothing to do.
NOTHING_TO_DO = ("not found", "was not present", "has no ")


@dataclass(frozen=True)
class StepFacts:
    """Everything a check may look at for one step."""

    tool: str
    params: dict[str, Any]
    ok: bool
    crashed: bool
    data: dict[str, Any]
    files_changed: bool
    scene_changed: bool
    before: dict[str, dict[str, str]]
    after: dict[str, dict[str, str]]
    valid_before: bool | None
    valid_after: bool | None
    new_errors: list[str]


def _is_read_only(tool: str) -> bool:
    return tool.startswith(READ_ONLY_PREFIXES)


def _generic(step: StepFacts) -> list[str]:
    flags = []
    if step.crashed:
        flags.append("the tool crashed instead of answering")
    if not step.ok and (step.files_changed or step.scene_changed):
        flags.append("refused, but the project changed anyway")
    if step.ok and _is_read_only(step.tool) and step.files_changed:
        flags.append("a read-only tool changed files")
    message = str(step.data.get("message", "")).lower()
    said_nothing_to_do = step.data.get("removed") is False or any(
        words in message for words in NOTHING_TO_DO
    )
    if (
        step.ok and not _is_read_only(step.tool) and not step.files_changed
        and step.tool not in MAY_CHANGE_NOTHING and not step.tool.startswith("select_")
        and not step.params.get("validate_only") and not said_nothing_to_do
    ):
        flags.append("reported success, but no file changed")
    if step.valid_before is not False and step.valid_after is False:
        flags.append("this step made the scene invalid")
    elif step.new_errors:
        flags.append(f"this step added {len(step.new_errors)} validation error(s)")
    prim_path = step.data.get("prim_path") if step.ok else None
    if (
        isinstance(prim_path, str) and prim_path.startswith("/")
        and not step.tool.startswith(REMOVING_PREFIXES) and not _is_read_only(step.tool)
        and not step.params.get("validate_only") and prim_path not in step.after
    ):
        flags.append(f"the returned prim_path {prim_path} does not exist in the scene")
    return flags


def _shown_under(facts: dict[str, dict[str, str]], root: str) -> dict[str, str]:
    """The material each part at or under *root* shows."""
    return {
        path: prim["material shown"] for path, prim in facts.items()
        if "material shown" in prim and (path == root or path.startswith(root + "/"))
    }


def _material_added(step: StepFacts) -> list[str]:
    if not step.ok:
        return []
    target = step.params.get("prim_path", "")
    name = str(step.data.get("material", "")).rsplit("/", 1)[-1]
    if target not in step.after:
        return [f"the prim it bound, {target}, does not exist in the scene"]
    shown = _shown_under(step.after, target)
    if not shown:
        return [f"{target} has no geometry at or under it to show the material"]
    missing = sorted(path for path, material in shown.items() if not material.endswith("/" + name))
    if missing:
        return [f"{len(missing)} part(s) under {target} do not show {name}: {', '.join(missing)}"]
    return []


def _material_removed(step: StepFacts) -> list[str]:
    if not step.ok or step.data.get("removed") is False:
        return []
    target = step.params.get("prim_path", "")
    before = _shown_under(step.before, target)
    after = _shown_under(step.after, target)
    if not any(material != "(none)" for material in before.values()):
        return [f"{target} showed no material before, yet the answer says one was removed"]
    kept = sorted(path for path, material in after.items() if material != "(none)"
                  and material == before.get(path))
    if kept:
        return [f"still showing the same material after the removal: {', '.join(kept)}"]
    return []


_UNIT_RANGE_PARAMS = (
    "base_color_r", "base_color_g", "base_color_b", "metalness", "roughness", "opacity",
)


def _material_created(step: StepFacts) -> list[str]:
    flags = _material_added(step)
    outside = [
        f"{name}={step.params[name]}" for name in _UNIT_RANGE_PARAMS
        if isinstance(step.params.get(name), int | float) and not 0.0 <= step.params[name] <= 1.0
    ]
    if step.ok and outside:
        flags.append(f"accepted values outside 0-1: {', '.join(outside)}")
    return flags


def _variant_selected(step: StepFacts) -> list[str]:
    if not step.ok:
        return []
    target = step.params.get("prim_path", "")
    set_name = step.params.get("variant_set", "")
    wanted = step.params.get("variant_name", "")
    key = f"variant set {set_name}"
    found = {
        path: prim[key] for path, prim in step.after.items()
        if key in prim and (path == target or path.startswith(target + "/"))
    }
    if not found:
        return [f"no prim at or under {target} has a variant set named {set_name!r}"]
    if not any(value.startswith(f"{wanted} of ") for value in found.values()):
        return [f"{set_name!r} does not show {wanted!r}: " + "; ".join(
            f"{path} selects {value}" for path, value in sorted(found.items()))]
    return []


TOOL_CHECKS: dict[str, Callable[[StepFacts], list[str]]] = {
    "select_asset_variant": _variant_selected,
    "select_asset_variant_for_instance": _variant_selected,
    "select_scene_variant": _variant_selected,
    "create_material": _material_created,
    "bind_material": _material_added,
    "remove_material": _material_removed,
}


def run_checks(step: StepFacts) -> list[str]:
    """All ``⚠`` flags for *step*: the generic ones, then the tool's own."""
    flags = _generic(step)
    tool_check = TOOL_CHECKS.get(step.tool)
    if tool_check is not None:
        flags += tool_check(step)
    return [f"⚠ {flag}" for flag in flags]
