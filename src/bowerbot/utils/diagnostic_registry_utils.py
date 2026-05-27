# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Per-process registry of diagnostic checks against a composed stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pxr import Usd

from bowerbot.schemas import Finding

CheckFn = Callable[[Usd.Stage, Usd.Prim | None], list[Finding]]
Predicate = Callable[[Usd.Stage, Usd.Prim | None], bool]


@dataclass(frozen=True)
class RegisteredCheck:
    """One diagnostic check declared by a subsystem."""

    check_id: str
    subsystem: str
    fn: CheckFn
    applies_to: Predicate


CHECKS: list[RegisteredCheck] = []


def register(
    check_id: str, subsystem: str, applies_to: Predicate,
) -> Callable[[CheckFn], CheckFn]:
    """Decorator: register *fn* as a diagnostic check for *subsystem*."""
    def decorator(fn: CheckFn) -> CheckFn:
        CHECKS.append(RegisteredCheck(
            check_id=check_id,
            subsystem=subsystem,
            fn=fn,
            applies_to=applies_to,
        ))
        return fn
    return decorator


def run(stage: Usd.Stage, focus: Usd.Prim | None) -> list[Finding]:
    """Run every check whose predicate matches (*stage*, *focus*)."""
    findings: list[Finding] = []
    for check in CHECKS:
        if check.applies_to(stage, focus):
            findings.extend(check.fn(stage, focus))
    return findings


def has_applicable_check(stage: Usd.Stage, focus: Usd.Prim | None) -> bool:
    """Whether any registered check's predicate matches (*stage*, *focus*)."""
    return any(c.applies_to(stage, focus) for c in CHECKS)


def resolve_focus(
    stage: Usd.Stage, focus_path: str | None,
) -> tuple[Usd.Prim | None, str | None]:
    """Resolve *focus_path* to a prim; broad containers normalize to scene-wide."""
    if not focus_path:
        return None, None
    prim = stage.GetPrimAtPath(focus_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim not found: {focus_path}")
    if prim == stage.GetDefaultPrim() or not has_applicable_check(stage, prim):
        return None, None
    return prim, focus_path


def register_core_checks() -> None:
    """Import every core ``*_diagnostic_utils`` module so its checks register."""
    from bowerbot.utils import physics_diagnostic_utils  # noqa: F401
